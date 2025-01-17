from typing import List, Any, Callable

from qgis.PyQt.QtCore import QThreadPool, QRunnable
from rasterio.windows import Window

from .logger import get_logger

logger = get_logger()


def parallel(windows: List[Window],
             process_func: Callable,
             max_workers: int) -> List[Any]:

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

    executor = QThreadPool.globalInstance()
    executor.setMaxThreadCount(max_workers)
    workers = []

    logger.debug(f"Processing {len(windows)} windows in QGIS environment")

    for window in windows:
        worker = RasterWorker(window, process_func)
        workers.append(worker)
        executor.start(worker)

    executor.waitForDone()
    results = [w.result for w in workers if w.result is not None]

    return results
