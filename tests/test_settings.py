import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from core.pypoprf.config.settings import Settings


def write_raster(path, values=None, transform=None, count=1, nodata=-9999):
    values = np.arange(32 * 32, dtype=np.float32).reshape(32, 32) if values is None else values
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
                       count=count, dtype=values.dtype, crs="EPSG:4326",
                       transform=transform or from_origin(20, 10, 0.01, 0.01), nodata=nodata) as dst:
        for band in range(1, count + 1):
            dst.write(values, band)
    return str(path)


@pytest.fixture
def settings_inputs(tmp_path):
    master = write_raster(tmp_path / "master.tif", np.ones((32, 32), dtype=np.float32))
    covariate = write_raster(tmp_path / "covariate.tif")
    census = tmp_path / "census.csv"
    pd.DataFrame({"id": [1, 2], "sum": [10, 20]}).to_csv(census, index=False)
    return {"work_dir": str(tmp_path), "data_dir": ".", "mastergrid": master,
            "covariates": {"x": covariate}, "census_data": str(census),
            "census_pop_column": "sum", "census_id_column": "id",
            "block_size": (16, 16), "n_estimators": 12, "max_workers": 1,
            "cv_strategy": "shuffled_zone"}


def test_validation_preserves_source_csv_and_config(settings_inputs, tmp_path):
    source = tmp_path / "census.csv"
    original = source.read_bytes()
    config = tmp_path / "config.yaml"
    config.write_text("do not rewrite me", encoding="utf-8")
    settings = Settings(**settings_inputs, output_dir="custom/results")
    assert settings.census["pop_column"] == "sum"
    assert source.read_bytes() == original
    assert config.read_text() == "do not rewrite me"
    assert settings.output_dir == tmp_path / "custom" / "results"


@pytest.mark.parametrize("changes", [
    {"max_workers": 0}, {"max_workers": True}, {"block_size": [15, 32]},
    {"block_size": [16]}, {"log_scale": "true"}, {"selection_threshold": np.nan},
    {"selection_threshold": -1}, {"random_seed": -1}, {"cv_folds": 1},
    {"n_estimators": 0}, {"logging": {"file": "../config.yaml"}},
    {"cv_strategy": "invented"}, {"spatial_grid": [0, 4]}, {"spatial_grid": [4.5, 4]},
    {"logging": {"level": "not-a-level"}}, {"logging": {"file": "input.tif"}},
    {"logging": {"file": "NUL.log"}}, {"logging": {"file": "file.log:stream.log"}},
    {"constrain": "missing.tif"}, {"mastergrid": None},
])
def test_invalid_parameters_fail_preflight(settings_inputs, changes):
    with pytest.raises((ValueError, FileNotFoundError)):
        Settings(**(settings_inputs | changes))


@pytest.mark.parametrize("rows", [
    {"id": [1, 1], "sum": [1, 2]}, {"id": [1, np.nan], "sum": [1, 2]},
    {"id": [1, 1.5], "sum": [1, 2]}, {"id": [1, 2], "sum": [1, -1]},
    {"id": [1, 2], "sum": [1, np.inf]}, {"id": [1, 2], "sum": [1, np.nan]},
])
def test_all_census_rows_are_checked(settings_inputs, rows):
    pd.DataFrame(rows).to_csv(settings_inputs["census_data"], index=False)
    with pytest.raises(ValueError):
        Settings(**settings_inputs)


def test_duplicate_csv_header_is_not_hidden_by_pandas(settings_inputs):
    from pathlib import Path
    Path(settings_inputs["census_data"]).write_text("id,sum,sum\n1,10,20\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        Settings(**settings_inputs)


def test_ids_cannot_round_into_representable_range(settings_inputs):
    from pathlib import Path
    Path(settings_inputs["census_data"]).write_text("id,sum\n9007199254740993,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="representable"):
        Settings(**settings_inputs)


def test_group_column_preflight_checks_census(settings_inputs):
    with pytest.raises(ValueError, match="cv_group_column"):
        Settings(**settings_inputs, cv_group_column="region")


@pytest.mark.parametrize("column", ["id", "sum"])
def test_direct_census_validation_rejects_complex_values(column):
    data = pd.DataFrame({"id": [1], "sum": [10]})
    data[column] = [1 + 3j]
    with pytest.raises(ValueError, match="real"):
        Settings.validate_census_frame(data, "id", ["sum"])


@pytest.mark.parametrize("role", ["covariates", "mask", "constrain"])
def test_same_shape_shifted_grid_rejected(settings_inputs, tmp_path, role):
    shifted = write_raster(tmp_path / "shifted.tif", transform=from_origin(20.01, 10, .01, .01))
    change = {role: {"x": shifted} if role == "covariates" else shifted}
    with pytest.raises(ValueError, match="affine"):
        Settings(**(settings_inputs | change))


def test_roundoff_tolerated_but_second_pixel_axis_checked(settings_inputs, tmp_path):
    rounded = write_raster(tmp_path / "rounded.tif", transform=from_origin(20 + 1e-14, 10, .01, .01))
    Settings(**(settings_inputs | {"mask": rounded}))
    changed = write_raster(tmp_path / "changed.tif", transform=from_origin(20, 10, .01, .011))
    with pytest.raises(ValueError, match="affine"):
        Settings(**(settings_inputs | {"mask": changed}))


def test_multiband_rejected(settings_inputs, tmp_path):
    multiband = write_raster(tmp_path / "multiband.tif", count=2)
    with pytest.raises(ValueError, match="one raster band"):
        Settings(**(settings_inputs | {"mask": multiband}))


def test_agesex_metadata_is_ignored_and_ids_are_checked(settings_inputs, tmp_path):
    age = tmp_path / "age.csv"
    pd.DataFrame({"id": [2, 1], "f0": [10, 5], "m0": [10, 5], "flag": ["ok", "ok"]}).to_csv(age, index=False)
    Settings(**settings_inputs, agesex_data=str(age))
    pd.DataFrame({"id": [1, 3], "f0": [5, 10]}).to_csv(age, index=False)
    with pytest.raises(ValueError, match="match census"):
        Settings(**settings_inputs, agesex_data=str(age))


@pytest.mark.parametrize("content", ["", "[]", "work_dir: .", "null"])
def test_yaml_structure_validation(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.from_file(path)


def test_core_settings_import_does_not_import_qgis():
    result = subprocess.run([sys.executable, "-c", "from core.pypoprf.config.settings import Settings; "
                             "import sys; assert 'qgis' not in sys.modules"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_effective_config_snapshot_roundtrips_all_defaults_without_source_writes(settings_inputs, tmp_path):
    import inspect
    import yaml
    from core.pypoprf.utils.runtime import CancellationToken

    source = tmp_path / "census.csv"
    before = source.read_bytes()
    settings = Settings(**settings_inputs, cancellation_token=CancellationToken(),
                        output_dir="custom", logging={"file": "custom.log"})
    snapshot = settings.to_config()
    expected = set(inspect.signature(Settings.__init__).parameters) - {"self", "cancellation_token"}
    assert set(snapshot) == expected
    assert snapshot["random_seed"] == 42
    assert snapshot["cv_folds"] == 5
    assert snapshot["spatial_grid"] == [4, 4]
    assert snapshot["logging"]["file"] == "custom.log"
    assert snapshot["mastergrid"] == settings.mastergrid
    assert snapshot["data_dir"] == str(tmp_path)
    config_path = tmp_path / "replay.yaml"
    config_path.write_text(yaml.safe_dump(snapshot), encoding="utf-8")
    replayed = Settings.from_file(config_path)
    assert replayed.to_config() == snapshot
    assert source.read_bytes() == before
    snapshot["covariates"]["x"] = "changed"
    assert settings.covariate["x"] != "changed"


def test_effective_snapshot_roundtrips_disabled_logging(settings_inputs):
    settings = Settings(**settings_inputs, logging={"file": None})
    assert Settings(**settings.to_config()).logging["file"] is None


@pytest.mark.parametrize("role", ["mastergrid", "mask", "constrain", "covariates", "census_data", "agesex_data"])
def test_file_alias_guard_precedes_resolution_portably(settings_inputs, tmp_path, monkeypatch, role):
    import yaml

    alias = tmp_path / "alias.tif"
    alias.write_bytes(Path(settings_inputs["mastergrid"]).read_bytes())
    sidecar = Path(str(alias) + ".msk")
    sidecar.write_bytes(b"alias-specific mask namespace")
    config = tmp_path / "alias.yaml"
    inputs = settings_inputs | {role: {"x": str(alias)} if role == "covariates" else str(alias)}
    config.write_text(yaml.safe_dump(inputs), encoding="utf-8")
    tracked = [alias, sidecar, config, Path(settings_inputs["census_data"])]
    before = {path: path.read_bytes() for path in tracked}
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == alias or original(path))
    with pytest.raises(ValueError, match="File-symlink.*GDAL sidecars"):
        Settings(**inputs)
    with pytest.raises(ValueError, match="File-symlink.*GDAL sidecars"):
        Settings.from_file(config)
    assert {path: path.read_bytes() for path in tracked} == before
    assert not (tmp_path / "output").exists()


def test_real_masked_file_symlink_rejected_by_settings_and_cli(settings_inputs, tmp_path):
    import json
    import yaml

    alias = tmp_path / "alias.tif"
    try:
        alias.symlink_to(settings_inputs["mastergrid"])
    except OSError as exc:
        pytest.skip(f"File symlink creation unavailable: {exc}")
    # This is a real GDAL external mask, not merely a name-only fixture.
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(alias, "r+") as dataset:
            mask = np.full((32, 32), 255, dtype=np.uint8)
            mask[0] = 0
            dataset.write_mask(mask)
    sidecar = Path(str(alias) + ".msk")
    assert sidecar.is_file()
    with rasterio.open(alias) as dataset:
        assert np.count_nonzero(dataset.read_masks(1)) == 31 * 32
    with rasterio.open(settings_inputs["mastergrid"]) as dataset:
        assert np.count_nonzero(dataset.read_masks(1)) == 32 * 32
    inputs = settings_inputs | {"mastergrid": str(alias)}
    config = tmp_path / "alias.yaml"
    config.write_text(yaml.safe_dump(inputs), encoding="utf-8")
    tracked = [Path(settings_inputs["mastergrid"]), sidecar, config, Path(settings_inputs["census_data"])]
    before = {path: path.read_bytes() for path in tracked}
    with pytest.raises(ValueError, match="File-symlink"):
        Settings(**inputs)
    with pytest.raises(ValueError, match="File-symlink"):
        Settings.from_file(config)
    output = tmp_path / "cli-output"
    result = subprocess.run([sys.executable, "-m", "core.pypoprf", "--config", str(config),
                             "--output-dir", str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    terminal = [event for event in events if event.get("event") == "result"][-1]
    assert terminal["status"] == "failed"
    assert terminal["run_dir"] is None
    assert "File-symlink" in terminal["message"]
    assert not output.exists()
    assert {path: path.read_bytes() for path in tracked} == before


def test_real_hardlink_preserves_its_external_mask_namespace(settings_inputs, tmp_path):
    import os
    import yaml
    from core.pypoprf.cli import input_resources
    from core.pypoprf.utils.runtime import CancellationToken

    alias = tmp_path / "hardlink.tif"
    os.link(settings_inputs["covariates"]["x"], alias)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(alias, "r+") as dataset:
            mask = np.full((32, 32), 255, dtype=np.uint8)
            mask[0] = 0
            dataset.write_mask(mask)
    sidecar = Path(str(alias) + ".msk")
    assert sidecar.is_file()
    tracked = [alias, sidecar, Path(settings_inputs["census_data"])]
    before = {path: path.read_bytes() for path in tracked}
    inputs = settings_inputs | {"covariates": {"x": str(alias)}}
    settings = Settings(**inputs)
    assert settings.covariate["x"] == str(alias.resolve())
    config = tmp_path / "hardlink.yaml"
    config.write_text(yaml.safe_dump(settings.to_config()), encoding="utf-8")
    replayed = Settings.from_file(config)
    assert replayed.covariate["x"] == str(alias.resolve())
    resources = input_resources(replayed, CancellationToken())
    assert sidecar.resolve() in resources
    with rasterio.open(replayed.covariate["x"]) as dataset:
        assert np.count_nonzero(dataset.read_masks(1)) == 31 * 32
    with rasterio.open(settings_inputs["covariates"]["x"]) as dataset:
        assert np.count_nonzero(dataset.read_masks(1)) == 32 * 32
    assert {path: path.read_bytes() for path in tracked} == before


def test_parent_directory_alias_keeps_file_namespace(settings_inputs, tmp_path):
    alias = tmp_path / "directory-alias"
    try:
        alias.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlink creation unavailable: {exc}")
    settings = Settings(**(settings_inputs | {"mastergrid": str(alias / "master.tif")}))
    assert settings.mastergrid == settings_inputs["mastergrid"]
