import tempfile
import shutil
import os
from typing import Generator
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

@contextmanager
def joblib_resources(qgis_mode: bool = False, base_dir: str = None) -> Generator[str, None, None]:
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
    old_temp = os.environ.get('JOBLIB_TEMP_FOLDER')

    try:
        if qgis_mode and base_dir:
            base_temp_dir = os.path.abspath(base_dir)
            os.makedirs(base_temp_dir, exist_ok=True)
            temp_folder = tempfile.mkdtemp(prefix='pypoprf_joblib_', dir=base_temp_dir)
            logger.debug(f"Created QGIS temp directory: {temp_folder}")
        else:
            temp_folder = tempfile.mkdtemp(prefix='pypoprf_joblib_')
            logger.debug(f"Created standard temp directory: {temp_folder}")

        os.environ['JOBLIB_TEMP_FOLDER'] = temp_folder
        yield temp_folder

    finally:
        # Restore the original JOBLIB_TEMP_FOLDER
        if old_temp is not None:
            os.environ['JOBLIB_TEMP_FOLDER'] = old_temp
        else:
            os.environ.pop('JOBLIB_TEMP_FOLDER', None)

        # Cleanup the temporary directory
        try:
            if temp_folder and os.path.exists(temp_folder):
                shutil.rmtree(temp_folder)
                logger.debug(f"Cleaned up temp directory: {temp_folder}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp folder {temp_folder}: {e}")
