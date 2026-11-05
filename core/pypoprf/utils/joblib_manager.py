import tempfile
import shutil
import os
from typing import Generator
from contextlib import contextmanager
import logging
from joblib import parallel_config

logger = logging.getLogger(__name__)


@contextmanager
def joblib_resources(
    qgis_mode: bool = False, base_dir: str = None
) -> Generator[str, None, None]:
    """
    Context manager for handling joblib temporary resources.

    Creates a temporary directory for joblib to use and ensures cleanup
    after processing is complete.

    Args:
        qgis_mode (bool): If True, adapts for QGIS environment.
        base_dir (str): Base directory for temporary files (default: system temp).

    Yields:
        str: Path to temporary directory
    """
    temp_folder = None

    try:
        if qgis_mode and base_dir:
            base_temp_dir = os.path.abspath(base_dir)
            os.makedirs(base_temp_dir, exist_ok=True)
            temp_folder = tempfile.mkdtemp(prefix="pypoprf_joblib_", dir=base_temp_dir)
            logger.debug(f"Created QGIS temp directory: {temp_folder}")
        else:
            temp_folder = tempfile.mkdtemp(prefix="pypoprf_joblib_")
            logger.debug(f"Created standard temp directory: {temp_folder}")

        # Joblib configuration is thread-local. Two runs must not race over
        # process-wide JOBLIB_TEMP_FOLDER or remove each other's resources.
        with parallel_config(temp_folder=temp_folder):
            yield temp_folder

    finally:
        # Cleanup the temporary directory
        try:
            if temp_folder and os.path.exists(temp_folder):
                shutil.rmtree(temp_folder)
                logger.debug(f"Cleaned up temp directory: {temp_folder}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp folder {temp_folder}: {e}")
