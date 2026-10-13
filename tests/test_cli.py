import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
import yaml

from core.pypoprf.cli import FileCancellationToken, fingerprint, input_resources
from core.pypoprf.utils.runtime import CancelledError


def test_cli_invalid_preflight_is_structured_failure_without_creating_run(tmp_path):
    config = tmp_path / "invalid.yaml"
    config.write_text("work_dir: .\n", encoding="utf-8")
    output = tmp_path / "run"
    process = subprocess.run(
        [sys.executable, "-m", "core.pypoprf", "--config", str(config), "--output-dir", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert process.returncode == 1
    event = json.loads(process.stdout)
    assert event["event"] == "result" and event["status"] == "failed"
    assert event["run_dir"] is None
    assert not output.exists()


def test_engine_child_cancellation_marker_is_checked_before_input_read(tmp_path):
    marker = tmp_path / "cancel.request"
    marker.touch()
    token = FileCancellationToken(marker)
    with pytest.raises(CancelledError):
        token.check()


def test_input_fingerprint_identifies_content_and_metadata(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes(b"id,pop\n1,50\n")
    initial = fingerprint(path, FileCancellationToken())
    path.write_bytes(b"id,pop\n1,60\n")
    changed = fingerprint(path, FileCancellationToken())
    assert initial["sha256"] != changed["sha256"]
    assert initial["bytes"] == changed["bytes"]


@pytest.mark.integration
@pytest.mark.parametrize("run_name", ["run", "результат"])
def test_cli_complete_run_has_durable_config_provenance_and_verified_maps(tmp_path, run_name):
    data = tmp_path / "data"
    data.mkdir()
    zones = np.repeat(np.arange(1, 7, dtype="int32"), 4).reshape(4, 6)
    for name, values in (("zones", zones), ("building", zones.astype("float32") + 1)):
        with rasterio.open(data / f"{name}.tif", "w", driver="GTiff", width=6, height=4,
                           count=1, dtype=values.dtype, crs="EPSG:3857",
                           transform=from_origin(0, 100, 10, 10)) as out:
            out.write(values, 1)
    census = pd.DataFrame({"zone": np.arange(1, 7), "sum": np.arange(6) * 40.0})
    census.to_csv(data / "census.csv", index=False)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "work_dir": ".", "mastergrid": "zones.tif", "covariates": {"building": "building.tif"},
        "census_data": "census.csv", "census_id_column": "zone", "census_pop_column": "sum",
        "n_estimators": 6, "cv_folds": 2, "cv_strategy": "shuffled_zone",
    }), encoding="utf-8")
    output = tmp_path / run_name
    process = subprocess.run(
        [sys.executable, "-m", "core.pypoprf", "--config", str(config), "--output-dir", str(output)],
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        env=dict(os.environ, PYTHONIOENCODING="cp1252"),
    )
    assert process.returncode == 0, process.stderr
    events = [json.loads(line) for line in process.stdout.splitlines()]
    assert events[-1]["status"] == "complete"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["outputs"] == events[-1]["outputs"]
    assert manifest["status"] == "complete"
    assert len(manifest["inputs"]) == 3
    assert "core/model.py" in manifest["engine_source_sha256"]
    assert set(manifest["engine_adapter_source_sha256"]) == {"runtime_manager.py", "atomic_files.py"}
    assert manifest["runtime"]["distributions"]["rasterio"] == rasterio.__version__
    assert manifest["runtime"]["rasterio_gdal"] == rasterio.__gdal_version__
    assert len(manifest["packaged_dependency_lock_sha256"]) == 64
    assert isinstance(manifest["runtime"]["native_threadpools"], list)
    assert all(pool["num_threads"] <= 1 for pool in manifest["runtime"]["native_threadpools"])
    snapshot = yaml.safe_load((output / manifest["config_snapshot"]).read_text())
    assert snapshot["work_dir"] == str(tmp_path)
    assert snapshot["mastergrid"] == str(data / "zones.tif")
    assert snapshot["random_seed"] == 42
    assert snapshot["spatial_grid"] == [4, 4]
    assert "cancellation_token" not in snapshot
    artifacts = {record["path"]: record for record in manifest["artifacts"]}
    assert "model_bundle.pkl.gz" in artifacts
    assert "cv_metrics.json" in artifacts
    assert "run_config.yaml" in artifacts
    assert all(len(record["sha256"]) == 64 for record in artifacts.values())
    with rasterio.open(output / "population_unconstrained.tif") as result:
        values = result.read(1, masked=True)
    for row in census.to_dict("records"):
        assert float(values[zones == row["zone"]].sum()) == pytest.approx(row["sum"], abs=1e-5)
    assert list(pd.read_csv(data / "census.csv")) == ["zone", "sum"]


def test_input_resources_include_external_gdal_validity_mask(tmp_path):
    from types import SimpleNamespace

    raster = tmp_path / "source.tif"
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(raster, "w", driver="GTiff", width=2, height=2,
                           count=1, dtype="int32", crs="EPSG:3857",
                           transform=from_origin(0, 20, 10, 10)) as out:
            out.write(np.ones((2, 2), dtype="int32"), 1)
            out.write_mask(np.array([[255, 0], [255, 255]], dtype="uint8"))
    census = tmp_path / "census.csv"
    census.write_text("id,pop\n1,30\n", encoding="utf-8")
    settings = SimpleNamespace(mastergrid=str(raster), covariate={"x": str(raster)},
                               census={"path": str(census)}, agesex_data=None,
                               mask=None, constrain=None)
    resources = input_resources(settings, FileCancellationToken())
    assert Path(str(raster) + ".msk") in resources
    assert resources == sorted({raster, census, Path(str(raster) + ".msk")})
