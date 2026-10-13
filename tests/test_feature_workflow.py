"""Independent end-to-end acceptance of derived projects and AOI population totals."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
import yaml

from q_models.quality_report import load_quality_report


def write_raster(path, values, resolution):
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1],
                       height=values.shape[0], count=1, dtype=values.dtype,
                       crs="EPSG:3857", transform=from_origin(0, 4, resolution, resolution)) as target:
        target.write(values, 1)


def polygon_feature(identifier, left, bottom, right, top):
    return {"type": "Feature", "properties": {"zone": identifier}, "geometry": {
        "type": "Polygon", "coordinates": [[[left, bottom], [right, bottom],
                                                [right, top], [left, top], [left, bottom]]]}}


def write_polygons(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "crs": {
        "type": "name", "properties": {"name": "EPSG:3857"}}, "features": features}),
        encoding="utf-8")


def run_json_cli(arguments):
    completed = subprocess.run([sys.executable, "-X", "utf8", *arguments],
                               capture_output=True, text=True, encoding="utf-8",
                               timeout=60, check=False, env=dict(os.environ, PYTHONIOENCODING="cp1252"))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    events = [json.loads(line) for line in completed.stdout.splitlines()]
    assert events and events[-1]["event"] == "result"
    assert events[-1]["status"] == "complete"
    return events[-1]


@pytest.mark.integration
@pytest.mark.parametrize("partial_extent", [False, True])
def test_polygon_prepare_analysis_and_aoi_summary_preserve_sources(tmp_path, partial_extent):
    source = tmp_path / "исходники_人口"
    source.mkdir()
    reference, covariate = source / "reference.tif", source / "distance.tif"
    write_raster(reference, np.ones((4, 4), dtype="uint8"), 1)
    write_raster(covariate, np.arange(1, 65, dtype="float32").reshape(8, 8), .5)
    census = source / "census.csv"
    census.write_text("zone,population\n4,40\n2,20\n1,10\n3,30\n", encoding="utf-8")
    boundaries = source / "boundaries.geojson"
    write_polygons(boundaries, [polygon_feature(1, 0, 2, 2, 4), polygon_feature(2, 2, 2, 4, 4),
                                polygon_feature(3, 0, 0, 2, 2), polygon_feature(4, 2, 0, 4, 2)])
    sources = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()}
    prepared = tmp_path / "проект_人口"
    request_path = tmp_path / "prepare.json"
    request = {"schema_version": 1, "request_id": "a" * 32, "operation": "prepare",
               "output_dir": str(prepared), "reference_raster": str(reference),
               "census": {"path": str(census), "id_column": "zone", "population_column": "population"},
               "census_polygons": {"path": str(boundaries), "id_column": "zone"},
               "covariates": [{"name": "distance", "path": str(covariate),
                               "quantity": "continuous", "resampling": "average"}], "tile_size": 512}
    request_path.write_text(json.dumps(request), encoding="utf-8")
    event = run_json_cli(["-m", "core.pypoprf.tools", "--request", str(request_path)])
    assert event["request_id"] == request["request_id"]
    report = json.loads(Path(event["report_path"]).read_text(encoding="utf-8"))
    assert report["ready"] is True and not report["errors"]
    assert report["request_id"] == request["request_id"]
    config_path = Path(event["config_path"])
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.update(n_estimators=8, cv_folds=2, spatial_grid=[2, 2], max_workers=1)
    # Only the newly derived project's configuration is edited; sources are immutable.
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepared / "output" / "runs" / "acceptance"
    run_json_cli(["-m", "core.pypoprf", "--config", str(config_path), "--output-dir", str(run)])
    quality = load_quality_report(run)
    assert not quality.errors
    assert quality.run_status == quality.cv_status == "complete"
    assert len(quality.points) == 4 and quality.crs
    assert quality.baseline_metrics and "Engine-reported" in quality.conservation_label
    population = run / "population_unconstrained.tif"
    with rasterio.open(population) as dataset:
        values = dataset.read(1, masked=True)
        assert dataset.shape == (4, 4)
        assert float(values.sum()) == pytest.approx(100, abs=1e-6)
        for identifier, rows, columns in ((1, slice(0, 2), slice(0, 2)),
                                          (2, slice(0, 2), slice(2, 4)),
                                          (3, slice(2, 4), slice(0, 2)),
                                          (4, slice(2, 4), slice(2, 4))):
            assert float(values[rows, columns].sum()) == pytest.approx(identifier * 10, abs=1e-6)
    aoi = tmp_path / "aoi.geojson"
    write_polygons(aoi, [polygon_feature(1, -2 if partial_extent else 0, 0, 2, 4)])
    summary_request = {"schema_version": 1, "request_id": "b" * 32, "operation": "population_summary",
                       "output_dir": str(tmp_path / "summary"), "population_raster": str(population),
                       "aoi": {"path": str(aoi)}, "inclusion": "cell_center", "units": "persons_per_pixel"}
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary_request), encoding="utf-8")
    summary_event = run_json_cli(["-m", "core.pypoprf.tools", "--request", str(summary_path)])
    summary = json.loads(Path(summary_event["report_path"]).read_text(encoding="utf-8"))["summary"]
    assert summary["sum_persons"] == pytest.approx(40, abs=1e-6)
    assert summary["valid_cells"] == summary["selected_cells"] == 8
    assert summary["coverage_fraction"] == 1
    assert summary["aoi_extends_outside_raster"] is partial_extent
    assert summary["complete_coverage"] is (not partial_extent)
    assert summary["inclusion"] == "cell_center"
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in sources.items())
