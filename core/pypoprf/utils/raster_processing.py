from typing import Dict, List, Tuple, Optional, Any, Callable
from .logger import get_logger

from tqdm import tqdm
from rasterio.windows import Window
logger = get_logger()

def progress_bar(iterable: Any,
                 show: bool,
                 total: int,
                 desc: str = "Processing") -> Any:
    """
    Create a progress bar for iteration.

    Args:
        iterable: Iterable object
        show: Whether to show progress bar
        total: Total number of items
        desc: Description for progress bar

    Returns:
        Progress bar wrapped iterable
    """
    if show:
        return tqdm(iterable, total=total, desc=desc)
    return iterable


def parallel(windows: List[Window],
                     process_func: Callable,
                     max_workers: int,
                     show_progress: bool = True,
                     desc: str = "Processing") -> List[Any]:
    """
    Generic parallel processing function that handles both QGIS and non-QGIS environments.

    Args:
        windows: List of windows to process
        process_func: Function to process each window
        max_workers: Maximum number of worker threads
        show_progress: Whether to show progress bar
        desc: Description for progress bar

    Returns:
        List of results from processing each window
    """
    try:
        from qgis.PyQt.QtCore import QThreadPool, QRunnable

        class RasterWorker(QRunnable):
            def __init__(self, window, process_func):
                super().__init__()
                self.window = window
                self.process_func = process_func
                self.result = None

            def run(self):
                try:
                    self.result = self.process_func(self.window)
                except Exception as e:
                    logger.error(f"Error in RasterWorker: {str(e)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

        qgis_executor = QThreadPool.globalInstance()
        qgis_executor.setMaxThreadCount(max_workers)
        workers = []

        logger.debug(f"Processing {len(windows)} windows in QGIS environment")

        for window in windows:
            worker = RasterWorker(window, process_func)
            workers.append(worker)
            qgis_executor.start(worker)

        qgis_executor.waitForDone()
        results = [w.result for w in workers if w.result is not None]

        return results

    except ImportError:
        # Non-QGIS environment
        from concurrent.futures import ThreadPoolExecutor

        logger.debug(f"Processing {len(windows)} windows in non-QGIS environment")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(progress_bar(
                executor.map(process_func, windows),
                show_progress,
                len(windows),
                desc=desc
            ))

        return results