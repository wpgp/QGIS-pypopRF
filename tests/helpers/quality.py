"""Saved-run fixtures shared by service and genuine Qt acceptance tests."""
import csv
import hashlib
import json


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
