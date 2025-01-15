# src/pypoprf/utils/config_utils.py
from pathlib import Path
from typing import Dict, Any
import yaml

from pypoprf.utils.logger import get_logger

logger = get_logger()

def create_config_template(output_path: Path,
                           data_dir: str = "data",
                           prefix: str = "test_") -> None:
    """
    Create a configuration file template with proper paths.

    Args:
        output_path: Path where config file will be saved
        data_dir: Name of directory for input data files
        prefix: Prefix added to input filenames

    Raises:
        ValueError: If arguments are invalid
        OSError: If file cannot be written
    """
    logger.info("Creating configuration template")
    logger.debug(f"Parameters: output_path={output_path}, data_dir={data_dir}, prefix={prefix}")

    # Validate inputs
    if not isinstance(output_path, (str, Path)):
        logger.error("output_path must be string or Path")
        raise ValueError("output_path must be string or Path")
    output_path = Path(output_path)

    if not isinstance(data_dir, str):
        logger.error("data_dir must be string")
        raise ValueError("data_dir must be string")
    if not isinstance(prefix, str):
        logger.error("prefix must be string")
        raise ValueError("prefix must be string")

    # Define default configuration
    logger.debug("Creating default configuration dictionary")
    config: Dict[str, Any] = {
        'work_dir': ".",
        'data_dir': data_dir,
        'covariates': {
            'cnt': f"{prefix}buildingCount.tif",
            'srf': f"{prefix}buildingSurface.tif",
            'vol': f"{prefix}buildingVolume.tif"
        },
        'mastergrid': f"{prefix}mastergrid.tif",
        'mask': f"{prefix}mask.tif",
        'constrain': f"{prefix}constrain.tif",
        'census_data': f"{prefix}admin3.csv",
        'census_pop_column': "pop",
        'census_id_column': "id",
        'output_dir': "output",
        'by_block': True,
        'block_size': [512, 512],
        'max_workers': 8,
        'show_progress': True,
        'logging': {
            'level': 'INFO',
            'file': 'pypoprf.log',
        },
    }
    logger.debug(f"Configuration template created with covariates: {list(config['covariates'].keys())}")

    header_comment = """# pypopRF configuration file
#
# Configuration options:
#   work_dir: Root directory for project
#   data_dir: Directory containing input files
#   covariates: Dictionary of covariate raster files
#   mastergrid: Path to mastergrid file
#   mask: Path to mask file
#   constrain: Path to file for constraining population dist.
#   census_data: Path to census data file
#   census_pop_column: Population column in census data
#   census_id_column: ID column in census data
#   output_dir: Directory for output files
#   by_block: Whether to process data by block
#   block_size: Processing block size [width, height]
#   max_workers: Number of parallel workers
#   show_progress: Whether to show progress bars
#   logging: Settings for logging process
#     level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
#     file: Log file name (default: pypoprf.log, saved in output directory)

# Logging levels:
#   DEBUG    - Detailed information for debugging
#   INFO     - Confirmation that things are working as expected
#   WARNING  - Something unexpected happened but process continues
#   ERROR    - Serious problem, software is unable to perform function
#   CRITICAL - Program cannot continue running
#
# Example covariates:
#   covariates:
#     key1: "path/to/raster1.tif"
#     key2: "path/to/raster2.tif"
#
"""

    try:
        # Create parent directories if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created parent directories: {output_path.parent}")

        # Write config file
        logger.info(f"Writing configuration to: {output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(header_comment)
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.info("Configuration template created successfully")


    except Exception as e:
        error_msg = f"Failed to write config file: {str(e)}"
        logger.error(error_msg)
        raise OSError(error_msg)
