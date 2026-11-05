"""Headless tile tasks. Errors always propagate to the owning job."""
import time

import numpy as np
import pandas as pd
import rasterio

from .raster import valid_mask, validate_alignment


class ProgressBar:
    def __init__(self, total, width=20, logger=None, update_frequency=None):
        if total < 0:
            raise ValueError("Progress total cannot be negative")
        self.total, self.width, self.logger = total, width, logger
        self.current = 0
        self.start_time = time.monotonic()
        self.update_frequency = update_frequency or max(1, total // 20)
        self.last_update = 0

    def update(self, current=None):
        self.current = min(self.total, self.current + 1 if current is None else current)
        if self.logger and self.current - self.last_update >= self.update_frequency:
            self.logger.info(f"Processing: {self.current}/{self.total}")
            self.last_update = self.current

    def finish(self):
        if self.current != self.total:
            raise RuntimeError("Cannot finish incomplete progress")
        if self.logger:
            self.logger.info(f"Completed {self.total} tiles in {time.monotonic() - self.start_time:.1f}s")


class _Task:
    """Compatible .run/.result interface, with no global progress or Qt dependency."""
    def setAutoDelete(self, value):
        pass

    @classmethod
    def init_progress(cls, total_workers, logger):
        # Legacy callers receive a local progress object; no shared class state.
        return ProgressBar(total_workers, logger=logger)

    def run(self):
        self.result = None
        self.error = None
        try:
            self.result = self.compute()
        except Exception as exc:
            self.error = exc
            raise
        return self.result


class PredictionWorker(_Task):
    def __init__(self, window, covariates, selected_features, model, scaler, log_scale=True):
        self.window, self.covariates, self.selected_features = window, covariates, selected_features
        self.model, self.scaler, self.log_scale = model, scaler, log_scale
        self.result, self.error, self.idx = None, None, None

    def compute(self):
        if len(self.selected_features) == 0:
            raise ValueError("No selected model features")
        arrays, reference, valid = {}, None, None
        paths = {f"{key}_avg": path for key, path in self.covariates.items()}
        for feature in self.selected_features:
            if feature not in paths:
                raise ValueError(f"Missing selected covariate: {feature}")
            with rasterio.open(paths[feature]) as src:
                if reference is None:
                    reference = src.profile
                validate_alignment(reference, src.profile, ("selected covariate", feature))
                arr = src.read(1, window=self.window, masked=True)
            arr_valid = valid_mask(arr)
            valid = arr_valid if valid is None else valid & arr_valid
            arrays[feature] = np.asarray(np.ma.getdata(arr)).ravel()
        output = np.full(valid.shape, np.nan, dtype=np.float64)
        if valid.any():
            frame = pd.DataFrame(arrays)[self.selected_features].loc[valid.ravel()]
            values = np.asarray(self.model.predict(self.scaler.transform(frame)), dtype=float)
            if self.log_scale:
                with np.errstate(over="raise", invalid="raise"):
                    values = np.expm1(values)
            values = np.maximum(values, 0)
            if not np.isfinite(values).all():
                raise ValueError("Model produced nonfinite predictions")
            output[valid] = values
        return output


class RasterWorker(_Task):
    def __init__(self, window, file_paths, process_params, idx=None):
        self.window, self.file_paths, self.process_params, self.idx = window, file_paths, process_params, idx
        self.result, self.error = None, None

    def compute(self):
        with rasterio.open(self.file_paths["mastergrid"]) as mst, rasterio.open(self.file_paths["target"]) as tgt:
            validate_alignment(mst.profile, tgt.profile)
            return self.process_params["func"](tgt.read(1, window=self.window, masked=True),
                                                mst.read(1, window=self.window, masked=True))


class RasterStackWorker(RasterWorker):
    def compute(self):
        with rasterio.open(self.file_paths["mastergrid"]) as mst:
            mask = mst.read(1, window=self.window, masked=True)
            results = []
            for key in self.process_params["keys"]:
                with rasterio.open(self.file_paths[f"target_{key}"]) as src:
                    validate_alignment(mst.profile, src.profile)
                    results.append(self.process_params["func"](src.read(1, window=self.window, masked=True), mask))
            return results


class NormalizationWorker(_Task):
    def __init__(self, window, mastergrid_path, norm_mapping, profile, idx=None):
        self.window, self.mastergrid_path, self.norm_mapping, self.profile, self.idx = window, mastergrid_path, norm_mapping, profile, idx
        self.result, self.error, self.valid_mappings = None, None, 0

    def compute(self):
        with rasterio.open(self.mastergrid_path) as src:
            array = src.read(1, window=self.window, masked=True)
        valid = valid_mask(array)
        data = np.ma.getdata(array)
        output = np.full(array.shape, self.profile["nodata"], dtype=self.profile["dtype"])
        for zone in np.unique(data[valid]):
            if zone in self.norm_mapping:
                value = self.norm_mapping[zone]
                if not np.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid normalization coefficient in zone {zone}")
                selected = valid & (data == zone)
                output[selected] = value
                self.valid_mappings += int(selected.sum())
        return output[np.newaxis]


class DasymetricWorker(_Task):
    def __init__(self, window, file_paths, profile, idx=None):
        self.window, self.file_paths, self.profile, self.idx = window, file_paths, profile, idx
        self.result, self.error = None, None

    def compute(self):
        with rasterio.open(self.file_paths["prediction"]) as pred, rasterio.open(self.file_paths["normalization"]) as norm:
            validate_alignment(pred.profile, norm.profile, ("prediction", "normalization"))
            prediction = pred.read(1, window=self.window, masked=True)
            factors = norm.read(1, window=self.window, masked=True)
        valid = valid_mask(prediction) & valid_mask(factors)
        # Zero coefficients represent zero-population zones, including missing predictions.
        zeros = valid_mask(factors) & (np.asarray(factors) == 0)
        output = np.full(prediction.shape, self.profile["nodata"], dtype=self.profile["dtype"])
        values = np.asarray(prediction, dtype=float)[valid] * np.asarray(factors, dtype=float)[valid]
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("Invalid population tile")
        output[valid] = values
        output[zeros] = 0
        if not np.isfinite(output).all():
            raise ValueError("Population output overflow")
        return output[np.newaxis]


class MaskWorker(_Task):
    def __init__(self, window, mst, msk, mask_value, nodata, idx=None):
        self.window, self.mst, self.msk, self.mask_value, self.nodata, self.idx = window, mst, msk, mask_value, nodata, idx
        self.result, self.error = None, None

    def compute(self):
        validate_alignment(self.mst.profile, self.msk.profile)
        master = self.mst.read(1, window=self.window, masked=True)
        mask = self.msk.read(1, window=self.window, masked=True)
        if self.nodata is None:
            raise ValueError("MaskWorker requires an explicit NoData; use remask_layer for masked outputs")
        output = np.ma.getdata(master).copy()
        invalid = ~valid_mask(master) | ~valid_mask(mask) | (np.asarray(mask) == self.mask_value)
        output[invalid] = self.nodata
        return output[np.newaxis]


class ScaledRasterWorker(_Task):
    def __init__(self, window, norm_raster_path, scale_factors, profile, idx=None, mastergrid_path=None):
        self.window, self.norm_raster_path, self.scale_factors, self.profile, self.idx = window, norm_raster_path, scale_factors, profile, idx
        self.mastergrid_path = mastergrid_path
        self.result, self.error = None, None

    def compute(self):
        if self.mastergrid_path is None or not isinstance(self.scale_factors, dict):
            raise ValueError("Scaling requires a mastergrid and a zone-to-factor dictionary")
        with rasterio.open(self.norm_raster_path) as norm, rasterio.open(self.mastergrid_path) as mst:
            validate_alignment(mst.profile, norm.profile)
            values = norm.read(1, window=self.window, masked=True)
            zones = mst.read(1, window=self.window, masked=True)
        valid = valid_mask(values) & valid_mask(zones)
        output = np.full(values.shape, self.profile["nodata"], dtype=self.profile["dtype"])
        for zone, factor in self.scale_factors.items():
            if not np.isfinite(factor) or factor < 0:
                raise ValueError(f"Invalid scale factor for zone {zone}")
            selected = valid & (np.asarray(zones) == zone)
            output[selected] = np.asarray(values)[selected] * factor
        if not np.isfinite(output).all():
            raise ValueError("Scaled output overflow")
        return output[np.newaxis]
