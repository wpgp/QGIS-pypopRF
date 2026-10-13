"""Deterministic RF training, honest zone validation and bounded raster inference."""
from contextlib import ExitStack
import json
import platform
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, KFold, train_test_split
from sklearn.preprocessing import RobustScaler
from sklearn.utils.validation import check_is_fitted
from rasterio.windows import Window

from ..config.settings import Settings
from ..utils.logger import get_logger
from ..utils.runtime import atomic_output

logger = get_logger()
BUNDLE_VERSION = 2


class Model:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = Path(settings.output_dir)
        self.model = self.scaler = None
        self.feature_names = self.selected_features = None
        self.feature_importances = None
        self.target_mean = None
        self.target_transform = None
        self.cv_metrics = None
        self.cv_predictions = None
        self.training_grid = None
        self.cv_zone_geometry = None

    def _spatial_groups(self, zone_ids):
        """Group census-zone centroids in a reproducible raster-footprint grid.

        This is unbuffered centroid blocking, not a claim of independence:
        adjacent blocks share boundaries and a zone may span multiple blocks.
        Centroids use valid mastergrid pixel centres; water exclusion therefore
        affects them when the pipeline supplies a remasked mastergrid.
        """
        numeric_ids = pd.to_numeric(pd.Series(zone_ids), errors="raise").to_numpy(dtype=float)
        requested = set(numeric_ids)
        totals = {zone: [0.0, 0.0, 0] for zone in requested}
        columns, rows = getattr(self.settings, "spatial_grid", (4, 4))
        with rasterio.open(self.settings.mastergrid) as master:
            width, height = master.width, master.height
            transform = master.transform
            provenance = {
                "source": "mastergrid_valid_pixel_centroids",
                "crs": master.crs.to_wkt(), "affine": list(transform)[:6],
                "raster_shape": [height, width], "subdivisions": [columns, rows],
                "block_width_pixels": width / columns,
                "block_height_pixels": height / rows,
                "block_width_native_units": float(width / columns * np.hypot(transform.a, transform.d)),
                "block_height_native_units": float(height / rows * np.hypot(transform.b, transform.e)),
                "native_unit": "angular CRS units (degrees for EPSG:4326)" if master.crs.is_geographic
                               else "projected CRS units; see CRS WKT",
                "assignment": "floor(column_center / block_width), floor(row_center / block_height)",
                "centroid_method": "arithmetic mean of eligible pixel centre coordinates",
                "buffer_pixels": 0,
                "limitations": ["No spatial separation buffer between adjacent blocks",
                                "Centroid assignment does not prevent large zones crossing block boundaries",
                                "Block scale must be justified against dependence and intended transfer distance",
                                "Zone-density validation does not measure independent fine-pixel population accuracy"],
            }
            block_width, block_height = self.settings.block_size
            for top in range(0, height, block_height):
                for left in range(0, width, block_width):
                    self._check_cancelled()
                    window = Window(left, top, min(block_width, width - left), min(block_height, height - top))
                    values = master.read(1, window=window, masked=True)
                    valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
                    pixels = values.data[valid]
                    if np.any(pixels != np.floor(pixels)):
                        raise ValueError("Spatial validation mastergrid zone IDs must be integers")
                    if not len(pixels):
                        continue
                    local_rows, local_columns = np.nonzero(valid)
                    unique, inverse = np.unique(pixels, return_inverse=True)
                    counts = np.bincount(inverse)
                    row_sums = np.bincount(inverse, weights=local_rows + top + 0.5)
                    column_sums = np.bincount(inverse, weights=local_columns + left + 0.5)
                    for index, zone in enumerate(unique):
                        if zone in requested:
                            total = totals[zone]
                            total[0] += row_sums[index]
                            total[1] += column_sums[index]
                            total[2] += int(counts[index])
        records = []
        missing = []
        for zone in numeric_ids:
            row_sum, column_sum, count = totals[zone]
            if not count:
                missing.append(int(zone))
                records.append({"zone_id": zone, "eligible_pixel_count": 0, "group": None})
                continue
            row, column = row_sum / count, column_sum / count
            block_column = min(columns - 1, int(np.floor(column * columns / width)))
            block_row = min(rows - 1, int(np.floor(row * rows / height)))
            x = transform.a * column + transform.b * row + transform.c
            y = transform.d * column + transform.e * row + transform.f
            records.append({"zone_id": zone, "eligible_pixel_count": count,
                            "centroid_row": row, "centroid_column": column,
                            "centroid_x": float(x), "centroid_y": float(y),
                            "block_row": block_row, "block_column": block_column,
                            "group": f"row{block_row}_col{block_column}"})
        geometry = pd.DataFrame(records)
        provenance["missing_zone_ids"] = missing
        provenance["n_occupied_blocks"] = int(geometry["group"].nunique())
        groups = None if missing else geometry["group"].to_numpy()
        return groups, provenance, geometry

    def _grid_signature(self):
        with rasterio.open(self.settings.mastergrid) as master:
            return {"crs": master.crs.to_wkt(),
                    "linear_affine": [master.transform.a, master.transform.b,
                                      master.transform.d, master.transform.e],
                    "units": "population_per_supported_pixel"}

    def _validate_grid_contract(self, signature):
        current = self._grid_signature()
        try:
            saved_crs = rasterio.crs.CRS.from_wkt(signature["crs"])
            affine = np.asarray(signature["linear_affine"], dtype=float)
            pixel_size = max(np.hypot(current["linear_affine"][0], current["linear_affine"][2]),
                             np.hypot(current["linear_affine"][1], current["linear_affine"][3]))
            compatible = (saved_crs == rasterio.crs.CRS.from_wkt(current["crs"])
                          and signature["units"] == current["units"]
                          and affine.shape == (4,) and np.isfinite(affine).all()
                          and np.allclose(affine, current["linear_affine"], rtol=0,
                                          atol=max(pixel_size * 1e-7, 1e-12)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid saved training-grid contract") from exc
        if not compatible:
            raise ValueError("Training grid CRS or pixel geometry differs; retrain for this grid")

    def _check_cancelled(self):
        token = getattr(self.settings, "cancellation_token", None)
        if token is not None:
            token.check()

    def _output_path(self, filename):
        path = self.output_dir / filename
        # Settings may legitimately be copied/rebound by an adapter. Protect
        # every publication as well as initial preflight against input aliases.
        inputs = [self.settings.mastergrid, self.settings.census.get("path"),
                  getattr(self.settings, "mask", None), getattr(self.settings, "constrain", None),
                  getattr(self.settings, "agesex_data", None), *self.settings.covariate.values()]
        if any(path.resolve() == Path(source).resolve() for source in inputs if source):
            raise ValueError(f"Model output would overwrite an input: {path}")
        return path

    @property
    def seed(self):
        return getattr(self.settings, "random_seed", 42)

    def _forest(self):
        return RandomForestRegressor(
            n_estimators=min(25, getattr(self.settings, "n_estimators", 500)),
            warm_start=True, random_state=self.seed,
            n_jobs=min(getattr(self.settings, "max_workers", 1), os.cpu_count() or 1),
        )

    def _fit_forest(self, X, y):
        # Batches offer cooperative cancellation between tree builds without
        # restarting a fit; fixed seed yields the same forest as a single fit.
        forest = self._forest()
        total = getattr(self.settings, "n_estimators", 500)
        for count in range(forest.n_estimators, total + 25, 25):
            self._check_cancelled()
            forest.set_params(n_estimators=min(count, total))
            forest.fit(X, y)
            if count >= total:
                break
        self._check_cancelled()
        return forest

    def _transform(self, density):
        return np.log1p(density) if self.target_transform == "log1p" else density

    def _inverse(self, values):
        with np.errstate(over="raise", invalid="raise"):
            result = np.expm1(values) if self.target_transform == "log1p" else np.asarray(values)
        if not np.isfinite(result).all():
            raise ValueError("Model produced nonfinite density predictions")
        return np.maximum(result, 0)

    def _select(self, X, y):
        names = X.columns.to_numpy()
        zeros = pd.DataFrame({"feature": names, "importance": 0.0, "std": 0.0})
        # An inner holdout only guides selection; the outer fold remains unseen.
        # Very small or constant-target sets retain all predictors explicitly.
        if len(y) < 8 or np.ptp(y) <= np.finfo(float).eps:
            return names, zeros
        train, validation = train_test_split(np.arange(len(y)), test_size=0.25,
                                             random_state=self.seed)
        scaler = RobustScaler().fit(X.iloc[train])
        forest = self._fit_forest(scaler.transform(X.iloc[train]), y[train])
        self._check_cancelled()
        result = permutation_importance(
            forest, scaler.transform(X.iloc[validation]), y[validation],
            n_repeats=5, n_jobs=1, random_state=self.seed,
            scoring="neg_root_mean_squared_error",
        )
        self._check_cancelled()
        scale = max(float(np.std(y[train])), float(np.mean(np.abs(y[train]))), 1e-12)
        importance = result.importances_mean / scale
        frame = pd.DataFrame({"feature": names, "importance": importance,
                              "std": result.importances_std / scale})
        selected = names[importance > self.settings.selection_threshold]
        if len(selected) == 0:
            # No credible ranking (e.g. all sparse/zero predictors): keep all.
            # If useful predictors exist but threshold excludes them, retain best.
            selected = names[[int(np.argmax(importance))]] if np.max(importance) > 0 else names
        return selected, frame.sort_values("importance", ascending=False)

    def _fit_procedure(self, X, density):
        target = self._transform(density)
        selected, importances = self._select(X, target)
        scaler = RobustScaler().fit(X[selected])
        forest = self._fit_forest(scaler.transform(X[selected]), target)
        return forest, scaler, selected, importances

    def _prepare_data(self, data, groups=None):
        if not isinstance(data, pd.DataFrame) or data.empty:
            raise ValueError("Training data must be a nonempty DataFrame")
        if data.columns.duplicated().any():
            raise ValueError("Training data has duplicate column names")
        id_column = self.settings.census["id_column"]
        pop_column = self.settings.census["pop_column"]
        names = [f"{name}_avg" for name in self.settings.covariate]
        missing = set([id_column, pop_column, "dens", *names]) - set(data.columns)
        if missing:
            raise ValueError(f"Training data missing required columns: {sorted(missing)}")
        Settings.validate_census_frame(data, id_column, [pop_column, "dens"], "Training data")
        X = data[names].apply(pd.to_numeric, errors="raise")
        if np.iscomplexobj(X.to_numpy()):
            raise ValueError("Training features must be real numbers")
        if not np.isfinite(X.to_numpy(dtype=float)).all():
            raise ValueError("Training features must be finite; missing-zone policy must be explicit")
        density = pd.to_numeric(data["dens"], errors="raise").to_numpy(dtype=float)
        column = getattr(self.settings, "cv_group_column", None)
        if groups is None and column is not None:
            if column not in data:
                raise ValueError(f"CV group column missing: {column}")
            groups = data[column].to_numpy()
        if groups is not None:
            groups = np.asarray(groups)
            if groups.ndim != 1 or len(groups) != len(data) or pd.isna(groups).any():
                raise ValueError("CV groups must provide one nonmissing group per training zone")
        self.feature_names = np.asarray(names)
        return X, density, groups

    def train(self, data, model_path=None, scaler_path=None, log_scale=None,
              save_model=True, groups=None):
        self._check_cancelled()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log_scale = self.settings.log_scale if log_scale is None else log_scale
        if not isinstance(log_scale, bool):
            raise ValueError("log_scale must be a boolean")
        if model_path is not None:
            self.load_model(model_path, scaler_path)
            if (self.target_transform == "log1p") != log_scale:
                raise ValueError("Requested target transform differs from saved model")
            return
        if scaler_path is not None:
            raise ValueError("A standalone scaler cannot establish the model schema; retrain or load a bundle")
        # A failed retraining attempt must not leave a fitted forest interpreted
        # with the new attempt's transform or feature names.
        self.model = self.scaler = None
        self.selected_features = None
        supplied_groups = groups is not None
        X, density, groups = self._prepare_data(data, groups)
        self.target_transform = "log1p" if log_scale else "identity"
        self.training_grid = self._grid_signature()
        self.target_mean = float(np.mean(density))
        # Validate the entire train/select/scale procedure with fresh fits per fold.
        self.cv_metrics = self._calculate_cv_scores(X, density, groups=groups,
                                                   zone_ids=data[self.settings.census["id_column"]].to_numpy(),
                                                   group_source="train_arguments" if supplied_groups else "census_column")
        self.model, self.scaler, self.selected_features, self.feature_importances = self._fit_procedure(X, density)
        with atomic_output(self._output_path("feature_importance.csv"),
                           getattr(self.settings, "cancellation_token", None)) as path:
            self.feature_importances.to_csv(path, index=False)
        if save_model:
            self._save_model()
        logger.info("Model trained; validation metrics describe census zones, not fine-scale pixel accuracy")

    def _calculate_cv_scores(self, X, density, cv=None, groups=None, zone_ids=None,
                             group_source="train_arguments"):
        cv = getattr(self.settings, "cv_folds", 5) if cv is None else cv
        n = len(density)
        strategy = getattr(self.settings, "cv_strategy", "spatial")
        geometry = None
        unavailable_reason = None
        if groups is not None:
            scheme, spatial = "group", False
            provenance = {"source": group_source, "column": getattr(self.settings, "cv_group_column", None),
                          "limitations": ["User-supplied groups do not by themselves establish spatial independence",
                                          "Zone-density validation does not measure fine-pixel population accuracy"]}
        elif strategy == "spatial":
            scheme, spatial = "spatial_blocks", True
            if zone_ids is None:
                raise ValueError("Spatial validation requires census zone IDs")
            groups, provenance, geometry = self._spatial_groups(zone_ids)
            self.cv_zone_geometry = geometry
            with atomic_output(self._output_path("cv_zone_geometry.csv"),
                               getattr(self.settings, "cancellation_token", None)) as path:
                geometry.to_csv(path, index=False)
            if provenance["missing_zone_ids"]:
                unavailable_reason = "Training zones have no eligible mastergrid centroid; spatial CV unavailable"
            elif provenance["n_occupied_blocks"] < 2:
                unavailable_reason = "At least two occupied spatial blocks are required; adjust spatial_grid or provide justified groups"
        elif strategy == "groups":
            raise ValueError("cv_strategy='groups' requires train(groups=...) or cv_group_column")
        else:
            scheme, spatial = "shuffled_zone", False
            provenance = {"source": "seeded_shuffled_census_zones", "random_seed": self.seed,
                          "limitations": ["Diagnostic split ignores geographic dependence; error can be optimistic",
                                          "Zone-density validation does not measure fine-pixel population accuracy"]}
        if geometry is None:
            self.cv_zone_geometry = None
            with atomic_output(self._output_path("cv_zone_geometry.csv"),
                               getattr(self.settings, "cancellation_token", None)) as path:
                pd.DataFrame(columns=["zone_id", "eligible_pixel_count", "centroid_row", "centroid_column",
                                      "centroid_x", "centroid_y", "block_row", "block_column", "group"]).to_csv(path, index=False)
        group_count = len(pd.unique(groups)) if groups is not None else n
        common = {"n_zones": n, "scale": "density", "scheme": scheme,
                  "spatial_validation": spatial and n >= 2 and group_count >= 2 and unavailable_reason is None,
                  "spatial_blocking_requested": spatial,
                  "grouping_provided": groups is not None,
                  "random_seed": self.seed, "target_transform": self.target_transform,
                  "target_units": "population_per_eligible_mastergrid_pixel",
                  "provenance": provenance, "n_groups": group_count if groups is not None else None}
        if n < 2 or group_count < 2 or unavailable_reason is not None:
            metrics = dict(common, status="unavailable", reason=unavailable_reason or
                           "At least two census zones and two held-out groups are required")
            self.cv_predictions = pd.DataFrame(columns=["zone_id", "density", "prediction", "fold"])
            with atomic_output(self._output_path("cv_predictions.csv"),
                               getattr(self.settings, "cancellation_token", None)) as path:
                self.cv_predictions.to_csv(path, index=False)
        else:
            folds = min(cv, group_count)
            splitter = GroupKFold(n_splits=folds) if groups is not None else KFold(
                n_splits=folds, shuffle=True, random_state=self.seed)
            predicted = np.empty(n, dtype=float)
            fold_ids = np.empty(n, dtype=int)
            for fold, (train, test) in enumerate(splitter.split(X, density, groups)):
                self._check_cancelled()
                forest, scaler, selected, _ = self._fit_procedure(X.iloc[train], density[train])
                predicted[test] = self._inverse(forest.predict(scaler.transform(X.iloc[test][selected])))
                fold_ids[test] = fold
            rmse = float(np.sqrt(mean_squared_error(density, predicted)))
            mae = float(mean_absolute_error(density, predicted))
            norm = float(np.mean(density))
            metrics = {**common, "status": "complete", "n_folds": folds,
                       "rmse": rmse, "mae": mae,
                       "r2": float(r2_score(density, predicted)) if np.ptp(density) > 0 else None,
                       "normalized_rmse": rmse / norm if norm > 0 else None,
                       "normalized_mae": mae / norm if norm > 0 else None}
            self.cv_predictions = pd.DataFrame({"zone_id": np.arange(n) if zone_ids is None else zone_ids,
                                                "density": density, "prediction": predicted, "fold": fold_ids})
            if groups is not None:
                self.cv_predictions["group"] = groups
            if geometry is not None:
                self.cv_predictions = self.cv_predictions.merge(
                    geometry.drop(columns="group"), on="zone_id", how="left", validate="one_to_one")
            with atomic_output(self._output_path("cv_predictions.csv"),
                               getattr(self.settings, "cancellation_token", None)) as path:
                self.cv_predictions.to_csv(path, index=False)
        with atomic_output(self._output_path("cv_metrics.json"),
                           getattr(self.settings, "cancellation_token", None)) as path:
            path.write_text(json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8")
        return metrics

    @staticmethod
    def _versions():
        return {"python": platform.python_version(), "sklearn": sklearn.__version__,
                "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__}

    def _save_model(self):
        bundle = {"bundle_version": BUNDLE_VERSION, "versions": self._versions(),
                  "model": self.model, "scaler": self.scaler,
                  "feature_names": self.feature_names.tolist(),
                  "selected_features": self.selected_features.tolist(),
                  "target_transform": self.target_transform, "target_mean": self.target_mean,
                  "random_seed": self.seed, "cv_metrics": self.cv_metrics,
                  "feature_importances": self.feature_importances,
                  "training_grid": self.training_grid,
                  "missing_policy": "selected_covariates_intersection"}
        with atomic_output(self._output_path("model_bundle.pkl.gz"),
                           getattr(self.settings, "cancellation_token", None)) as path:
            joblib.dump(bundle, path, compress=3)

    def load_model(self, model_path, scaler_path=None):
        """Load a locally trusted bundle. Joblib files must never be untrusted input.

        Legacy naked model/scaler pairs lack transform/schema metadata and require
        retraining. Pickled sklearn models are only supported in matching versions.
        """
        self._check_cancelled()
        if scaler_path is not None:
            raise ValueError("Legacy model/scaler pairs have no target contract; retrain to create a bundle")
        bundle = joblib.load(model_path)
        required = {"bundle_version", "versions", "model", "scaler", "feature_names",
                    "selected_features", "target_transform", "target_mean", "missing_policy", "training_grid"}
        if not isinstance(bundle, dict) or not required.issubset(bundle) or bundle["bundle_version"] != BUNDLE_VERSION:
            raise ValueError("Unsupported model bundle; retraining is required")
        versions = bundle["versions"]
        current = self._versions()
        if (versions.get("sklearn") != current["sklearn"]
                or str(versions.get("numpy", "")).split(".")[0] != current["numpy"].split(".")[0]
                or str(versions.get("python", "")).split(".")[:2] != current["python"].split(".")[:2]):
            raise ValueError("Model environment differs; retrain in the current environment")
        names, selected = bundle["feature_names"], bundle["selected_features"]
        expected = [f"{name}_avg" for name in self.settings.covariate]
        if (not isinstance(names, list) or not isinstance(selected, list) or not selected
                or len(names) != len(set(names)) or len(selected) != len(set(selected))
                or set(names) != set(expected) or not set(selected).issubset(names)):
            raise ValueError("Saved feature schema differs from configured covariates")
        if bundle["target_transform"] not in {"log1p", "identity"} or bundle["missing_policy"] != "selected_covariates_intersection":
            raise ValueError("Unsupported target or missing-data contract")
        self._validate_grid_contract(bundle["training_grid"])
        model, scaler = bundle["model"], bundle["scaler"]
        if (not isinstance(model, RandomForestRegressor) or not isinstance(scaler, RobustScaler)
                or getattr(model, "n_features_in_", None) != len(selected)
                or getattr(scaler, "n_features_in_", None) != len(selected)
                or list(getattr(scaler, "feature_names_in_", [])) != selected):
            raise ValueError("Corrupt model/scaler feature schema")
        try:
            check_is_fitted(model, "estimators_")
            check_is_fitted(scaler, ["center_", "scale_"])
        except Exception as exc:
            raise ValueError("Model bundle contains an unfitted estimator") from exc
        if (not np.isfinite(scaler.center_).all() or not np.isfinite(scaler.scale_).all()
                or np.any(scaler.scale_ <= 0)
                or not isinstance(bundle["target_mean"], (float, int))
                or not np.isfinite(bundle["target_mean"]) or bundle["target_mean"] < 0):
            raise ValueError("Corrupt model bundle numeric metadata")
        self.model, self.scaler = model, scaler
        self.feature_names, self.selected_features = np.asarray(names), np.asarray(selected)
        self.target_transform, self.target_mean = bundle["target_transform"], bundle["target_mean"]
        self.training_grid = bundle["training_grid"]
        self.cv_metrics = bundle.get("cv_metrics")
        self.feature_importances = bundle.get("feature_importances")
        self._check_cancelled()

    def predict(self, log_scale=None):
        if self.model is None or self.scaler is None or self.selected_features is None:
            raise RuntimeError("Model not trained. Call train() or load_model() first")
        if log_scale is not None and log_scale != (self.target_transform == "log1p"):
            raise ValueError("Prediction target transform must match the fitted model")
        self._check_cancelled()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._validate_grid_contract(self.training_grid)
        outfile = self._output_path("prediction.tif")
        token = getattr(self.settings, "cancellation_token", None)
        with ExitStack() as stack:
            master = stack.enter_context(rasterio.open(self.settings.mastergrid))
            sources = {f"{name}_avg": stack.enter_context(rasterio.open(path))
                       for name, path in self.settings.covariate.items()
                       if f"{name}_avg" in self.selected_features}
            for name, source in sources.items():
                Settings._validate_alignment(source, master, name)
            profile = master.profile.copy()
            profile.update(driver="GTiff", count=1, dtype="float32", nodata=np.nan,
                           tiled=True, blockxsize=self.settings.block_size[0],
                           blockysize=self.settings.block_size[1], compress="deflate", BIGTIFF="IF_SAFER")
            with atomic_output(outfile, token) as path:
                with rasterio.open(path, "w", **profile) as destination:
                    destination.update_tags(target_transform=self.target_transform,
                                            units="population_per_supported_pixel",
                                            missing_policy="selected_covariates_intersection")
                    # Even by_block=False is tiled: memory is bounded independently
                    # of dataset size, with identical pixel-level semantics.
                    for _, window in destination.block_windows():
                        self._check_cancelled()
                        zone = master.read(1, window=window, masked=True)
                        valid = ~np.ma.getmaskarray(zone) & np.isfinite(zone.data)
                        arrays = {}
                        for name, source in sources.items():
                            values = source.read(1, window=window, masked=True)
                            valid &= ~np.ma.getmaskarray(values) & np.isfinite(values.data)
                            if name in self.selected_features:
                                arrays[name] = values.data
                        result = np.full(valid.shape, np.nan, dtype=np.float32)
                        if np.any(valid):
                            features = pd.DataFrame({name: arrays[name][valid] for name in self.selected_features})
                            predictions = self._inverse(self.model.predict(self.scaler.transform(features)))
                            if np.any(predictions > np.finfo(np.float32).max):
                                raise ValueError("Density predictions exceed float32 output range")
                            result[valid] = predictions.astype(np.float32)
                        destination.write(result, indexes=1, window=window)
        return str(outfile)
