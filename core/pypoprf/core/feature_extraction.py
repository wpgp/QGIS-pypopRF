# src/pypoprf/core/feature_extraction.py
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any
import numpy as np
import pandas as pd
import geopandas as gpd

from ..utils.logger import get_logger
from ..utils.raster import raster_stat_stack
from ..config.settings import Settings

logger = get_logger()

class FeatureExtractor:
    """Extract and process features for population modeling."""

    # Supported file formats
    SUPPORTED_VECTOR_FORMATS = {'.shp', '.json', '.geojson', '.gpkg'}
    SUPPORTED_TABLE_FORMATS = {'.csv'}

    def __init__(self, settings: Settings):
        """
        Initialize feature extractor.

        Args:
            settings: Configuration settings
        """
        self.settings = settings
        self.features = None

    def load_table(self, path: str) -> pd.DataFrame:
        """
        Load data table from file.

        Args:
            path: Path to data file

        Returns:
            pd.DataFrame: Loaded data table
            gpd.GeoDataFrame: For spatial data formats

        Raises:
            ValueError: If file format is not supported or file cannot be read
            FileNotFoundError: If file does not exist
        """

        logger.info(f"Loading table from: {path}")
        path = Path(path)

        # Check if file exists
        if not path.exists():
            logger.error(f"File not found: {path}")
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        logger.debug(f"File extension: {ext}")

        try:
            if ext in self.SUPPORTED_VECTOR_FORMATS:
                logger.debug("Loading vector file")
                return gpd.read_file(path)
            elif ext in self.SUPPORTED_TABLE_FORMATS:
                logger.debug("Loading CSV file")
                return pd.read_csv(path)
            else:
                logger.error(f"Unsupported file format: {ext}")
                raise ValueError(f'Unsupported file format: {ext}')

        except Exception as e:
            logger.error(f"Failed to load file: {str(e)}")
            raise ValueError(f"Failed to load file: {str(e)}")

    def dump_table(self, df: pd.DataFrame, path: str, drop: Optional[List[str]] = None) -> None:
        """
        Save data table to file.

        Args:
            df: DataFrame to save
            path: Output file path
            drop: Optional list of columns to drop before saving

        Raises:
            ValueError: If file format is not supported or saving fails
            TypeError: If input arguments are invalid
        """
        logger.info(f"Saving table to: {path}")

        # Input validation
        if not isinstance(df, pd.DataFrame):
            logger.error("Input must be a pandas DataFrame")
            raise TypeError("df must be a pandas DataFrame")

        if drop is not None:
            if isinstance(drop, str):
                drop = [drop]  # Convert single string to list
            elif not isinstance(drop, list):
                logger.error("'drop' parameter must be a string or list of strings")
                raise TypeError("drop must be a string or list of strings")

            # Filter existing columns
            cols = df.columns.values
            drop = [d for d in drop if d in cols]
            df = df.drop(columns=drop)
            logger.debug(f"Dropped columns: {drop}")

        # Handle file saving
        path = Path(path)
        ext = path.suffix.lower()

        try:
            if ext in self.SUPPORTED_VECTOR_FORMATS:
                if not isinstance(df, gpd.GeoDataFrame):
                    logger.error("DataFrame must be GeoDataFrame for spatial formats")
                    raise ValueError("DataFrame must be GeoDataFrame for spatial formats")
                df.to_file(str(path), index=False)
                logger.debug("Saved as vector file")
            elif ext in self.SUPPORTED_TABLE_FORMATS:
                df.to_csv(path, index=False)
                logger.debug("Saved as CSV file")
            else:
                logger.error(f"Unsupported file format: {ext}")
                raise ValueError(f'Unsupported file format: {ext}')

            logger.info(f"Table successfully saved to {path}")

        except Exception as e:
            logger.error(f"Failed to save file: {str(e)}")
            raise ValueError(f"Failed to save file: {str(e)}")

    def validate_census(self,
                        census: pd.DataFrame,
                        simple: bool = False) -> Tuple[pd.DataFrame, str, str]:
        """Validate census data and return processed dataframe with column names."""
        logger.info("Validating census data")

        cols = census.columns.values
        pop_column = self.settings.census['pop_column']
        id_column = self.settings.census['id_column']

        logger.debug(f"Available columns: {cols.tolist()}")
        logger.debug(f"Required columns: pop={pop_column}, id={id_column}")

        if id_column not in cols:
            logger.error(f"ID column '{id_column}' not found in census data")
            raise ValueError('id_column not found in census data')
        if pop_column not in cols:
            logger.error(f"Population column '{pop_column}' not found in census data")
            raise ValueError('pop_column not found in census data')

        if pop_column == 'sum':
            logger.info("Renaming 'sum' column to 'pop'")
            pop_column = 'pop'
            census = census.rename(columns={'sum': 'pop'})

        if simple:
            logger.debug("Simplifying census DataFrame")
            census = census[[id_column, pop_column]]

        logger.info("Census data validation completed successfully")
        return census, id_column, pop_column


    def extract(self,
                save: Optional[str] = None,
                avg_only: bool = True) -> pd.DataFrame:
        """
        Extract features from raster data.

        Args:
            save: Optional path to save features
            avg_only: If True, keep only average statistics

        Returns:
            pd.DataFrame: Extracted features

        Raises:
            ValueError: If required data is missing
        """

        # Extract features from raster stack

        logger.info("Extracting features from raster stack")
        try:
            res = raster_stat_stack(
                self.settings.covariate,
                self.settings.mastergrid,
                by_block=self.settings.by_block,
                max_workers=self.settings.max_workers,
                block_size=self.settings.block_size
            )
            logger.debug(f"Initial features extracted: {res.shape}")
        except Exception as e:
            logger.error(f"Failed to extract features from raster stack: {str(e)}")
            raise

        # Load and validate census data
        try:
            logger.info("Loading census data")
            census = self.load_table(self.settings.census['path'])
            census, id_column, pop_column = self.validate_census(census, simple=True)
            logger.debug(f"Census data loaded: {len(census)} rows")
        except Exception as e:
            logger.error(f"Failed to load or validate census data: {str(e)}")
            raise

        # Merge with census data
        logger.info("Merging features with census data")
        res = pd.merge(
            res,
            census,
            left_on='id',
            right_on=id_column,
            how='inner'
        )
        logger.debug(f"Merged data shape: {res.shape}")

        # Get count for density calculation
        count = None
        for c in res.columns.values:
            if c.endswith('count'):
                count = res[c].values
                logger.debug(f"Using '{c}' for density calculation")
                break

        if count is None:
            logger.error("No count column found for density calculation")
            raise ValueError("No count column found for density calculation")

        # Filter columns if avg_only is True
        if avg_only:
            logger.info("Filtering for average statistics only")
            cols = ['id', 'pop']
            cols.extend([c for c in res.columns if c.endswith('avg')])
            res = res[cols]
            logger.debug(f"Selected columns: {cols}")

        # Calculate population density
        logger.info("Calculating population density")
        res['dens'] = np.divide(res['pop'], count, where=(count > 0))

        # Check for potential issues in density calculation
        zero_counts = np.sum(count == 0)
        if zero_counts > 0:
            logger.warning(f"Found {zero_counts} zones with zero count")

        inf_density = np.sum(np.isinf(res['dens']))
        if inf_density > 0:
            logger.warning(f"Found {inf_density} zones with infinite density")

        # Save features
        logger.info("Saving extracted features")
        output_path = Path(self.settings.work_dir) / 'output' / 'features.csv'
        self.dump_table(res, str(output_path))
        logger.debug(f"Features saved to: {output_path}")

        # Save to additional location if specified
        if save:
            logger.info(f"Saving features to additional location: {save}")
            save_path = Path(self.settings.work_dir) / save
            self.dump_table(res, str(save_path))

        logger.info(f"Feature extraction completed. Extracted features: {res.columns.values.tolist()}")

        self.features = res
        return res
