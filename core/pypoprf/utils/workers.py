import threading
import time
import traceback

import numpy as np
import pandas as pd
import rasterio
from qgis.PyQt.QtCore import QRunnable

from ..utils.logger import get_logger

logger = get_logger()


class ProgressBar:
    def __init__(self, total, width=50, logger=None, update_frequency=None):
        self.total = total
        self.width = width
        self.current = 0
        self.logger = logger
        self.start_time = time.time()

        if update_frequency is None:
            self.update_frequency = max(1, total // 20)
        else:
            self.update_frequency = update_frequency

        logger.debug(f"Progress bar initialized: total={total}, update_frequency={self.update_frequency}")

        self.last_update = 0
        self._logged_percentage = -1

    def _format_time(self, seconds: float) -> str:
        """Convert seconds to minutes and seconds format."""
        minutes = int(seconds // 60)
        seconds = seconds % 60
        if minutes > 0:
            return f"{minutes}m {seconds:.0f}s"
        return f"{seconds:.0f}s"

    def update(self, current=None):
        if current is not None:
            self.current = current
        else:
            self.current += 1

        percentage = (self.current / self.total)
        elapsed_time = time.time() - self.start_time

        if self.current - self.last_update >= self.update_frequency:
            filled = int(self.width * percentage)
            bar = '█' * filled + '░' * (self.width - filled)

            if percentage != self._logged_percentage:
                progress_text = (
                    f'<span style="color: #2355a6">Processing: |{bar}| {percentage:.0%} ({self.current}/{self.total}) '
                    f'<span style="color: #050500">Elapsed time: {self._format_time(elapsed_time)}</span> '
                )
                if self.logger:
                    self.logger.info(f'<span style="font-family: monospace;">{progress_text}</span>')
                self._logged_percentage = percentage

            self.last_update = self.current

    def finish(self):
        if self.logger:
            filled = '█' * self.width
            total_time = time.time() - self.start_time
            self.logger.info(
                f'<span style="font-family: monospace; color: #4CAF50">'
                f"Completed: |{filled}| 100% ({self.total}/{self.total}) "
                f"Total time: {self._format_time(total_time)}"
                f'</span>'
            )


class PredictionWorker(QRunnable):
    completed_workers = 0
    progress_bar = None
    lock = threading.Lock()

    def __init__(self, window, covariates, selected_features, model, scaler):
        super().__init__()
        self.window = window
        self.covariates = covariates
        self.selected_features = selected_features
        self.model = model
        self.scaler = scaler
        self.result = None
        self.idx = None

    @classmethod
    def init_progress(cls, total_workers, logger):
        cls.completed_workers = 0
        cls.progress_bar = ProgressBar(total_workers, logger=logger)

    def run(self):
        try:
            df = pd.DataFrame()
            for k, path in self.covariates.items():
                with rasterio.open(path, 'r') as src_file:
                    arr = src_file.read(window=self.window)[0, :, :]
                    df[k + '_avg'] = arr.flatten()

            df = df[self.selected_features]
            sx = self.scaler.transform(df)
            yp = self.model.predict(sx)
            self.result = yp.reshape(arr.shape)

            with self.lock:
                self.__class__.completed_workers += 1
                if self.__class__.progress_bar:
                    self.__class__.progress_bar.update(self.__class__.completed_workers)

        except Exception as e:
            logger.error(f"Error in worker {self.idx}: {str(e)}")
            logger.error(traceback.format_exc())


class RasterWorker(QRunnable):
    completed_workers = 0
    progress_bar = None
    lock = threading.Lock()
    total_process_time = 0
    total_workers = 0

    def __init__(self, window, file_paths, process_params, idx=None):
        super().__init__()
        self.window = window
        self.file_paths = file_paths
        self.process_params = process_params
        self.result = None
        self.idx = idx

    @classmethod
    def init_progress(cls, total_workers, logger):
        cls.completed_workers = 0
        cls.progress_bar = ProgressBar(total_workers, logger=logger)
        cls.total_process_time = 0
        cls.total_workers = 0

    def run(self):
        try:
            with rasterio.open(self.file_paths['mastergrid'], 'r') as mst, \
                    rasterio.open(self.file_paths['target'], 'r') as tgt:

                m = mst.read(window=self.window)
                t = tgt.read(window=self.window)

                nodata = tgt.nodata
                skip = mst.nodata

            self.result = self.process_params['func'](t, m, nodata=nodata, skip=skip)

            with self.lock:
                self.__class__.completed_workers += 1
                if self.__class__.progress_bar:
                    self.__class__.progress_bar.update(self.__class__.completed_workers)

        except Exception as e:
            logger.error(f"Error in worker {self.idx}: {str(e)}")
            logger.error(traceback.format_exc())


class RasterStackWorker(QRunnable):
    completed_workers = 0
    progress_bar = None
    lock = threading.Lock()
    total_process_time = 0
    total_workers = 0

    def __init__(self, window, file_paths, process_params, idx=None):
        super().__init__()
        self.window = window
        self.file_paths = file_paths
        self.process_params = process_params
        self.idx = idx
        self.result = None

    @classmethod
    def init_progress(cls, total_workers, logger):
        cls.completed_workers = 0
        cls.progress_bar = ProgressBar(total_workers, logger=logger)
        cls.total_process_time = 0
        cls.total_workers = 0

    def run(self):
        try:
            with rasterio.open(self.file_paths['mastergrid']) as mst:
                m = mst.read(1, window=self.window)

                t = []
                for key in self.process_params['keys']:
                    with rasterio.open(self.file_paths[f'target_{key}']) as src:
                        t.append(src.read(1, window=self.window))

            results = [
                self.process_params['func'](
                    ta, m,
                    nodata=self.process_params['nodata_values'][key],
                    skip=self.process_params['skip']
                )
                for ta, key in zip(t, self.process_params['keys'])
            ]
            self.result = results

            with self.lock:
                self.__class__.completed_workers += 1
                if self.__class__.progress_bar:
                    self.__class__.progress_bar.update(self.__class__.completed_workers)

        except Exception as e:
            logger.error(f"Error in worker {self.idx}: {str(e)}")
            logger.error(traceback.format_exc())


class NormalizationWorker(QRunnable):
    completed_workers = 0
    progress_bar = None
    lock = threading.Lock()
    total_process_time = 0
    total_workers = 0

    def __init__(self, window, mastergrid_path, norm_mapping, profile, idx=None):
        super().__init__()
        self.window = window
        self.mastergrid_path = mastergrid_path
        self.norm_mapping = norm_mapping
        self.profile = profile
        self.idx = idx
        self.result = None
        self.valid_mappings = 0

    @classmethod
    def init_progress(cls, total_workers, logger):
        cls.completed_workers = 0
        cls.progress_bar = ProgressBar(total_workers, logger=logger)
        cls.total_process_time = 0
        cls.total_workers = 0


    def run(self):
        try:
            with rasterio.open(self.mastergrid_path, 'r') as mst:
                mst_data = mst.read(1, window=self.window)
                nodata = mst.nodata



            output = np.full_like(mst_data, self.profile['nodata'], dtype='float32')

            valid_data = mst_data != nodata
            unique_zones = np.unique(mst_data[valid_data])

            for zone_id in unique_zones:
                if zone_id in self.norm_mapping:
                    mask = mst_data == zone_id
                    output[mask] = self.norm_mapping[zone_id]
                    self.valid_mappings += mask.sum()

            output[~valid_data] = self.profile['nodata']

            self.result = output[np.newaxis, :, :]

            with self.lock:
                self.__class__.completed_workers += 1
                if self.__class__.progress_bar:
                    self.__class__.progress_bar.update(self.__class__.completed_workers)

        except Exception as e:
            logger.error(f"Error in worker {self.idx}: {str(e)}")
            logger.error(traceback.format_exc())


class DasymetricWorker(QRunnable):
    completed_workers = 0
    progress_bar = None
    lock = threading.Lock()
    total_process_time = 0
    total_workers = 0

    def __init__(self, window, file_paths, profile, idx=None):
        super().__init__()
        self.window = window
        self.file_paths = file_paths
        self.profile = profile
        self.idx = idx
        self.result = None

    @classmethod
    def init_progress(cls, total_workers, logger):
        cls.completed_workers = 0
        cls.progress_bar = ProgressBar(total_workers, logger=logger)
        cls.total_process_time = 0
        cls.total_workers = 0


    def run(self):
        try:
            with rasterio.open(self.file_paths['prediction']) as pred, \
                    rasterio.open(self.file_paths['normalization']) as norm:

                pred_data = pred.read(1, window=self.window)
                norm_data = norm.read(1, window=self.window)
                pred_nodata = pred.nodata

            population = np.round(pred_data * norm_data).astype('int32')

            nodata_mask = (pred_data == pred_nodata) | (norm_data == self.profile['nodata'])
            population[nodata_mask] = self.profile['nodata']

            self.result = population[np.newaxis, :, :]

            with self.lock:
                self.__class__.completed_workers += 1
                if self.__class__.progress_bar:
                    self.__class__.progress_bar.update(self.__class__.completed_workers)

        except Exception as e:
            logger.error(f"Error in worker {self.idx}: {str(e)}")
            logger.error(traceback.format_exc())