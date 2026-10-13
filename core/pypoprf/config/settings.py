"""Validated, headless project settings. Validation never modifies input files."""
import inspect
import csv
from copy import deepcopy
import numbers
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import rasterio
import yaml

from ..utils.logger import get_logger

logger = get_logger()


class Settings:
    def __init__(
        self, work_dir: str = ".", data_dir: str = "data",
        mastergrid: Optional[str] = None, mask: Optional[str] = None,
        constrain: Optional[str] = None, covariates: Optional[Dict[str, str]] = None,
        census_data: Optional[str] = None, census_pop_column: Optional[str] = None,
        census_id_column: Optional[str] = None, agesex_data: Optional[str] = None,
        output_dir: Optional[str] = None, by_block: bool = True,
        block_size: Tuple[int, int] = (512, 512), max_workers: int = 4,
        show_progress: bool = True, log_scale: bool = True,
        selection_threshold: float = 0.01, logging: Optional[Dict] = None,
        random_seed: int = 42, cv_folds: int = 5,
        cv_group_column: Optional[str] = None, n_estimators: int = 500,
        cv_strategy: str = "spatial", spatial_grid: Tuple[int, int] = (4, 4),
        cancellation_token=None,
    ):
        self.work_dir = Path(work_dir).resolve()
        self.data_dir = (self.work_dir / data_dir).resolve()
        self.output_dir = (self.work_dir / (output_dir or "output")).resolve()
        self.mastergrid = self._resolve_path(mastergrid)
        self.mask = self._resolve_path(mask)
        self.constrain = self._resolve_path(constrain)
        if not isinstance(covariates, dict) or not covariates:
            raise ValueError("At least one named covariate is required")
        if any(not isinstance(k, str) or not k.strip() for k in covariates):
            raise ValueError("Covariate names must be nonempty strings")
        self.covariate = {k: self._resolve_path(v) for k, v in covariates.items()}
        self.census = {"path": self._resolve_path(census_data),
                       "pop_column": census_pop_column, "id_column": census_id_column}
        self.agesex_data = self._resolve_path(agesex_data)
        self.by_block = by_block
        self.block_size = block_size
        self.max_workers = max_workers
        self.show_progress = show_progress
        self.log_scale = log_scale
        self.selection_threshold = selection_threshold
        self.random_seed = random_seed
        self.cv_folds = cv_folds
        self.cv_group_column = cv_group_column
        self.n_estimators = n_estimators
        self.cv_strategy = cv_strategy
        self.spatial_grid = spatial_grid
        self.cancellation_token = cancellation_token
        self.logging = {"level": "INFO", "file": "pypoprf.log"}
        if logging is not None:
            if not isinstance(logging, dict):
                raise ValueError("logging must be a mapping")
            if set(logging) - {"level", "file"}:
                raise ValueError("Unknown logging settings")
            self.logging.update(logging)
        self._validate_parameters()
        self._validate_settings()
        logger.set_level(self.logging["level"])

    def _check_cancelled(self):
        if self.cancellation_token is not None:
            self.cancellation_token.check()

    def _resolve_path(self, path):
        if path is None or path == "":
            return None
        if not isinstance(path, (str, Path)):
            raise ValueError("Input paths must be strings or Path objects")
        supplied = self.data_dir / path
        # Resolving a file alias changes the GDAL namespace: alias.tif.msk and
        # alias.tif.aux.xml need not describe the canonical target.tif. Parent
        # directory aliases are safe to resolve; real hardlinks retain their
        # distinct filename and therefore their own mask/metadata namespace.
        if supplied.is_symlink():
            raise ValueError("File-symlink sources may have different GDAL sidecars; "
                             "select the canonical file or export an explicit self-contained copy")
        return str(supplied.resolve())

    def _validate_parameters(self):
        for name in ("by_block", "show_progress", "log_scale"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        for name, minimum in (("max_workers", 1), ("n_estimators", 1),
                              ("cv_folds", 2), ("random_seed", 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if self.random_seed > 2 ** 32 - 1:
            raise ValueError("random_seed must be <= 2**32 - 1")
        if (not isinstance(self.block_size, (tuple, list)) or len(self.block_size) != 2
                or any(isinstance(n, bool) or not isinstance(n, numbers.Integral)
                       or n < 16 or n % 16 for n in self.block_size)):
            raise ValueError("block_size must contain two positive multiples of 16")
        self.block_size = tuple(self.block_size)
        if (isinstance(self.selection_threshold, bool)
                or not isinstance(self.selection_threshold, numbers.Real)
                or not np.isfinite(self.selection_threshold) or self.selection_threshold < 0):
            raise ValueError("selection_threshold must be finite and nonnegative")
        if self.cv_group_column is not None and (not isinstance(self.cv_group_column, str)
                                                 or not self.cv_group_column.strip()):
            raise ValueError("cv_group_column must be a nonempty column name")
        if not isinstance(self.cv_strategy, str) or self.cv_strategy not in {"spatial", "groups", "shuffled_zone"}:
            raise ValueError("cv_strategy must be spatial, groups or shuffled_zone")
        if (not isinstance(self.spatial_grid, (list, tuple)) or len(self.spatial_grid) != 2
                or any(isinstance(n, bool) or not isinstance(n, numbers.Integral)
                       or n < 1 or n > 1024 for n in self.spatial_grid)):
            raise ValueError("spatial_grid must contain two integers between 1 and 1024 (columns, rows)")
        self.spatial_grid = tuple(self.spatial_grid)
        level = self.logging["level"]
        if not isinstance(level, str) or level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Unknown logging level")
        logfile = self.logging["file"]
        if logfile:
            if not isinstance(logfile, str) or Path(logfile).name != logfile or logfile in {".", ".."}:
                raise ValueError("logging.file must be a filename within output_dir")
            if not logfile.lower().endswith(".log"):
                raise ValueError("logging.file must have a .log extension")
            device = logfile.split(".", 1)[0].upper()
            reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                        *[f"LPT{i}" for i in range(1, 10)]}
            if (logfile != logfile.strip() or any(c in logfile for c in '<>:"/\\|?*')
                    or any(ord(c) < 32 for c in logfile) or device in reserved):
                raise ValueError("logging.file must be a portable .log filename")
            self.logging["file"] = str(self.output_dir / logfile)
        elif logfile is not None and logfile != "":
            raise ValueError("logging.file must be a filename or null")

    @staticmethod
    def _require_file(path, role):
        if not path:
            raise ValueError(f"{role} path is required")
        if not Path(path).is_file():
            raise FileNotFoundError(f"{role} file not found: {path}")

    @staticmethod
    def _validate_alignment(source, reference, role):
        if source.count != 1:
            raise ValueError(f"{role} must have exactly one raster band")
        if source.crs is None:
            raise ValueError(f"{role} has no CRS")
        if source.crs != reference.crs or source.shape != reference.shape:
            raise ValueError(f"{role} grid dimensions or CRS differ from mastergrid")
        pixel_size = max(np.hypot(reference.transform.a, reference.transform.d),
                         np.hypot(reference.transform.b, reference.transform.e))
        if not np.isfinite(pixel_size) or pixel_size <= 0:
            raise ValueError("Mastergrid has an invalid affine transform")
        coefficients = np.asarray(tuple(reference.transform)[:6], dtype=float)
        determinant = reference.transform.a * reference.transform.e - reference.transform.b * reference.transform.d
        if not np.isfinite(coefficients).all() or not np.isfinite(determinant) or determinant == 0:
            raise ValueError("Mastergrid affine transform is nonfinite or singular")
        if not np.allclose(tuple(source.transform)[:6], tuple(reference.transform)[:6],
                           rtol=0, atol=max(pixel_size * 1e-7, 1e-12)):
            raise ValueError(f"{role} affine transform differs from mastergrid")

    @staticmethod
    def validate_census_frame(frame, id_column, population_columns, role="Census"):
        required = [id_column, *population_columns]
        missing = set(required) - set(frame.columns)
        if missing:
            raise ValueError(f"{role} missing required columns: {sorted(missing)}")
        if frame.empty:
            raise ValueError(f"{role} contains no rows")
        if len(frame.columns) != len(set(frame.columns)):
            raise ValueError(f"{role} contains duplicate column names")
        if any(frame[column].map(lambda value: isinstance(value, (bool, np.bool_))).any()
               for column in required):
            raise ValueError(f"{role} IDs and population values cannot be booleans")
        numeric_ids = pd.to_numeric(frame[id_column], errors="raise")
        if np.iscomplexobj(numeric_ids.to_numpy()):
            raise ValueError(f"{role} IDs must be real numbers")
        if (numeric_ids.abs() > 2 ** 53).any():
            raise ValueError(f"{role} IDs must be finite integers representable exactly")
        ids = numeric_ids.to_numpy(dtype=float)
        if not np.isfinite(ids).all() or np.any(ids != np.floor(ids)) or np.any(np.abs(ids) > 2 ** 53):
            raise ValueError(f"{role} IDs must be finite integers representable exactly")
        if pd.Series(ids).duplicated().any():
            raise ValueError(f"{role} contains duplicate zone IDs")
        for column in population_columns:
            numeric_values = pd.to_numeric(frame[column], errors="raise")
            if np.iscomplexobj(numeric_values.to_numpy()):
                raise ValueError(f"{role} population column {column} must be real")
            values = numeric_values.to_numpy(dtype=float)
            if not np.isfinite(values).all() or np.any(values < 0):
                raise ValueError(f"{role} population column {column} must be finite and nonnegative")
        return ids

    @staticmethod
    def _read_csv(path):
        # pandas renames repeated headers, which would hide an ambiguous schema.
        with open(path, newline="", encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle), [])
        if not header or len(set(header)) != len(header) or any(not name.strip() for name in header):
            raise ValueError("CSV headers must be nonempty and unique")
        return pd.read_csv(path)

    def _validate_settings(self):
        self._check_cancelled()
        self._require_file(self.mastergrid, "Mastergrid")
        with rasterio.open(self.mastergrid) as reference:
            self._validate_alignment(reference, reference, "Mastergrid")
            for role, path in [(f"Covariate {k}", v) for k, v in self.covariate.items()] + [
                    ("Mask", self.mask), ("Constrain", self.constrain)]:
                if path is None and role in {"Mask", "Constrain"}:
                    continue
                self._check_cancelled()
                self._require_file(path, role)
                with rasterio.open(path) as source:
                    self._validate_alignment(source, reference, role)
        pop = self.census["pop_column"]
        zone = self.census["id_column"]
        if not isinstance(pop, str) or not pop.strip() or not isinstance(zone, str) or not zone.strip():
            raise ValueError("Census population and ID column names are required")
        if pop == zone:
            raise ValueError("Census population and ID columns must differ")
        reserved_names = {"dens", "eligible_pixel_count", *[f"{name}_avg" for name in self.covariate]}
        if pop in reserved_names or zone in reserved_names:
            raise ValueError("Census column names conflict with derived training columns")
        self._require_file(self.census["path"], "Census")
        if Path(self.census["path"]).suffix.lower() != ".csv":
            raise ValueError("Census file must be CSV format")
        census = self._read_csv(self.census["path"])
        self.validate_census_frame(census, zone, [pop])
        if self.cv_group_column is not None:
            if self.cv_group_column not in census or census[self.cv_group_column].isna().any():
                raise ValueError("cv_group_column must exist and provide a nonmissing group for each census row")
        if self.agesex_data:
            self._require_file(self.agesex_data, "Age-sex census")
            if Path(self.agesex_data).suffix.lower() != ".csv":
                raise ValueError("Age-sex census file must be CSV format")
            frame = self._read_csv(self.agesex_data)
            age_column = re.compile(r"^[fm](?:_)?\d+(?:[_-]\d+|\+)?$", re.IGNORECASE)
            groups = [c for c in frame.columns if c != zone and age_column.fullmatch(c)]
            if not groups:
                raise ValueError("Age-sex census must contain population columns")
            self.validate_census_frame(frame, zone, groups, "Age-sex census")
            if set(pd.to_numeric(frame[zone])) != set(pd.to_numeric(census[zone])):
                raise ValueError("Age-sex census IDs must match census IDs")
        self._check_cancelled()
        inputs = [self.mastergrid, self.mask, self.constrain, self.census["path"],
                  self.agesex_data, *self.covariate.values()]
        reserved = [self.output_dir / name for name in ("prediction.tif", "model.pkl.gz",
                    "scaler.pkl.gz", "model_bundle.pkl.gz", "feature_importance.csv",
                    "cv_predictions.csv", "cv_metrics.json")]
        if any(Path(p).resolve() in reserved for p in inputs if p):
            raise ValueError("An input path conflicts with a model output path")

    @classmethod
    def validate_config_file(cls, config_path):
        with open(config_path, encoding="utf-8-sig") as handle:
            config = yaml.safe_load(handle)
        if not isinstance(config, dict):
            raise ValueError("Configuration YAML must contain a mapping")
        required = {"work_dir", "mastergrid", "covariates", "census_data",
                    "census_pop_column", "census_id_column"}
        missing = required - config.keys()
        if missing:
            raise ValueError(f"Missing required fields in config: {sorted(missing)}")
        accepted = set(inspect.signature(cls.__init__).parameters) - {"self", "cancellation_token"}
        unknown = config.keys() - accepted
        if unknown:
            raise ValueError(f"Unknown configuration fields: {sorted(unknown)}")
        if not isinstance(config["covariates"], dict) or not config["covariates"]:
            raise ValueError("covariates must be a nonempty dictionary")
        return config

    @classmethod
    def from_file(cls, config_path):
        config = cls.validate_config_file(config_path)
        config_dir = Path(config_path).parent.resolve()
        work_dir = config["work_dir"]
        if not isinstance(work_dir, str) or not work_dir:
            raise ValueError("work_dir must be a nonempty path")
        config["work_dir"] = str((config_dir / work_dir).resolve())
        return cls(**config)

    def to_config(self):
        """Snapshot every effective constructor setting, excluding run cancellation.

        Paths are canonical and defaults explicit, so replay does not depend on
        the current directory or a later change to the engine's default values.
        Logging stores a basename compatible with Settings/from_file validation.
        This method does not write configuration or modify source inputs.
        """
        special = {"covariates": dict(self.covariate), "census_data": self.census["path"],
                   "census_pop_column": self.census["pop_column"],
                   "census_id_column": self.census["id_column"],
                   "logging": {"level": self.logging["level"],
                               "file": Path(self.logging["file"]).name if self.logging["file"] else None}}
        config = {}
        for name in inspect.signature(type(self).__init__).parameters:
            if name in {"self", "cancellation_token"}:
                continue
            value = special[name] if name in special else getattr(self, name)
            if isinstance(value, Path):
                value = str(value.resolve())
            elif isinstance(value, tuple):
                value = list(value)
            config[name] = deepcopy(value)
        return config

    def __str__(self):
        return (f"pypopRF Settings: work_dir={self.work_dir}, output_dir={self.output_dir}, "
                f"mastergrid={self.mastergrid}, covariates={list(self.covariate)}, "
                f"block_size={self.block_size}, log_scale={self.log_scale}, "
                f"selection_threshold={self.selection_threshold}, random_seed={self.random_seed}")
