from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from core.pypoprf.utils.raster import (get_raster_stats, aggregate_table, raster_stat, raster_stat_stack,
                                       get_windows, remask_layer, bounded_window_map, validate_census)
from core.pypoprf.utils.workers import PredictionWorker, DasymetricWorker, ProgressBar, ScaledRasterWorker


def write_raster(path, data, nodata=None, transform=None, mask=None):
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[np.newaxis]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(
            path, "w", driver="GTiff", width=data.shape[2], height=data.shape[1], count=data.shape[0],
            dtype=data.dtype, crs="EPSG:4326", transform=transform or from_origin(0, 10, 1, 1), nodata=nodata) as dst:
        dst.write(data)
        if mask is not None:
            dst.write_mask(np.asarray(mask, dtype="uint8") * 255)
    return str(path)


def test_singletons_and_nan_nodata():
    raw = get_raster_stats(np.array([[1., np.nan, 3.]]), np.array([[9, 9, 42]]), nodata=np.nan)
    result = aggregate_table(raw).set_index("id")
    assert result.loc[9, "count"] == 1
    assert result.loc[9, "avg"] == 1
    assert result.loc[42, "count"] == 1
    assert result.loc[42, "sum"] == 3


def test_stable_variance():
    result = aggregate_table(get_raster_stats(np.array([[1e12, 1e12 + 2]]), np.array([[1, 1]])))
    assert result["var"].iloc[0] == pytest.approx(1)


@pytest.mark.parametrize("by_block", [False, True])
def test_gdal_masks_and_empty_schema(tmp_path, by_block):
    master = write_raster(tmp_path / "grid.tif", [[1, 1, 2]], mask=[[1, 1, 0]])
    target = write_raster(tmp_path / "target.tif", [[4., 99., 20.]], mask=[[1, 0, 1]])
    result = raster_stat(target, master, by_block=by_block, block_size=(1, 1))
    assert result["id"].tolist() == [1]
    assert result["avg"].tolist() == [4]
    empty = write_raster(tmp_path / "empty.tif", [[-99., -99., -99.]], nodata=-99)
    result = raster_stat_stack({"empty": empty}, master, by_block=by_block)
    assert result["eligible_pixel_count"].tolist() == [2]
    assert result["empty_avg"].isna().all()
    stats = raster_stat(empty, master, by_block=by_block)
    assert stats.empty and {"id", "sum", "count", "avg"} <= set(stats.columns)


@pytest.mark.parametrize("block_size", [None, (1, 1), (256, 256), (2, 3)])
def test_windows_defaults_and_edges(block_size):
    windows = list(get_windows(SimpleNamespace(width=7, height=5), block_size))
    assert sum(window.width * window.height for window in windows) == 35
    assert all(window.col_off + window.width <= 7 and window.row_off + window.height <= 5 for window in windows)


@pytest.mark.parametrize("block_size", [(0, 1), (-1, 1), (1,), (1.2, 3), (True, 1), "12"])
def test_windows_reject_invalid_sizes(block_size):
    with pytest.raises(ValueError, match="positive integers"):
        get_windows(SimpleNamespace(width=7, height=5), block_size)


@pytest.mark.parametrize("by_block", [False, True])
def test_multiband_is_rejected_consistently(tmp_path, by_block):
    master = write_raster(tmp_path / "grid.tif", [[1, 1]])
    target = write_raster(tmp_path / "target.tif", [[[1, 2]], [[3, 4]]])
    with pytest.raises(ValueError, match="one band"):
        raster_stat(target, master, by_block=by_block)


@pytest.mark.parametrize("operation", ["stats", "remask"])
def test_misaligned_inputs_rejected_before_output(tmp_path, operation):
    master = write_raster(tmp_path / "grid.tif", [[1, 1]])
    target = write_raster(tmp_path / "target.tif", [[0, 1]], transform=from_origin(1, 10, 1, 1))
    output = tmp_path / "out.tif"
    with pytest.raises(ValueError, match="Transform mismatch"):
        if operation == "stats":
            raster_stat(target, master)
        else:
            remask_layer(master, target, 1, output)
    assert not output.exists()


def test_roundoff_alignment_tolerated(tmp_path):
    master = write_raster(tmp_path / "grid.tif", [[1, 1]])
    target = write_raster(tmp_path / "target.tif", [[4, 8]], transform=from_origin(1e-14, 10, 1, 1))
    assert raster_stat(target, master)["sum"].iloc[0] == 12


@pytest.mark.parametrize("by_block", [True, False])
@pytest.mark.parametrize("mask_value,expected", [(1, [True, False, False]), (0, [False, True, False])])
def test_remask_without_master_nodata_excludes_unknown_mask(tmp_path, by_block, mask_value, expected):
    master = write_raster(tmp_path / "grid.tif", np.array([[0, 8, 8]], dtype="uint16"))
    mask = write_raster(tmp_path / "mask.tif", np.array([[0, 1, 255]], dtype="uint8"), nodata=255)
    out = remask_layer(master, mask, mask_value, tmp_path / "out.tif", by_block=by_block, block_size=(1, 1))
    with rasterio.open(out) as src:
        assert (~np.ma.getmaskarray(src.read(1, masked=True))).ravel().tolist() == expected
        assert src.nodata is None


def test_remask_failure_preserves_existing_output(tmp_path):
    master = write_raster(tmp_path / "grid.tif", [[1, 1]])
    mask = write_raster(tmp_path / "mask.tif", [[0, 7]])
    out = tmp_path / "out.tif"
    out.write_bytes(b"prior-result")
    with pytest.raises(ValueError, match="0/1"):
        remask_layer(master, mask, 1, out, block_size=(1, 1))
    assert out.read_bytes() == b"prior-result"


def test_parallel_errors_are_propagated_and_submission_bounded():
    submitted = []
    def windows():
        for i in range(1000):
            submitted.append(i)
            yield i
    def fail(window):
        raise RuntimeError("broken tile")
    with pytest.raises(RuntimeError, match="broken tile"):
        list(bounded_window_map(fail, windows(), max_workers=2))
    assert len(submitted) <= 4


@pytest.mark.parametrize("ids,pops", [([1, 1], [1, 2]), ([1, np.nan], [1, 2]), ([1, 2], [1, np.inf]),
                                     ([1, 2], [1, -2]), ([1, 2], [1, "bad"])])
def test_invalid_census_is_rejected(ids, pops):
    with pytest.raises(ValueError):
        validate_census(pd.DataFrame({"zone": ids, "pop": pops}), "zone", "pop")


class IdentityScaler:
    def transform(self, frame):
        return frame.to_numpy()


class LogModel:
    def predict(self, values):
        return np.log1p(values[:, 0])


def test_prediction_selected_feature_mask_policy_and_inverse(tmp_path):
    selected = write_raster(tmp_path / "selected.tif", [[0., 4., -99., np.nan]], nodata=-99)
    worker = PredictionWorker(Window(0, 0, 4, 1), {"x": selected, "unused": "missing.tif"},
                              ["x_avg"], LogModel(), IdentityScaler())
    worker.run()
    np.testing.assert_allclose(worker.result[:, :2], [[0., 4.]])
    assert np.isnan(worker.result[:, 2:]).all()


def test_worker_exception_does_not_report_success():
    worker = PredictionWorker(Window(0, 0, 1, 1), {}, ["absent_avg"], LogModel(), IdentityScaler())
    with pytest.raises(ValueError, match="Missing selected"):
        worker.run()
    assert isinstance(worker.error, ValueError)
    assert worker.result is None


def test_dasymetric_worker_serial_idx_none_and_gdal_mask(tmp_path):
    pred = write_raster(tmp_path / "pred.tif", [[2., 3.]], mask=[[1, 0]])
    norm = write_raster(tmp_path / "norm.tif", [[4., 5.]])
    worker = DasymetricWorker(Window(0, 0, 2, 1), {"prediction": pred, "normalization": norm},
                              {"nodata": -99, "dtype": "float64"})
    worker.run()
    np.testing.assert_array_equal(worker.result, [[[8., -99.]]])


def test_progress_zero_total_and_incomplete():
    progress = ProgressBar(0)
    progress.update()
    progress.finish()
    with pytest.raises(RuntimeError, match="incomplete"):
        ProgressBar(2).finish()


def test_scaled_raster_uses_explicit_zone_ids(tmp_path):
    norm = write_raster(tmp_path / "norm.tif", [[0.5, 0.25]])
    grid = write_raster(tmp_path / "grid.tif", [[10, 80]])
    worker = ScaledRasterWorker(Window(0, 0, 2, 1), norm, {10: 100, 80: 20},
                               {"nodata": -99, "dtype": "float64"}, mastergrid_path=grid)
    worker.run()
    np.testing.assert_array_equal(worker.result, [[[50, 5]]])
    with pytest.raises(ValueError, match="mastergrid"):
        ScaledRasterWorker(Window(0, 0, 2, 1), norm, [1, 2], {"nodata": -99, "dtype": "float32"}).run()


def test_int64_minimum_zone_id_rejected_without_absolute_value_overflow(tmp_path):
    minimum = -(2 ** 63)
    zones = np.array([[minimum]], dtype="int64")
    with pytest.raises(ValueError, match="representable integers"):
        get_raster_stats(np.array([[1.]]), zones)
    with pytest.raises(ValueError, match="representable integers"):
        validate_census(pd.DataFrame({"zone": [minimum], "people": [1]}), "zone", "people")
    grid = write_raster(tmp_path / "minimum.tif", zones)
    with pytest.raises(ValueError, match="representable integers"):
        raster_stat_stack({}, grid)
