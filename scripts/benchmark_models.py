"""Compare fixed candidate models on identical, recorded spatial outer folds.

This is a research diagnostic, not a runtime model switch or fine-pixel accuracy
test. Run with ``python -m scripts.benchmark_models --output <fresh-directory>``.
No source case-study file is changed and no hyperparameters are selected on the
reported folds. The original engine environment is recorded with the results.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_limits

from core.pypoprf.config.settings import Settings
from core.pypoprf.core.feature_extraction import FeatureExtractor
from core.pypoprf.core.model import Model

ROOT = Path(__file__).resolve().parents[1]


def run_benchmark(data_dir, output, n_estimators=100, cv_folds=5, spatial_grid=(4, 4), folds_from=None):
    data_dir, output = Path(data_dir).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Benchmark output must be a fresh directory")
    if output == data_dir or output.is_relative_to(data_dir):
        raise ValueError("Benchmark output must be outside the source data directory")
    files = sorted(data_dir.glob("*.tif"))
    sources = [*files, data_dir / "RWA_2026.csv"]
    source_hashes = {str(path.relative_to(data_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sources}
    covariates = {path.stem: str(path) for path in files if path.name != "rwa_mastergrid.tif"}
    settings = Settings(work_dir=str(output), data_dir=str(data_dir),
                        mastergrid="rwa_mastergrid.tif", covariates=covariates,
                        census_data="RWA_2026.csv", census_pop_column="pop", census_id_column="id",
                        output_dir=".", max_workers=2, random_seed=42, n_estimators=n_estimators,
                        cv_folds=cv_folds, cv_strategy="spatial", spatial_grid=spatial_grid)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    features = FeatureExtractor(settings).extract()
    extractor_seconds = time.monotonic() - started
    model = Model(settings)
    X, density, _ = model._prepare_data(features)
    model.target_transform = "log1p"
    centroid_started = time.monotonic()
    groups, provenance, geometry = model._spatial_groups(features.id.to_numpy())
    centroid_seconds = time.monotonic() - centroid_started
    if groups is None or len(pd.unique(groups)) < 2:
        raise ValueError("Dataset has insufficient occupied spatial blocks for a benchmark")
    folds = min(cv_folds, len(pd.unique(groups)))
    split_source = "current_environment_GroupKFold"
    if folds_from is None:
        splits = list(GroupKFold(folds).split(X, density, groups))
    else:
        recorded = json.loads(Path(folds_from).read_text(encoding="utf-8"))
        if recorded.get("source_sha256") != source_hashes:
            raise ValueError("Frozen benchmark folds refer to different source data")
        if recorded.get("spatial_provenance") != provenance:
            raise ValueError("Frozen benchmark folds use a different spatial grid or geometry")
        records = recorded.get("folds")
        if not isinstance(records, list) or len(records) < 2:
            raise ValueError("Frozen benchmark must provide at least two outer folds")
        splits, tested = [], set()
        all_groups = set(groups)
        for fold, record in enumerate(records):
            train_groups, test_groups = set(record["train_groups"]), set(record["test_groups"])
            if (record["fold"] != fold or not train_groups or not test_groups
                    or train_groups.intersection(test_groups)
                    or train_groups | test_groups != all_groups or tested.intersection(test_groups)):
                raise ValueError("Frozen benchmark folds are not disjoint complete group splits")
            train = np.flatnonzero(np.isin(groups, list(train_groups)))
            test = np.flatnonzero(np.isin(groups, list(test_groups)))
            if len(train) != record["n_train"] or len(test) != record["n_test"]:
                raise ValueError("Frozen benchmark fold sample counts differ")
            splits.append((train, test))
            tested.update(test_groups)
        if tested != all_groups:
            raise ValueError("Frozen benchmark does not test every spatial group exactly once")
        folds = len(splits)
        split_source = f"recorded_folds:{Path(folds_from).resolve()}"
    algorithms = ["uniform_training_mean", "building_surface_proportional",
                  "rf_log1p_selection", "rf_log1p_all_features", "hist_gradient_boosting_log1p"]
    predictions = {name: np.empty(len(features), dtype=float) for name in algorithms}
    duration = {name: 0.0 for name in algorithms}
    fold_ids = np.empty(len(features), dtype=int)
    building = next((name for name in X.columns if "buildings_surface" in name), None)
    if building is None:
        raise ValueError("A buildings_surface covariate is needed for the stated baseline")
    fold_records = []
    for fold, (train, test) in enumerate(splits):
        fold_ids[test] = fold
        fold_records.append({"fold": fold, "n_train": len(train), "n_test": len(test),
                             "train_groups": sorted(pd.unique(groups[train]).tolist()),
                             "test_groups": sorted(pd.unique(groups[test]).tolist())})
        start = time.monotonic()
        predictions["uniform_training_mean"][test] = float(np.mean(density[train]))
        duration["uniform_training_mean"] += time.monotonic() - start

        start = time.monotonic()
        support_train = np.maximum(X.iloc[train][building].to_numpy(dtype=float), 0)
        denominator = float(np.dot(support_train, support_train))
        coefficient = float(np.dot(support_train, density[train]) / denominator) if denominator > 0 else 0
        predictions["building_surface_proportional"][test] = coefficient * np.maximum(
            X.iloc[test][building].to_numpy(dtype=float), 0)
        duration["building_surface_proportional"] += time.monotonic() - start

        start = time.monotonic()
        forest, scaler, selected, _ = model._fit_procedure(X.iloc[train], density[train])
        predictions["rf_log1p_selection"][test] = model._inverse(
            forest.predict(scaler.transform(X.iloc[test][selected])))
        duration["rf_log1p_selection"] += time.monotonic() - start

        start = time.monotonic()
        scaler = RobustScaler().fit(X.iloc[train])
        forest = model._fit_forest(scaler.transform(X.iloc[train]), model._transform(density[train]))
        predictions["rf_log1p_all_features"][test] = model._inverse(forest.predict(scaler.transform(X.iloc[test])))
        duration["rf_log1p_all_features"] += time.monotonic() - start

        start = time.monotonic()
        histogram = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.1,
                                                  early_stopping=False, random_state=42)
        with threadpool_limits(limits=2):
            histogram.fit(X.iloc[train], model._transform(density[train]))
            predictions["hist_gradient_boosting_log1p"][test] = model._inverse(histogram.predict(X.iloc[test]))
        duration["hist_gradient_boosting_log1p"] += time.monotonic() - start
    rows = []
    for name, predicted in predictions.items():
        rows.append({"candidate": name, "rmse_density": float(np.sqrt(mean_squared_error(density, predicted))),
                     "mae_density": float(mean_absolute_error(density, predicted)),
                     "r2_density": float(r2_score(density, predicted)),
                     "fit_predict_seconds": duration[name]})
    results = pd.DataFrame(rows)
    results.to_csv(output / "candidate_metrics.csv", index=False)
    out_of_fold = geometry.assign(density=density, fold=fold_ids)
    for name, predicted in predictions.items():
        out_of_fold[name] = predicted
    out_of_fold.to_csv(output / "candidate_predictions.csv", index=False)
    metadata = {"dataset": "Bundled Rwanda 2026 census and supplied covariates",
                "n_zones": len(features), "n_features": X.shape[1], "n_folds": folds,
                "random_seed": 42, "rf_trees": n_estimators, "target_transform": "log1p",
                "thread_budget": 2,
                "split_source": split_source,
                "density_units": "population_per_eligible_mastergrid_pixel",
                "versions": model._versions(), "spatial_provenance": provenance,
                "folds": fold_records, "feature_names": list(X.columns),
                "building_feature": building, "feature_extraction_seconds": extractor_seconds,
                "centroid_scan_seconds": centroid_seconds,
                "total_seconds": time.monotonic() - started,
                "source_sha256": source_hashes,
                "limitations": ["One dataset and one fixed unbuffered block grid; no nested hyperparameter tuning",
                                "Zone centroids can be close across block borders; spatial independence not established",
                                "Validation target is zone-average density, not independent fine-pixel population truth",
                                "Building proportional coefficient is fitted using training zones only",
                                "Wall-clock timings depend on hardware and thread configuration"]}
    (output / "benchmark_metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    return results, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "case_study" / "RWA")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--spatial-grid", type=int, nargs=2, metavar=("COLUMNS", "ROWS"), default=(4, 4))
    parser.add_argument("--folds-from", type=Path, help="Replay exact group splits from a benchmark_metadata.json")
    options = parser.parse_args(argv)
    results, metadata = run_benchmark(options.data, options.output, options.trees,
                                      spatial_grid=tuple(options.spatial_grid), folds_from=options.folds_from)
    print(results.to_string(index=False))
    print(json.dumps({"n_zones": metadata["n_zones"], "n_folds": metadata["n_folds"],
                      "n_occupied_blocks": metadata["spatial_provenance"]["n_occupied_blocks"],
                      "feature_extraction_seconds": metadata["feature_extraction_seconds"],
                      "centroid_scan_seconds": metadata["centroid_scan_seconds"],
                      "total_seconds": metadata["total_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
