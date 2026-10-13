"""Conservative dasymetric population mapping, independent of Qt/QGIS."""
from pathlib import Path
import re

import numpy as np
import rasterio

from ..config.settings import Settings
from ..utils.logger import get_logger
from ..utils.raster import (raster_stat, get_windows, bounded_window_map, check_cancel,
                            validate_alignment, validate_census, valid_mask, protect_output)
from ..utils.runtime import atomic_output
from ..utils.workers import NormalizationWorker, DasymetricWorker

logger = get_logger()


class DasymetricMapper:
    """Allocate census totals proportionally to finite, nonnegative predictions.

    mastergrid and constrain are zone-ID rasters. Raw binary masks must first
    be transformed using remask_layer (water=1 excluded; constrain=0 excluded).
    Positive totals without positive weights fail; zero totals produce zeros.
    Every population artifact is read back and verified before publication.
    """
    AGE_COLUMN = re.compile(r"^[fm](?:_)?\d+(?:[_-]\d+|\+)?$", re.IGNORECASE)

    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = Path(getattr(settings, "output_dir", Path(settings.work_dir) / "output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._expectations = {}
        self._normalization_stats = {}
        self.diagnostics = {}
        self._input_paths = [settings.mastergrid, settings.constrain, settings.census.get("path"),
                             *getattr(settings, "covariate", {}).values(), getattr(settings, "mask", None),
                             getattr(settings, "agesex_data", None)]

    @property
    def _token(self):
        return getattr(self.settings, "cancellation_token", None)

    @staticmethod
    def _validate_census(census, kwargs, simple=False):
        id_column = kwargs.get("id_column", "id")
        pop_column = kwargs.get("pop_column", "pop")
        result = validate_census(census, id_column, pop_column)
        if simple:
            result = result[[id_column, pop_column]]
        return result, id_column, pop_column

    @staticmethod
    def _check_compatibility(src_profile, tgt_profile, labels):
        validate_alignment(src_profile, tgt_profile, labels)

    def _grid(self, constrained):
        if constrained and not self.settings.constrain:
            raise ValueError("Constrained mapping requires a constrained zone grid")
        return self.settings.constrain if constrained else self.settings.mastergrid

    def _windows(self, src):
        # Legacy by_block=False requests serial execution, never an unbounded read.
        return get_windows(src, self.settings.block_size)

    def _validate_inputs(self, prediction_path, mastergrid_path, constrain_path=None):
        """Check alignment and values without loading a complete raster."""
        check_cancel(self._token)
        self._input_paths.append(prediction_path)
        with rasterio.open(mastergrid_path) as mst, rasterio.open(prediction_path) as pred:
            validate_alignment(mst.profile, pred.profile, ("mastergrid", "prediction"))
            if constrain_path:
                with rasterio.open(constrain_path) as con:
                    validate_alignment(mst.profile, con.profile, ("mastergrid", "constrained zones"))
            for window in get_windows(mst, self.settings.block_size):
                check_cancel(self._token)
                weights = pred.read(1, window=window, masked=True)
                known = ~np.ma.getmaskarray(weights)
                data = np.ma.getdata(weights)
                if ((~np.isfinite(data) | (data < 0)) & known).any():
                    raise ValueError(f"Prediction contains nonfinite or negative weights in window {window}")
                if constrain_path:
                    with rasterio.open(constrain_path) as con:
                        zones = mst.read(1, window=window, masked=True)
                        constrained = con.read(1, window=window, masked=True)
                    eligible = valid_mask(constrained)
                    if (eligible & (~valid_mask(zones) | (np.asarray(zones) != np.asarray(constrained)))).any():
                        raise ValueError("Constrained raster must preserve mastergrid zone IDs and coverage")

    def _load_census(self, census_path, **kwargs):
        # Keep the same CSV/vector formats as feature extraction.
        from .feature_extraction import FeatureExtractor
        census = FeatureExtractor(self.settings).load_table(census_path)
        return self._validate_census(census, kwargs)

    @staticmethod
    def _validate_agesex(census, id_column):
        columns = [column for column in census if column != id_column and
                   isinstance(column, str) and DasymetricMapper.AGE_COLUMN.fullmatch(column)]
        if not columns:
            raise ValueError("No age-sex columns found; use f0, m0, f_0_4, m_5_9, f65+ style names")
        if len({column.casefold() for column in columns}) != len(columns):
            raise ValueError("Age-sex group names must be unique ignoring case")
        result = census.copy()
        for column in columns:
            result = validate_census(result, id_column, column)
        return result, id_column, columns

    def _load_agesex(self, census_path, id_column):
        from .feature_extraction import FeatureExtractor
        census = FeatureExtractor(self.settings).load_table(census_path)
        return self._validate_agesex(census, id_column)

    def _calculate_normalization(self, census, prediction_path, id_column, pop_column, constrained=False):
        census = validate_census(census, id_column, pop_column)
        key = (str(prediction_path), str(self._grid(constrained)))
        if key not in self._normalization_stats:
            self._normalization_stats[key] = raster_stat(prediction_path, self._grid(constrained), self.settings.by_block,
                                                       self.settings.max_workers, self.settings.block_size, self._token)
        stats = self._normalization_stats[key]
        # Standardized keys prevent accidental positional broadcasting and ID-column collisions.
        totals = census[[id_column, pop_column]].rename(columns={id_column: "id", pop_column: "_population"})
        unknown = stats.loc[~stats["id"].isin(totals["id"]), "id"].tolist()
        self.diagnostics["constrained" if constrained else "unconstrained"] = {
            "excluded_grid_zone_ids": unknown,
            "excluded_prediction_pixels": int(stats.loc[~stats["id"].isin(totals["id"]), "count"].sum()),
        }
        if unknown:
            logger.warning(f"Grid zones without census are excluded from population output: {unknown}")
        merged = totals.merge(stats[["id", "sum"]], on="id", how="left", validate="one_to_one")
        positive = merged["_population"].to_numpy(dtype=float) > 0
        weights = merged["sum"].to_numpy(dtype=float)
        unsupported = positive & (~np.isfinite(weights) | (weights <= 0))
        if unsupported.any():
            raise ValueError(f"Positive population has no positive eligible prediction support in zones: {merged.loc[unsupported, 'id'].tolist()}")
        factors = np.zeros(len(merged), dtype=np.float64)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            factors[positive] = merged.loc[positive, "_population"].to_numpy(dtype=float) / weights[positive]
        if not np.isfinite(factors).all():
            raise ValueError("Nonfinite normalization coefficients")
        merged["norm"] = factors
        return merged

    def _artifact_path(self, kind, constrained=False, suffix=None):
        if suffix is not None and not self.AGE_COLUMN.fullmatch(suffix):
            raise ValueError(f"Unsafe or unsupported age-sex suffix: {suffix}")
        if kind == "normalized":
            directory = self.output_dir / "agesex" / "additional_files" if suffix else self.output_dir
            name = "normalized_census" + ("_constrained" if constrained else "") + (f"_{suffix}" if suffix else "")
        else:
            directory = self.output_dir / "agesex" if suffix else self.output_dir
            name = (f"population_{suffix}" + ("_constrained" if constrained else "") if suffix
                    else "population_" + ("constrained" if constrained else "unconstrained"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.tif"
        protect_output(path, self._input_paths)
        return path

    @staticmethod
    def _output_profile(profile, dtype):
        profile = profile.copy()
        profile.update(driver="GTiff", count=1, dtype=dtype, nodata=-99, compress="deflate",
                       tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
        return profile

    def _create_normalized_raster(self, normalized_data, constrained=False, suffix=None):
        grid = self._grid(constrained)
        output_path = self._artifact_path("normalized", constrained, suffix)
        if normalized_data["id"].duplicated().any():
            raise ValueError("Duplicate normalization zone IDs")
        mapping = dict(zip(normalized_data["id"], normalized_data["norm"]))
        with rasterio.open(grid) as src:
            # Coefficients use float64 so tiny weights and large totals do not overflow float32.
            profile = self._output_profile(src.profile, "float64")
            windows = self._windows(src)
        def process(window):
            check_cancel(self._token)
            worker = NormalizationWorker(window, grid, mapping, profile)
            return worker.run()
        with atomic_output(output_path, self._token) as temporary:
            with rasterio.open(temporary, "w", **profile) as dst:
                for window, data in bounded_window_map(process, windows, self.settings.max_workers if self.settings.by_block else 1, self._token):
                    dst.write(data, window=window)
        self._expectations[str(output_path)] = normalized_data[["id", "_population"]].copy()
        return str(output_path)

    def _verify_population(self, output_path, expected, constrained=False):
        """Independent on-disk conservation check; no table algebra shortcut."""
        grid = self._grid(constrained)
        with rasterio.open(output_path) as out, rasterio.open(grid) as mst:
            validate_alignment(mst.profile, out.profile, ("mastergrid", "population"))
            for window in get_windows(out, self.settings.block_size):
                check_cancel(self._token)
                population = out.read(1, window=window, masked=True)
                known = ~np.ma.getmaskarray(population)
                values = np.ma.getdata(population)
                if (known & (~np.isfinite(values) | (values < 0))).any():
                    raise ValueError("Population raster contains invalid values")
                zones = mst.read(1, window=window, masked=True)
                if (known & ~valid_mask(zones)).any():
                    raise ValueError("Population written outside eligible zone coverage")
        actual = raster_stat(output_path, grid, True, self.settings.max_workers, self.settings.block_size, self._token)
        extra = actual.loc[~actual["id"].isin(expected["id"]), "id"].tolist()
        if extra:
            raise ValueError(f"Unexpected population zones: {extra}")
        comparison = expected.merge(actual[["id", "sum"]], on="id", how="left", validate="one_to_one")
        sums = comparison["sum"].fillna(0).to_numpy(dtype=float)
        totals = comparison["_population"].to_numpy(dtype=float)
        good = np.isclose(sums, totals, rtol=1e-6, atol=1e-5)
        if not good.all():
            rows = comparison.loc[~good, ["id", "_population", "sum"]].to_dict("records")
            raise ValueError(f"Population conservation failed by zone: {rows}")
        logger.info(f"Verified population conservation for {len(expected)} zones: total {float(sums.sum()):,.3f}")

    def _create_dasymetric_raster(self, prediction_path, norm_raster_path, constrained=False, suffix=None):
        output_path = self._artifact_path("population", constrained, suffix)
        protect_output(output_path, [prediction_path, norm_raster_path])
        if str(norm_raster_path) not in self._expectations:
            raise ValueError("Population output requires census expectations for on-disk verification")
        with rasterio.open(prediction_path) as src:
            profile = self._output_profile(src.profile, "float64")
            windows = self._windows(src)
        def process(window):
            check_cancel(self._token)
            worker = DasymetricWorker(window, {"prediction": prediction_path, "normalization": norm_raster_path}, profile)
            return worker.run()
        with atomic_output(output_path, self._token) as temporary:
            with rasterio.open(temporary, "w", **profile) as dst:
                for window, data in bounded_window_map(process, windows, self.settings.max_workers if self.settings.by_block else 1, self._token):
                    dst.write(data, window=window)
            self._verify_population(temporary, self._expectations[str(norm_raster_path)], constrained)
        return output_path

    def map(self, prediction_path):
        self._normalization_stats.clear()
        self._validate_inputs(prediction_path, self.settings.mastergrid, self.settings.constrain)
        census, id_column, pop_column = self._load_census(self.settings.census["path"], **self.settings.census)
        # Preflight both variants before producing any result.
        modes = [False, True] if self.settings.constrain else [False]
        normalized = {mode: self._calculate_normalization(census, prediction_path, id_column, pop_column, mode) for mode in modes}
        paths = {}
        for mode, table in normalized.items():
            factors = self._create_normalized_raster(table, mode)
            paths["constrained" if mode else "unconstrained"] = self._create_dasymetric_raster(prediction_path, factors, mode)
        return paths

    def map_agesex(self, prediction_path, agesex_path):
        self._normalization_stats.clear()
        self._input_paths.append(agesex_path)
        self._validate_inputs(prediction_path, self.settings.mastergrid, self.settings.constrain)
        census, id_column, columns = self._load_agesex(agesex_path, self.settings.census["id_column"])
        main, main_id, main_pop = self._load_census(self.settings.census["path"], **self.settings.census)
        totals = main[[main_id, main_pop]].rename(columns={main_id: "id", main_pop: "census_population"})
        groups = census[[id_column]].rename(columns={id_column: "id"}).copy()
        groups["age_sex_population"] = census[columns].sum(axis=1).to_numpy(dtype=float)
        if not np.isfinite(groups["age_sex_population"]).all():
            raise ValueError("Age-sex population totals exceed the numeric range")
        comparison = totals.merge(groups, on="id", how="outer", validate="one_to_one")
        common = comparison["census_population"].notna() & comparison["age_sex_population"].notna()
        comparison["difference"] = comparison["age_sex_population"] - comparison["census_population"]
        mismatch = common & ~np.isclose(comparison["age_sex_population"], comparison["census_population"], rtol=1e-6, atol=1e-5)
        differences = comparison.loc[mismatch, ["id", "census_population", "age_sex_population", "difference"]]
        missing_groups = comparison.loc[comparison["age_sex_population"].isna(), "id"].tolist()
        missing_main = comparison.loc[comparison["census_population"].isna(), "id"].tolist()
        self.diagnostics["age_sex_totals"] = {
            "mismatch_count": len(differences), "mismatched_zone_ids": differences["id"].tolist(),
            "differences": differences.head(100).to_dict("records"),
            "differences_truncated": len(differences) > 100,
            "missing_age_sex_zone_ids": missing_groups, "missing_census_zone_ids": missing_main,
            "policy": "Groups are allocated independently; totals are not forced to match census",
        }
        if len(differences) or missing_groups or missing_main:
            logger.warning(f"Age-sex group totals differ from census in {len(differences)} zones; "
                           f"{len(missing_groups)} zones lack groups and {len(missing_main)} lack main census. "
                           "Groups are allocated independently; review the age-sex totals diagnostic.")
        diagnostic_path = self.output_dir / "agesex" / "age_sex_totals.csv"
        protect_output(diagnostic_path, self._input_paths)
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(diagnostic_path, self._token) as temporary:
            comparison.to_csv(temporary, index=False)
        self.diagnostics["age_sex_totals"]["table"] = str(diagnostic_path.relative_to(self.output_dir))
        # Validate all groups/support first, so a late invalid group cannot leave an apparently complete result set.
        modes = [False, True] if self.settings.constrain else [False]
        tables = {(mode, column): self._calculate_normalization(census, prediction_path, id_column, column, mode)
                  for mode in modes for column in columns}
        paths = {}
        for (mode, column), table in tables.items():
            factors = self._create_normalized_raster(table, mode, column)
            paths[("constrained" if mode else "unconstrained") + "_" + column] = self._create_dasymetric_raster(prediction_path, factors, mode, column)
        return paths
