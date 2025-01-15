# src/pypoprf/config/settings.py
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import rasterio
import yaml

from pypoprf.utils.logger import get_logger

logger = get_logger()

class Settings:
    """
    Configuration settings manager for pypopRF.

    This class handles all configuration settings for population modeling,
    including file paths, processing parameters, and validation of inputs.

    Attributes:
        work_dir (Path): Working directory path
        data_dir (Path): Data directory path
        mastergrid (str): Path to mastergrid file or 'create'
        mask (str): Path to (water) mask file
        constrain (str): Path to raster for constraining population distribution
        covariate (dict): Dictionary of covariate names and paths
        census (dict): Census configuration including path and column names
        output_dir (Path): Output directory path
        by_block (bool): Whether to process by blocks
        block_size (tuple): Size of processing blocks (width, height)
        max_workers (int): Maximum number of parallel workers
        show_progress (bool): Whether to show progress bars

    Raises:
        ValueError: If required settings are missing or invalid
        FileNotFoundError: If required files don't exist
    """
    def __init__(self,
                 work_dir: str = ".",
                 data_dir: str = "data",
                 mastergrid: Optional[str] = None,
                 mask: Optional[str] = None,
                 constrain: Optional[str] = None,
                 covariates: Optional[Dict[str, str]] = None,
                 census_data: Optional[str] = None,
                 census_pop_column: Optional[str] = None,
                 census_id_column: Optional[str] = None,
                 output_dir: Optional[str] = None,
                 by_block: bool = True,
                 block_size: Tuple[int, int] = (512, 512),
                 max_workers: int = 4,
                 show_progress: bool = True,
                 logging: Optional[Dict] = None):

        """
        Initialize Settings with configuration parameters.

        Args:
            work_dir: Root directory for the project
            data_dir: Directory containing input data files
            mastergrid: Path to mastergrid file or 'create'
            mask (str): Path to (water) mask file
            constrain (str): Path to raster for constraining population distribution
            covariates: Dictionary mapping covariate names to file paths
            census_data: Path to census data file
            census_pop_column: Name of population column in census data
            census_id_column: Name of ID column in census data
            output_dir: Directory for output files
            by_block: Whether to process by blocks
            block_size: Tuple of (width, height) for processing blocks
            max_workers: Number of parallel processing workers
            show_progress: Whether to display progress bars

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        logger.info("Initializing pypopRF settings")

        # Convert working directory to absolute path
        self.work_dir = Path(work_dir).resolve()
        self.data_dir = self.work_dir / data_dir

        # Handle mastergrid path
        self.mastergrid = str(Path(mastergrid)) if mastergrid else None
        if self.mastergrid and self.mastergrid != 'create':
            if not Path(self.mastergrid).is_absolute():
                self.mastergrid = str(self.data_dir / mastergrid)

        # Handle (water) mask path
        self.mask = str(Path(mask)) if mask else None
        if self.mask:
            if not Path(self.mask).is_absolute():
                self.mask = str(self.data_dir / mask)

        # Handle constrain path
        self.constrain = str(Path(constrain)) if constrain else None
        if self.constrain:
            if not Path(self.constrain).is_absolute():
                self.constrain = str(self.data_dir / constrain)

        # Process covariate paths
        self.covariate = {}
        if covariates:
            for key, path in covariates.items():
                if not Path(path).is_absolute():
                    path = str(self.data_dir / path)
                self.covariate[key] = path

        if not self.covariate:
            raise ValueError("At least one covariate is required")

        # Process census path
        census_path = Path(census_data) if census_data else None
        self.census = {
            'path': str(self.data_dir / census_data) if census_data and not census_path.is_absolute() else census_data,
            'pop_column': census_pop_column,
            'id_column': census_id_column
        }

        # Set output directory
        if output_dir:
            self.output_dir = Path(output_dir)
            if not self.output_dir.is_absolute():
                self.output_dir = self.work_dir / output_dir
        else:
            self.output_dir = self.work_dir / 'output'

        # Set processing parameters
        self.by_block = by_block
        self.block_size = tuple(block_size)
        self.max_workers = max_workers
        self.show_progress = show_progress

        self.logging = {
            'level': 'INFO',
            'file': 'pypoprf.log'
        }
        if logging:
            self.logging.update(logging)

        if self.logging['file']:
            self.logging['file'] = str(self.output_dir / self.logging['file'])
        logger.set_level(self.logging['level'])

        # Validate all settings
        self._validate_settings()
        logger.info("Settings initialization completed")

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

        logger.info("Validating settings...")

        if not self.census['path']:
            logger.error("Census data path is required")
            raise ValueError("Census data path is required")
        if not self.census['pop_column']:
            logger.error("Census population column name is required")
            raise ValueError("Census population column name is required")
        if not self.census['id_column']:
            logger.error("Census ID column name is required")
            raise ValueError("Census ID column name is required")
        if not self.covariate:
            logger.error("At least one covariate is required")
            raise ValueError("At least one covariate is required")

        template_profile = None

        if self.mastergrid != 'create':
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
                logger.warning(f"Constraining file not found: {self.constrain}, proceeding without constrain")
                self.constrain = None

        logger.info("Validating covariates...")
        for name, path in self.covariate.items():
            if not Path(path).is_file():
                logger.error(f"Covariate file not found: {path} ({name})")
                raise FileNotFoundError(f"Covariate file not found: {path} ({name})")

            with rasterio.open(path) as src:
                if template_profile is None:
                    template_profile = src.profile
                else:
                    if src.crs != template_profile['crs']:
                        logger.warning(f"Covariate {name}: CRS mismatch")
                    if src.transform[0] != template_profile['transform'][0]:
                        logger.warning(f"Covariate {name}: Resolution mismatch")
                    if src.width != template_profile['width']:
                        logger.warning(f"Covariate {name}: Width mismatch")
                    if src.height != template_profile['height']:
                        logger.warning(f"Covariate {name}: Height mismatch")

        logger.info("Validating census data...")
        census_path = Path(self.census['path'])
        if not census_path.is_file():
            logger.error(f"Census file not found: {census_path}")
            raise FileNotFoundError(f"Census file not found: {census_path}")

        if census_path.suffix.lower() != '.csv':
            logger.error("Census file must be CSV format")
            raise ValueError("Census file must be CSV format")

        try:
            df = pd.read_csv(census_path, nrows=1)
            missing_cols = []
            for col in [self.census['pop_column'], self.census['id_column']]:
                if col not in df.columns:
                    missing_cols.append(col)
                if missing_cols:
                    logger.error(f"Missing required columns in census data: {', '.join(missing_cols)}")
                    raise ValueError(f"Missing required columns in census data: {', '.join(missing_cols)}")
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
            'work_dir', 'covariates', 'census_data',
            'census_pop_column', 'census_id_column'
        }

        with open(config_path) as f:
            config = yaml.safe_load(f)

        missing = required_fields - set(config.keys())
        if missing:
            logger.error(f"Missing required fields in config: {missing}")
            raise ValueError(f"Missing required fields in config: {missing}")

        if not isinstance(config.get('covariates', {}), dict):
            logger.error("'covariates' must be a dictionary")
            raise ValueError("'covariates' must be a dictionary")

        logger.info("Configuration file validation successful")

    @classmethod
    def from_file(cls, config_path: str) -> 'Settings':
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
        if config['work_dir'] == '.':
            config['work_dir'] = str(config_dir)
        elif not Path(config['work_dir']).is_absolute():
            config['work_dir'] = str(config_dir / config['work_dir'])

        logger.info("Settings loaded successfully")
        return cls(**config)

    def __str__(self) -> str:
        """
        Create string representation of settings.

        Returns:
            str: Formatted string containing all settings
        """

        covariate_str = '\n    '.join(f"- {key}: {value}" for key, value in self.covariate.items())
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
            f"  Processing:\n"
            f"    By Block: {self.by_block}\n"
            f"    Block Size: {self.block_size}\n"
            f"    Max Workers: {self.max_workers}\n"
            f"    Show Progress: {self.show_progress}"
            f"  Logging:\n"
            f"    Level: {self.logging['level']}\n"
            f"    File: {self.logging['file']}"
        )