from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import rasterio
import yaml

from ....q_models.config_manager import ConfigManager
from ..utils.logger import get_logger

logger = get_logger()


def rename_column_in_csv(file_path: str, old_column_name: str, new_column_name: str) -> bool:

    try:
        logger.info(f"Renaming column '{old_column_name}' to '{new_column_name}' in file {file_path}")

        df = pd.read_csv(file_path)

        if old_column_name not in df.columns:
            logger.error(f"Column '{old_column_name}' not found in the file")
            return False

        df = df.rename(columns={old_column_name: new_column_name})
        df.to_csv(file_path, index=False)
        logger.info(f"Successfully renamed column in {file_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to rename column in CSV file: {str(e)}")
        return False


class Settings:
    """Configuration settings manager for pypopRF.

    This class handles configuration settings for population modeling,
    including file paths, processing parameters, and validation of inputs.
    """

    def __init__(
        self,
        work_dir: str = ".",
        data_dir: str = "data",
        mastergrid: Optional[str] = None,
        mask: Optional[str] = None,
        constrain: Optional[str] = None,
        covariates: Optional[Dict[str, str]] = None,
        census_data: Optional[str] = None,
        census_pop_column: Optional[str] = None,
        census_id_column: Optional[str] = None,
        agesex_data: Optional[str] = None,
        output_dir: Optional[str] = None,
        by_block: bool = True,
        block_size: Tuple[int, int] = (512, 512),
        max_workers: int = 4,
        show_progress: bool = True,
        log_scale: bool = True,
        selection_threshold: float = 0.01,
        logging: Optional[Dict] = None,
    ):
        """Initialize Settings.

        Args:
            work_dir: Root directory for project
            data_dir: Directory for input files
            mastergrid: Path to mastergrid file
            mask: Path to water mask file (optional)
            constrain: Path to constraining raster (optional)
            covariates: Dictionary mapping covariate names to file paths
            census_data: Path to census CSV file
            census_pop_column: Name of population column
            census_id_column: Name of ID column
            agesex_data: Path to age-sex CSV file (optional)
            output_dir: Directory for outputs
            by_block: Process by blocks
            block_size: Block dimensions (width, height)
            max_workers: Max parallel workers
            show_progress: Show progress bars
            log_scale: Whether to train model on log(dens)
            selection_threshold: Threshold for feature selection in the model
            logging: Logging configuration

        Raises:
            ValueError: If required settings are invalid
            FileNotFoundError: If required files don't exist
        """
        logger.info("Initializing pypopRF settings")

        # Initialize paths
        self._init_paths(work_dir, data_dir, output_dir)

        # Handle input files
        self._init_input_files(mastergrid, mask, constrain)

        # Handle covariates
        self._init_covariates(covariates)

        # Handle census data
        self._init_census(census_data, census_pop_column, census_id_column, agesex_data)

        # Processing settings
        self.by_block = by_block
        self.block_size = tuple(block_size)
        self.max_workers = max_workers
        self.show_progress = show_progress
        self.log_scale = log_scale
        self.selection_threshold = selection_threshold

        # Logging settings
        self._init_logging(logging)

        # Validate settings
        self._validate_settings()
        logger.info("Settings initialization completed")

    def _init_paths(self, work_dir: str, data_dir: str, output_dir: Optional[str]) -> None:
        """Initialize directory paths."""
        self.work_dir = Path(work_dir).resolve()
        self.data_dir = self.work_dir / data_dir

        if output_dir:
            self.output_dir = Path(output_dir)
            if not self.output_dir.is_absolute():
                self.output_dir = self.work_dir / output_dir
        else:
            self.output_dir = self.work_dir / "output"

    def _init_input_files(
        self, mastergrid: Optional[str], mask: Optional[str], constrain: Optional[str]
    ) -> None:
        """Initialize input file paths."""
        # Process paths relative to data directory
        self.mastergrid = self._resolve_path(mastergrid)
        self.mask = self._resolve_path(mask)
        self.constrain = self._resolve_path(constrain)

    def _init_covariates(self, covariates: Optional[Dict[str, str]]) -> None:
        """Initialize covariate paths."""
        self.covariate = {}
        if covariates:
            self.covariate = {
                key: self._resolve_path(path) for key, path in covariates.items()
            }

        if not self.covariate:
            raise ValueError("At least one covariate is required")

    def _init_census(
        self,
        census_data: Optional[str],
        pop_column: Optional[str],
        id_column: Optional[str],
        agesex_data: Optional[str],
    ) -> None:
        """Initialize census data settings."""
        self.census = {
            "path": self._resolve_path(census_data),
            "pop_column": pop_column,
            "id_column": id_column,
        }
        self.agesex_data = self._resolve_path(agesex_data)

    def _init_logging(self, logging: Optional[Dict]) -> None:
        """Initialize logging settings."""
        self.logging = {"level": "INFO", "file": "pypoprf.log"}
        if logging:
            self.logging.update(logging)

        if self.logging["file"]:
            self.logging["file"] = str(self.output_dir / self.logging["file"])
        logger.set_level(self.logging["level"])

    def _resolve_path(self, path: Optional[str]) -> Optional[str]:
        """Resolve path relative to data directory."""
        if not path:
            return None

        p = Path(path)
        if not p.is_absolute():
            return str(self.data_dir / path)
        return str(p)

    def _validate_settings(self) -> None:
        """
        Validate settings and check file existence.

        Performs comprehensive validation of all settings including:
        - Required paths and parameters
        - File existence
        - Raster compatibility (CRS, resolution, dimensions)
        - Census data format and required columns

        Raises:
            ValueError: If settings are invalid
            FileNotFoundError: If required files don't exist
        """

        logger.info("Validating settings!")

        if not self.census["path"]:
            logger.error("Census data path is required")
            raise ValueError("Census data path is required")
        if not self.census["pop_column"]:
            logger.error("Census population column name is required")
            raise ValueError("Census population column name is required")
        if not self.census["id_column"]:
            logger.error("Census ID column name is required")
            raise ValueError("Census ID column name is required")
        if not self.covariate:
            logger.error("At least one covariate is required")
            raise ValueError("At least one covariate is required")

        template_profile = None

        if self.mastergrid != "create":
            if not Path(self.mastergrid).is_file():
                logger.error(f"Mastergrid file not found: {self.mastergrid}")
                raise FileNotFoundError(f"Mastergrid file not found: {self.mastergrid}")
            with rasterio.open(self.mastergrid) as src:
                template_profile = src.profile
                logger.debug("Mastergrid template profile loaded")

        if self.mask is not None:
            mask_path = Path(self.mask)
            if not mask_path.is_file():
                logger.error(f"Mask file not found: {self.mask}")
                raise FileNotFoundError(f"Mask file not found: {self.mask}")

        if self.constrain is not None:
            constrain_path = Path(self.constrain)
            if not constrain_path.is_file():
                logger.warning(
                    f"Constraining file not found: {self.constrain}, proceeding without constrain"
                )
                self.constrain = None

        logger.info("Validating covariates")
        for name, path in self.covariate.items():
            if not Path(path).is_file():
                logger.error(f"Covariate file not found: {path} ({name})")
                raise FileNotFoundError(f"Covariate file not found: {path} ({name})")

            with rasterio.open(path) as src:
                if template_profile is None:
                    template_profile = src.profile
                else:
                    if src.crs != template_profile["crs"]:
                        logger.warning(f"Covariate {name}: CRS mismatch")
                    if src.transform[0] != template_profile["transform"][0]:
                        logger.warning(f"Covariate {name}: Resolution mismatch")
                    if src.width != template_profile["width"]:
                        logger.warning(f"Covariate {name}: Width mismatch")
                    if src.height != template_profile["height"]:
                        logger.warning(f"Covariate {name}: Height mismatch")

        logger.info("Validating census data")
        census_path = Path(self.census["path"])
        if not census_path.is_file():
            logger.error(f"Census file not found: {census_path}")
            raise FileNotFoundError(f"Census file not found: {census_path}")

        if census_path.suffix.lower() != ".csv":
            logger.error("Census file must be CSV format")
            raise ValueError("Census file must be CSV format")

        if self.census["pop_column"] == "sum":
            logger.warning("Column name 'sum' can cause conflicts with data processing")
            new_column_name = "population"

            success = rename_column_in_csv(str(census_path), "sum", new_column_name)
            if success:
                logger.info(f"Renamed column 'sum' to '{new_column_name}' in file")
                self.census["pop_column"] = new_column_name
                config_path = Path(self.work_dir) / "config.yaml"
                if config_path.exists():
                    temp_config = ConfigManager(logger)
                    temp_config.config_path = str(config_path)
                    temp_config.update_config("census_pop_column", "population")

        # Validate agesex data if provided
        if self.agesex_data is not None:
            agesex_path = Path(self.agesex_data)
            if not agesex_path.is_file():
                logger.warning(
                    f"Age-sex census file not found: {self.agesex_data}, proceeding without age-sex structure"
                )
                self.agesex_data = None
            elif agesex_path.suffix.lower() != ".csv":
                logger.error("Age-sex census file must be CSV format")
                raise ValueError("Age-sex census file must be CSV format")

        try:
            df = pd.read_csv(census_path, nrows=1)
            missing_cols = []
            for col in [self.census["pop_column"], self.census["id_column"]]:
                if col not in df.columns:
                    missing_cols.append(col)
                if missing_cols:
                    logger.error(
                        f"Missing required columns in census data: {', '.join(missing_cols)}"
                    )
                    raise ValueError(
                        f"Missing required columns in census data: {', '.join(missing_cols)}"
                    )
        except Exception as e:
            logger.error(f"Error reading census file: {str(e)}")
            raise ValueError(f"Error reading census file: {str(e)}")

        logger.info("Settings validation completed successfully")

    @classmethod
    def validate_config_file(cls, config_path: str) -> None:
        """
        Validate configuration file structure.

        Args:
            config_path: Path to YAML configuration file

        Raises:
            ValueError: If configuration file is missing required fields
                       or has invalid structure
        """
        logger.info(f"Validating configuration file: {config_path}")

        required_fields = {
            "work_dir",
            "covariates",
            "census_data",
            "census_pop_column",
            "census_id_column",
        }

        with open(config_path) as f:
            config = yaml.safe_load(f)

        missing = required_fields - set(config.keys())
        if missing:
            logger.error(f"Missing required fields in config: {missing}")
            raise ValueError(f"Missing required fields in config: {missing}")

        if not isinstance(config.get("covariates", {}), dict):
            logger.error("'covariates' must be a dictionary")
            raise ValueError("'covariates' must be a dictionary")

        logger.info("Configuration file validation successful")

    @classmethod
    def from_file(cls, config_path: Path) -> "Settings":
        """
        Create Settings instance from configuration file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Settings: Initialized Settings instance

        Raises:
            ValueError: If configuration file is invalid
        """
        logger.info(f"Loading settings from file: {config_path}")

        cls.validate_config_file(config_path)

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Resolve work_dir relative to config file location
        config_dir = Path(config_path).parent.resolve()
        if config["work_dir"] == ".":
            config["work_dir"] = str(config_dir)
        elif not Path(config["work_dir"]).is_absolute():
            config["work_dir"] = str(config_dir / config["work_dir"])

        return cls(**config)

    def __str__(self) -> str:
        """
        Create string representation of settings.

        Returns:
            str: Formatted string containing all settings
        """

        covariate_str = "\n    ".join(
            f"- {key}: {value}" for key, value in self.covariate.items()
        )
        return (
            f"pypopRF Settings:\n"
            f"  Work Directory: {self.work_dir}\n"
            f"  Output Directory: {self.output_dir}\n"
            f"  Mastergrid: {self.mastergrid}\n"
            f"  Mask: {self.mask}\n"
            f"  Constrain: {self.constrain}\n"
            f"  Covariates:\n    {covariate_str}\n"
            f"  Census:\n"
            f"    Path: {self.census['path']}\n"
            f"    Pop Column: {self.census['pop_column']}\n"
            f"    ID Column: {self.census['id_column']}\n"
            f"  Age-Sex Data: {self.agesex_data}\n"
            f"  Processing:\n"
            f"    By Block: {self.by_block}\n"
            f"    Block Size: {self.block_size}\n"
            f"    Max Workers: {self.max_workers}\n"
            f"    Show Progress: {self.show_progress}"
            f"    Log Scale: {self.log_scale}"
            f"    CCS Limit: {self.log_scale}"
            f"  Logging:\n"
            f"    Level: {self.logging['level']}\n"
            f"    File: {self.logging['file']}"
        )
