"""Headless, mask-aware raster operations with bounded private executors."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from numbers import Integral

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window

RAW_COLUMNS = ["id", "count", "sum", "sum2", "min", "max", "mean", "m2"]


def check_cancel(token):
    if token is not None:
        token.check()


def protect_output(target, input_paths):
    """Reject output paths that would replace any original input."""
    resolved = Path(target).resolve()
    if resolved in {Path(path).resolve() for path in input_paths if path}:
        raise ValueError(f"Output path conflicts with an input: {target}")


def valid_mask(array, nodata=None):
    """Respect masked reads, scalar NoData, NaN and infinities."""
    data = np.asarray(np.ma.getdata(array))
    valid = ~np.ma.getmaskarray(array) & np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    return valid


def validate_alignment(reference, target, labels=("mastergrid", "raster")):
    """Require one band and the same grid (tolerate roundoff, not pixel shifts)."""
    for profile, label in zip((reference, target), labels):
        if profile["count"] != 1:
            raise ValueError(f"{label} must have exactly one band")
        if profile["crs"] is None:
            raise ValueError(f"{label} must define a CRS")
    for key in ("crs", "width", "height"):
        if reference[key] != target[key]:
            raise ValueError(f"{key} mismatch between {labels[0]} and {labels[1]}")
    # Tolerance scales with resolution, never with the origin coordinate.
    transform = reference["transform"]
    resolution = max(np.hypot(transform.a, transform.d), np.hypot(transform.b, transform.e))
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("Reference grid has an invalid affine transform")
    tolerance = max(resolution * 1e-7, 1e-12)
    if not np.allclose(tuple(transform), tuple(target["transform"]), rtol=0, atol=tolerance):
        raise ValueError(f"Transform mismatch between {labels[0]} and {labels[1]}")


def validate_census(census, id_column, pop_column):
    """Unique finite numeric zone IDs and finite, nonnegative populations."""
    if id_column == pop_column:
        raise ValueError("Zone ID and population must use different columns")
    if census.columns.duplicated().any():
        raise ValueError("Duplicate census column names")
    for column in (id_column, pop_column):
        if column not in census:
            raise ValueError(f"Missing census column: {column}")
    if census.empty:
        raise ValueError("Census is empty")
    result = census.copy()
    for column in (id_column, pop_column):
        if pd.api.types.is_bool_dtype(result[column]) or result[column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"Census column {column} cannot contain boolean values")
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Census column {column} must be numeric") from exc
        if np.iscomplexobj(result[column]):
            raise ValueError(f"Census column {column} must be real-valued")
        if not np.isfinite(result[column].to_numpy(dtype=float)).all():
            raise ValueError(f"Census column {column} must contain finite values")
    if result[id_column].duplicated().any():
        raise ValueError("Duplicate census zone IDs")
    ids = result[id_column]
    if ((ids < -(2 ** 53)) | (ids > 2 ** 53)).any() or (ids.to_numpy(dtype=float) != np.floor(ids.to_numpy(dtype=float))).any():
        raise ValueError("Census zone IDs must be exactly representable integers")
    if (result[pop_column] < 0).any():
        raise ValueError(f"Negative population in {pop_column}")
    return result


def get_raster_stats(t, m, nodata=None, skip=None):
    if np.iscomplexobj(t) or np.iscomplexobj(m):
        raise ValueError("Raster values and zone IDs must be real-valued")
    if t.shape != m.shape:
        raise ValueError("Target and zone arrays have different shapes")
    valid = valid_mask(t, nodata) & valid_mask(m, skip)
    zones = np.asarray(np.ma.getdata(m))[valid]
    values = np.asarray(np.ma.getdata(t), dtype=np.float64)[valid]
    if not len(values):
        return pd.DataFrame(columns=RAW_COLUMNS)
    if ((zones < -(2 ** 53)) | (zones > 2 ** 53)).any() or (zones != np.floor(zones)).any():
        raise ValueError("Mastergrid zone IDs must be exactly representable integers")
    order = np.argsort(zones, kind="stable")
    zones, values = zones[order], values[order]
    ids, starts, counts = np.unique(zones, return_index=True, return_counts=True)
    sums = np.add.reduceat(values, starts)
    means = sums / counts
    deviations = values - np.repeat(means, counts)
    with np.errstate(over="raise", invalid="raise"):
        sums2 = np.add.reduceat(values * values, starts)
        m2 = np.add.reduceat(deviations * deviations, starts)
    return pd.DataFrame(dict(id=ids, count=counts, sum=sums, sum2=sums2,
                             min=np.minimum.reduceat(values, starts),
                             max=np.maximum.reduceat(values, starts), mean=means, m2=m2))


def _combine_raw(frames):
    """Merge tile moments using Chan's formula, keeping only one row per zone."""
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=RAW_COLUMNS)
    table = pd.concat(frames, ignore_index=True)
    if "mean" not in table:
        table["mean"] = table["sum"] / table["count"]
        table["m2"] = np.maximum(table["sum2"] - table["sum"] ** 2 / table["count"], 0)
    grouped = table.groupby("id", sort=True)
    combined = grouped.agg(count=("count", "sum"), sum=("sum", "sum"), sum2=("sum2", "sum"),
                           min=("min", "min"), max=("max", "max"))
    combined["mean"] = combined["sum"] / combined["count"]
    means = table["id"].map(combined["mean"])
    table["_moment"] = table["m2"] + table["count"] * (table["mean"] - means) ** 2
    combined["m2"] = table.groupby("id")["_moment"].sum()
    return combined.reset_index()[RAW_COLUMNS]


def aggregate_table(df, prefix="", min_count=1):
    prefix = f"{prefix}_" if prefix else ""
    columns = ["id"] + [prefix + name for name in ("count", "sum", "min", "max", "avg", "var", "std")]
    raw = _combine_raw([df])
    if raw.empty:
        return pd.DataFrame(columns=columns)
    raw = raw[raw["count"] >= min_count].copy()
    out = raw[["id", "count", "sum", "min", "max"]].copy()
    out["avg"] = raw["mean"]
    out["var"] = raw["m2"] / raw["count"]
    out["std"] = np.sqrt(out["var"])
    return out.rename(columns={column: prefix + column for column in out if column != "id"})


def get_windows(src, block_size=None):
    block_size = (256, 256) if block_size is None else block_size
    if (not isinstance(block_size, (tuple, list)) or len(block_size) != 2 or
            any(isinstance(x, bool) or not isinstance(x, Integral) or x <= 0 for x in block_size)):
        raise ValueError("block_size must contain two positive integers")
    return (Window(x, y, min(block_size[0], src.width - x), min(block_size[1], src.height - y))
            for y in range(0, src.height, block_size[1]) for x in range(0, src.width, block_size[0]))


def bounded_window_map(function, windows, max_workers=4, cancellation_token=None):
    """Yield ordered results; at most 2 * max_workers tiles live at once."""
    if isinstance(max_workers, bool) or not isinstance(max_workers, Integral) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    iterator = iter(windows)
    if max_workers == 1:
        for window in iterator:
            check_cancel(cancellation_token)
            yield window, function(window)
        return
    pending = deque()
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pypoprf") as executor:
        try:
            for _ in range(max_workers * 2):
                window = next(iterator, None)
                if window is None:
                    break
                check_cancel(cancellation_token)
                pending.append((window, executor.submit(function, window)))
            while pending:
                check_cancel(cancellation_token)
                window, future = pending.popleft()
                result = future.result()
                check_cancel(cancellation_token)
                yield window, result
                window = next(iterator, None)
                if window is not None:
                    pending.append((window, executor.submit(function, window)))
        finally:
            for _, future in pending:
                future.cancel()


def raster_stat(infile, mastergrid, by_block=True, max_workers=4, block_size=None, cancellation_token=None):
    """Windowed statistics; legacy False means serial tiles with bounded memory."""
    with rasterio.open(mastergrid) as mst, rasterio.open(infile) as target:
        validate_alignment(mst.profile, target.profile, ("mastergrid", str(infile)))
        windows = get_windows(mst, block_size)

    def process(window):
        check_cancel(cancellation_token)
        with rasterio.open(mastergrid) as mst, rasterio.open(infile) as target:
            return get_raster_stats(target.read(1, window=window, masked=True), mst.read(1, window=window, masked=True))

    combined = pd.DataFrame(columns=RAW_COLUMNS)
    for _, frame in bounded_window_map(process, windows, max_workers if by_block else 1, cancellation_token):
        combined = _combine_raw([combined, frame])
    return aggregate_table(combined)


def raster_stat_stack(infiles, mastergrid, by_block=True, max_workers=4, block_size=None, cancellation_token=None):
    # Target denominator comes only from the eligible mastergrid, independently of covariate order/coverage.
    with rasterio.open(mastergrid) as mst:
        validate_alignment(mst.profile, mst.profile)
        windows = get_windows(mst, block_size)
    def count_pixels(window):
        check_cancel(cancellation_token)
        with rasterio.open(mastergrid) as mst:
            zones = mst.read(1, window=window, masked=True)
        ids = np.ma.getdata(zones)[valid_mask(zones)]
        if ((ids < -(2 ** 53)) | (ids > 2 ** 53)).any() or (ids != np.floor(ids)).any():
            raise ValueError("Mastergrid zone IDs must be exactly representable integers")
        ids, counts = np.unique(ids, return_counts=True)
        return pd.DataFrame({"id": ids, "eligible_pixel_count": counts})
    out = pd.DataFrame(columns=["id", "eligible_pixel_count"])
    for _, counts in bounded_window_map(count_pixels, windows, max_workers if by_block else 1, cancellation_token):
        if not counts.empty:
            out = counts if out.empty else pd.concat([out, counts]).groupby("id", as_index=False)["eligible_pixel_count"].sum()
    for key, path in infiles.items():
        frame = raster_stat(path, mastergrid, by_block, max_workers, block_size, cancellation_token)
        frame = frame.rename(columns={column: f"{key}_{column}" for column in frame if column != "id"})
        out = out.merge(frame, on="id", how="left", validate="one_to_one")
    return out


def remask_layer(mastergrid, mask, mask_value, outfile="remasked_layer.tif", by_block=True,
                 max_workers=4, block_size=(512, 512), cancellation_token=None):
    """Exclude mask_value/unknown coverage; False processes tiles serially."""
    if Path(outfile).resolve() in {Path(mastergrid).resolve(), Path(mask).resolve()}:
        raise ValueError("Remasked output must differ from input paths")
    with rasterio.open(mastergrid) as mst, rasterio.open(mask) as msk:
        validate_alignment(mst.profile, msk.profile, ("mastergrid", "mask"))
        windows = get_windows(mst, block_size)
        profile = mst.profile.copy()
    def process(window):
        check_cancel(cancellation_token)
        with rasterio.open(mastergrid) as mst, rasterio.open(mask) as msk:
            m = mst.read(1, window=window, masked=True)
            n = msk.read(1, window=window, masked=True)
            categories = np.unique(np.asarray(n)[valid_mask(n)])
            if not np.isin(categories, [0, 1]).all():
                raise ValueError(f"Mask must contain only 0/1 categories, got {categories.tolist()}")
            valid = valid_mask(m) & valid_mask(n) & (np.asarray(n) != mask_value)
            data = np.ma.getdata(m).copy()
            data[~valid] = profile["nodata"] if profile["nodata"] is not None else 0
            return data, valid
    Path(outfile).parent.mkdir(parents=True, exist_ok=True)
    # Write temporary artifact and replace only after every tile succeeds.
    from .runtime import atomic_output
    with atomic_output(outfile, cancellation_token) as temporary:
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(temporary, "w", **profile) as dst:
            for window, (data, valid) in bounded_window_map(process, windows, max_workers if by_block else 1, cancellation_token):
                dst.write(data, 1, window=window)
                dst.write_mask(valid.astype("uint8") * 255, window=window)
    return str(outfile)


def parallel_raster_processing(windows, file_paths, process_params, max_workers, worker_type="single"):
    """Compatibility API: exceptions propagate, rather than omitting failed tiles."""
    from .workers import RasterWorker, RasterStackWorker
    if worker_type not in {"single", "stack"}:
        raise ValueError(f"Unknown worker type: {worker_type}")
    cls = RasterWorker if worker_type == "single" else RasterStackWorker
    def process(window):
        worker = cls(window, file_paths, process_params)
        worker.run()
        return worker.result
    return [result for _, result in bounded_window_map(process, windows, max_workers)]
