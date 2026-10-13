from pathlib import Path
from typing import Optional, List, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from ..config.settings import Settings
from ..utils.logger import get_logger
from ..utils.raster import raster_stat_stack, validate_census, check_cancel, protect_output
from ..utils.runtime import atomic_output, CancelledError

logger = get_logger()


class FeatureExtractor:
    """Extract and process features for population modeling."""

    # Supported file formats
    SUPPORTED_VECTOR_FORMATS = {".shp", ".json", ".geojson", ".gpkg"}
    SUPPORTED_TABLE_FORMATS = {".csv"}

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
                # pandas mangles duplicated headers, making validation too late.
                import csv
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    headers = next(csv.reader(handle), [])
                if len(headers) != len(set(headers)):
                    raise ValueError("Duplicate census column names")
                return pd.read_csv(path)
            else:
                logger.error(f"Unsupported file format: {ext}")
                raise ValueError(f"Unsupported file format: {ext}")

        except CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed to load file: {str(e)}")
            raise ValueError(f"Failed to load file: {str(e)}")

    def dump_table(
        self, df: pd.DataFrame, path: str, drop: Optional[List[str]] = None
    ) -> None:
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
        input_paths = [self.settings.mastergrid, self.settings.census.get("path"),
                       *self.settings.covariate.values(), getattr(self.settings, "mask", None),
                       getattr(self.settings, "constrain", None), getattr(self.settings, "agesex_data", None)]
        protect_output(path, input_paths)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if ext in self.SUPPORTED_VECTOR_FORMATS:
                if not isinstance(df, gpd.GeoDataFrame):
                    logger.error("DataFrame must be GeoDataFrame for spatial formats")
                    raise ValueError("DataFrame must be GeoDataFrame for spatial formats")
                df.to_file(str(path), index=False)
                logger.debug("Saved as vector file")
            elif ext in self.SUPPORTED_TABLE_FORMATS:
                with atomic_output(path, getattr(self.settings, "cancellation_token", None)) as temporary:
                    df.to_csv(temporary, index=False)
                logger.debug("Saved as CSV file")
            else:
                logger.error(f"Unsupported file format: {ext}")
                raise ValueError(f"Unsupported file format: {ext}")

        except CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed to save file: {str(e)}")
            raise ValueError(f"Failed to save file: {str(e)}")

    def validate_census(
        self, census: pd.DataFrame, simple: bool = False
    ) -> Tuple[pd.DataFrame, str, str]:
        """Validate census data and return processed dataframe with column names."""
        logger.info("Validating census data")

        cols = census.columns.values
        pop_column = self.settings.census["pop_column"]
        id_column = self.settings.census["id_column"]

        logger.debug(f"Required columns: pop={pop_column}, id={id_column}")

        if id_column not in cols:
            logger.error(f"ID column '{id_column}' not found in census data")
            raise ValueError("id_column not found in census data")
        if pop_column not in cols:
            logger.error(f"Population column '{pop_column}' not found in census data")
            raise ValueError("pop_column not found in census data")

        census = validate_census(census, id_column, pop_column)
        group_column = getattr(self.settings, "cv_group_column", None)
        if group_column is not None:
            if group_column not in census:
                raise ValueError(f"CV group column missing in census: {group_column}")
            groups = census[group_column]
            if groups.isna().any() or groups.astype(str).str.strip().eq("").any():
                raise ValueError("CV groups must be nonmissing and nonempty for every census zone")
        if simple:
            logger.debug("Simplifying census DataFrame")
            columns = [id_column, pop_column]
            if group_column is not None and group_column not in columns:
                columns.append(group_column)
            census = census[columns]

        logger.info("Census data validation completed successfully")
        return census, id_column, pop_column

    def get_dummy(self) -> pd.DataFrame:
        """
        Get dummy features

        Returns:
            pd.DataFrame: Dummy features
        """
        logger.info("Creating dummy features")
        res = pd.DataFrame({self.settings.census["id_column"]: [1],
                            self.settings.census["pop_column"]: [1], "eligible_pixel_count": [1]})
        for c in self.settings.covariate:
            res[f'{c}_avg'] = [1]

        res['dens'] = [1]
        group_column = getattr(self.settings, "cv_group_column", None)
        if group_column is not None and group_column not in res:
            res[group_column] = ["dummy"]

        self.features = res
        return res

    def extract(self, save: Optional[str] = None, avg_only: bool = True) -> pd.DataFrame:
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

        # Feature/support names must not collide with census identifiers or totals.
        reserved = {"dens", "eligible_pixel_count"}
        feature_names = {f"{key}_{stat}" for key in self.settings.covariate
                         for stat in ("count", "sum", "min", "max", "avg", "var", "std")}
        census_names = {self.settings.census["id_column"], self.settings.census["pop_column"]}
        if census_names & (reserved | feature_names):
            raise ValueError("Census column names conflict with feature or support columns")
        group_column = getattr(self.settings, "cv_group_column", None)
        if group_column is not None and group_column in reserved | feature_names:
            raise ValueError("CV group column conflicts with feature or support columns")

        # Extract features from raster stack

        logger.info("Extracting features from raster stack")
        try:
            res = raster_stat_stack(
                self.settings.covariate,
                self.settings.mastergrid,
                by_block=self.settings.by_block,
                max_workers=self.settings.max_workers,
                block_size=self.settings.block_size,
                cancellation_token=getattr(self.settings, "cancellation_token", None),
            )
            logger.debug(f"Initial features extracted: {res.shape}")
        except Exception as e:
            logger.error(f"Failed to extract features from raster stack: {str(e)}")
            raise

        # Load and validate census data
        try:
            census = self.load_table(self.settings.census["path"])
            census, id_column, pop_column = self.validate_census(census, simple=True)
            logger.debug(f"Census data loaded: {len(census)} rows")
        except Exception as e:
            logger.error(f"Failed to load or validate census data: {str(e)}")
            raise

        # Merge with census data
        logger.info("Merging features with census data")
        if id_column != "id":
            res = res.rename(columns={"id": id_column})
        missing = census.loc[~census[id_column].isin(res[id_column]), id_column].tolist()
        if missing:
            raise ValueError(f"Census zones have no eligible pixels: {missing}")
        res = pd.merge(census, res, on=id_column, how="left", validate="one_to_one")
        logger.debug(f"Merged data shape: {res.shape}")

        # Get count for density calculation
        count = res["eligible_pixel_count"].to_numpy(dtype=float)
        if not np.isfinite(count).all() or (count <= 0).any():
            raise ValueError("Training zones must have eligible pixels")
        feature_columns = [f"{key}_avg" for key in self.settings.covariate]
        if not feature_columns:
            raise ValueError("At least one covariate is required")
        invalid = ~np.isfinite(res[feature_columns].to_numpy(dtype=float)).all(axis=1)
        if invalid.any():
            raise ValueError(f"Census zones lack valid covariate means: {res.loc[invalid, id_column].tolist()}")

        # Filter columns if avg_only is True
        if avg_only:
            logger.info("Filtering for average statistics only")
            pop_column = self.settings.census["pop_column"]
            id_column = self.settings.census["id_column"]
            cols = [id_column, pop_column, "eligible_pixel_count"] + feature_columns
            if group_column is not None and group_column not in cols:
                cols.append(group_column)
            res = res[cols].copy()
            logger.debug(f"Selected columns: {cols}")

        # Calculate population density
        logger.info("Calculating population density")
        pop_column = self.settings.census["pop_column"]
        res["dens"] = res[pop_column].to_numpy(dtype=float) / count

        # Check for potential issues in density calculation
        zero_counts = np.sum(count == 0)
        if zero_counts > 0:
            logger.warning(f"Found {zero_counts} zones with zero count")

        inf_density = np.sum(np.isinf(res["dens"]))
        if inf_density > 0:
            logger.warning(f"Found {inf_density} zones with infinite density")

        # Save features
        logger.info("Saving extracted features")
        check_cancel(getattr(self.settings, "cancellation_token", None))
        output_path = Path(getattr(self.settings, "output_dir", Path(self.settings.work_dir) / "output")) / "features.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.dump_table(res, str(output_path))
        logger.debug(f"Features saved to: {output_path}")

        # Save to additional location if specified
        if save:
            logger.info(f"Saving features to additional location: {save}")
            save_path = Path(self.settings.work_dir) / save
            self.dump_table(res, str(save_path))

        logger.info(f"Extracted features: {res.columns.values.tolist()}")

        self.features = res
        return res
