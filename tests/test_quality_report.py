import csv
import hashlib
import importlib
import json
import math
import os
import subprocess
import sys

import pytest

from q_models import quality_report as quality


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def fixture_run(root, inventory=True, status="complete"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "population.tif").write_bytes(b"fixture: dashboard never opens a raster")
    metrics = {"status": "complete", "scale": "density", "scheme": "spatial_blocks",
               "target_units": "population_per_eligible_mastergrid_pixel", "n_zones": 4, "n_folds": 2,
               "rmse": 1., "mae": 1., "r2": 1 - 4 / 68,
               "provenance": {"source": "mastergrid_valid_pixel_centroids", "crs": "EPSG:3857",
                              "limitations": ["No buffer between blocks"]}}
    (root / "cv_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    write_csv(root / "cv_predictions.csv", ["zone_id", "density", "prediction", "fold", "group"],
              [[1, 0, 1, 0, "a"], [2, 2, 3, 0, "a"], [3, 8, 7, 1, "b"], [4, 10, 9, 1, "b"]])
    write_csv(root / "cv_zone_geometry.csv", ["zone_id", "centroid_x", "centroid_y"],
              [[4, 40, 80], [3, 30, 60], [2, 20, 40], [1, 10, 20]])
    write_csv(root / "feature_importance.csv", ["feature", "importance", "std"],
              [["building_avg", .7, .1], ["unused_avg", -.05, .2]])
    manifest = {"status": status, "outputs": ["population.tif"] if status == "complete" else []}
    if inventory:
        manifest["artifacts"] = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                 for path in root.iterdir() if path.is_file()]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def update_metrics(root, **fields):
    path = root / "cv_metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics.update(fields)
    path.write_text(json.dumps(metrics), encoding="utf-8")


def test_quality_oof_baseline_geometry_and_source_preservation(tmp_path):
    run = fixture_run(tmp_path / "run")
    before = {path.name: path.read_bytes() for path in run.iterdir()}
    report = quality.load_quality_report(run)
    assert report.run_status == report.cv_status == "complete"
    assert "Engine-reported" in report.conservation_label
    assert len(report.points) == 4 and not report.errors
    assert dict(report.baseline_metrics) == {"rmse": math.sqrt(65), "mae": 8.}
    # Train mean on OTHER fold: [9,9,1,1], not all-zone mean5 (leaks test targets).
    assert dict(report.baseline_metrics)["rmse"] != math.sqrt(17)
    request = report.zone_request([1, 4])
    assert request["zone_ids"] == [1, 4] and request["crs"] == "EPSG:3857"
    assert request["centroids"] == [{"zone_id": 1, "x": 10., "y": 20.},
                                    {"zone_id": 4, "x": 40., "y": 80.}]
    assert report.feature_importance[1].importance < 0
    assert any("not independent fine-pixel" in value for value in report.limits)
    assert {path.name: path.read_bytes() for path in run.iterdir()} == before


@pytest.mark.parametrize("status", ["failed", "cancelled", "running"])
def test_incomplete_run_training_quality_is_separate_from_conservation(tmp_path, status):
    run = fixture_run(tmp_path / "run", status=status)
    report = quality.load_quality_report(run)
    assert report.run_status == status and report.cv_status == "complete"
    assert "not established" in report.conservation_label and len(report.points) == 4
    assert any("did not complete" in limit for limit in report.limits)


def test_unavailable_cv_and_empty_selection_do_not_fake_quality(tmp_path):
    assert quality.load_quality_report(None).run_status == "not_selected"
    run = fixture_run(tmp_path / "run", inventory=False)
    update_metrics(run, status="unavailable", reason="Only one independent group")
    report = quality.load_quality_report(run)
    assert report.cv_status == "unavailable" and not report.points and not report.baseline_metrics
    assert "Only one independent group" in report.limits
    assert report.zone_request()["zone_ids"] == []


@pytest.mark.parametrize("mutation", ["missing_fold", "duplicate_id", "nonfinite", "negative", "group_leak", "truncated",
                                       "bad_score", "huge_fold_count", "duplicate_header", "extra_cell"])
def test_malformed_or_non_oof_predictions_are_never_plotted(tmp_path, mutation):
    run = fixture_run(tmp_path / "run", inventory=False)
    path = run / "cv_predictions.csv"
    text = path.read_text(encoding="utf-8")
    if mutation == "missing_fold":
        text = "zone_id,density,prediction\n1,0,1\n"
    elif mutation == "duplicate_id":
        text = text.replace("2,2,3", "1,2,3")
    elif mutation == "nonfinite":
        text = text.replace("1,0,1", "1,nan,1")
    elif mutation == "negative":
        text = text.replace("1,0,1", "1,0,-1")
    elif mutation == "group_leak":
        text = text.replace("3,8,7,1,b", "3,8,7,1,a")
    elif mutation == "truncated":
        text = "\n".join(text.splitlines()[:-1]) + "\n"
    elif mutation == "bad_score":
        update_metrics(run, rmse=42)
    elif mutation == "huge_fold_count":
        update_metrics(run, n_folds=2 ** 53)
    elif mutation == "duplicate_header":
        text = text.replace("zone_id,density", "density,density")
    else:
        text = text.replace("1,0,1,0,a", "1,0,1,0,a,extra")
    path.write_text(text, encoding="utf-8")
    report = quality.load_quality_report(run)
    assert not report.points and not report.baseline_metrics and report.errors


@pytest.mark.parametrize("contents", ["[]", "null", '{"status":[]}', '{"status":"complete","outputs":["../outside.tif"]}',
                                     '{"status":"complete","x":NaN}', "[" * 2000])
def test_malformed_manifest_fails_closed_without_exception(tmp_path, contents):
    run = fixture_run(tmp_path / "run")
    (run / "manifest.json").write_text(contents, encoding="utf-8")
    report = quality.load_quality_report(run)
    assert report.run_status == "invalid" and not report.points


def test_hash_mismatch_quarantines_changed_component(tmp_path):
    run = fixture_run(tmp_path / "run")
    (run / "cv_predictions.csv").write_text("changed", encoding="utf-8")
    report = quality.load_quality_report(run)
    assert not report.points and any("SHA-256" in message for message in report.errors)
    assert report.feature_importance


def test_existing_inventory_missing_consumed_artifact_is_not_silently_trusted(tmp_path):
    run = fixture_run(tmp_path / "run")
    path = run / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"] = [record for record in manifest["artifacts"] if record["path"] != "cv_predictions.csv"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = quality.load_quality_report(run)
    assert not report.points and not report.metrics
    assert any("missing from" in message for message in report.errors)


def test_unknown_validation_strategy_does_not_assert_oof_quality(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    update_metrics(run, scheme="final_training_predictions")
    report = quality.load_quality_report(run)
    assert not report.points and not report.metrics and report.cv_status == "unavailable"


def test_geometry_mismatch_retains_oof_but_requests_raw_ids(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    write_csv(run / "cv_zone_geometry.csv", ["zone_id", "centroid_x", "centroid_y"], [[999, 10, 20]])
    report = quality.load_quality_report(run)
    assert report.points and report.crs is None
    assert report.zone_request([1])["zone_ids"] == [1]
    assert report.zone_request([1])["centroids"] == []
    assert any("Centroids" in message for message in report.errors)


@pytest.mark.parametrize("name", ["../outside.tif", "..\\outside.tif", "C:\\outside.tif", "C:relative.tif", "\\\\server\\share\\raster.tif"])
def test_cross_platform_outside_output_paths_are_rejected(tmp_path, name):
    run = fixture_run(tmp_path / "run")
    path = run / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["outputs"] = [name]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert quality.load_quality_report(run).run_status == "invalid"


def test_windows_relative_output_separators_are_portable(tmp_path):
    run = fixture_run(tmp_path / "run")
    (run / "agesex").mkdir()
    (run / "agesex" / "population_f0.tif").write_bytes(b"fixture")
    path = run / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["outputs"].append("agesex\\population_f0.tif")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert quality.load_quality_report(run).points


def test_csv_and_byte_bounds_never_present_partial_statistics(tmp_path, monkeypatch):
    run = fixture_run(tmp_path / "run", inventory=False)
    monkeypatch.setattr(quality, "MAX_CSV_BYTES", 20)
    report = quality.load_quality_report(run)
    assert not report.points and report.errors
    monkeypatch.setattr(quality, "MAX_CSV_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(quality, "_csv", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("row limit")))
    assert not quality.load_quality_report(run).points


def test_real_csv_row_limit_and_json_byte_limit(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    with pytest.raises(ValueError, match="row limit"):
        quality._csv(run, "cv_predictions.csv", {"zone_id"}, {}, max_rows=3)
    with pytest.raises(ValueError, match="byte limit"):
        quality._read(run, "manifest.json", 1, {})


def test_large_finite_scores_do_not_overflow():
    metrics = quality._scores([1.79e308, 0], [0, 1.79e308])
    assert all(math.isfinite(value) for _, value in metrics)


@pytest.mark.parametrize("value", ["1e10000000", "-1e10000000", "NaN", "Infinity", "9007199254740993", "1.5"])
def test_extreme_ids_are_rejected_without_decimal_context_overflow(value):
    with pytest.raises(ValueError):
        quality._integer(value)


def test_impossible_recorded_r2_is_not_displayed_as_quality(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    update_metrics(run, r2=10)
    report = quality.load_quality_report(run)
    assert not report.metrics and not report.points


def test_baseline_dominating_excluded_fold_preserves_small_training_mean():
    points = (quality.ZonePoint(1, 1e308, 0., 0), quality.ZonePoint(2, 1e-200, 0., 1),
              quality.ZonePoint(3, 3e-200, 0., 2))
    means = quality._training_means(points)
    assert means[0] == 2e-200
    assert means[1] == means[2] == 5e307


def test_many_fold_baseline_visits_each_zone_once(tmp_path, monkeypatch):
    points = tuple(quality.ZonePoint(index, float(index), 0., index) for index in range(2000))
    original, visited = quality._mean, []
    def count_values(values):
        visited.append(len(values))
        return original(values)
    monkeypatch.setattr(quality, "_mean", count_values)
    means = quality._training_means(points)
    assert sum(visited) == len(points)
    for index in (0, 50, 1999):
        assert math.isclose(means[index], (1999000 - index) / 1999, rel_tol=1e-12)


def test_loader_does_not_import_qt_scientific_modules_or_pickle(tmp_path):
    script = "import q_models.quality_report,sys; assert not any(name in sys.modules for name in ('qgis','numpy','pandas','sklearn','rasterio','joblib'))"
    process = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stderr
    run = fixture_run(tmp_path / "run")
    (run / "model_bundle.pkl.gz").write_bytes(b"never deserialize this")
    assert quality.load_quality_report(run).points


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junctions")
@pytest.mark.parametrize("ancestor", [False, True])
def test_real_junction_artifact_or_run_is_not_read(tmp_path, ancestor):
    outside = fixture_run(tmp_path / "outside")
    linked = tmp_path / "linked"
    target = outside.parent if ancestor else outside
    subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(linked), str(target)], capture_output=True, check=True)
    try:
        assert linked.is_junction() and not linked.is_symlink()
        assert quality.load_quality_report(linked / "outside" if ancestor else linked).run_status == "invalid"
    finally:
        assert linked.resolve() == target.resolve()
        linked.rmdir()


def test_symlink_artifact_is_never_followed(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    target = tmp_path / "outside.csv"
    target.write_bytes((run / "cv_predictions.csv").read_bytes())
    (run / "cv_predictions.csv").unlink()
    try:
        (run / "cv_predictions.csv").symlink_to(target)
    except OSError:
        pytest.skip("User/platform cannot create symlinks")
    report = quality.load_quality_report(run)
    assert not report.points and any("Linked" in message for message in report.errors)


def test_top_error_order_and_no_geometry_for_manual_group(tmp_path):
    run = fixture_run(tmp_path / "run", inventory=False)
    update_metrics(run, provenance={"source": "train_arguments", "limitations": []})
    report = quality.load_quality_report(run)
    assert [point.zone_id for point in report.high_error_zones] == [1, 2, 3, 4]
    assert report.crs is None and report.zone_request()["centroids"] == []
    assert any("No artifact SHA" in message for message in report.limits)


def test_package_alias_loader_has_no_root_import_dependency():
    assert importlib.import_module("q_models.quality_report").QualityReport is quality.QualityReport
