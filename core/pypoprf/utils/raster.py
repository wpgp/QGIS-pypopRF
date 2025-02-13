from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd
import rasterio
from qgis.PyQt.QtCore import QThreadPool
from rasterio.windows import Window

from .logger import get_logger
from .workers import RasterWorker, RasterStackWorker, MaskWorker

logger = get_logger()


def get_raster_stats(
    t: np.ndarray,
    m: np.ndarray,
    nodata: Optional[float] = None,
    skip: Optional[float] = None,
) -> pd.DataFrame:
    """
    Calculate statistics for a raster within mask regions.

    Args:
        t: Target raster data
        m: Mask raster data
        nodata: No data value
        skip: Value to skip in mask

    Returns:
        DataFrame with statistics
    """
    ids = np.unique(m)
    df_list = []

    for i in ids:
        if i == skip:
            continue

        select = np.logical_and(t != nodata, m == i)
        count = np.sum(select)
        if count < 1:
            continue

        tm = np.where(select, t, np.nan)
        d = pd.DataFrame(
            {
                "id": i,
                "count": count,
                "sum": np.nansum(tm),
                "sum2": np.nansum(tm * tm),
                "min": np.nanmin(tm),
                "max": np.nanmax(tm),
            },
            index=[0],
        )

        df_list.append(d)

    if df_list:
        return pd.concat(df_list, ignore_index=True)

    return pd.DataFrame()


def aggregate_table(df: pd.DataFrame, prefix: str = "", min_count: int = 1) -> pd.DataFrame:
    """
    Aggregate statistics from raster data.

    Args:
        df: Input DataFrame with statistics
        prefix: Prefix for output column names
        min_count: Minimum count threshold for valid data

    Returns:
        DataFrame with aggregated statistics
    """
    # Basic validation
    if df.empty:
        return pd.DataFrame()

    # Group by ID and aggregate
    ag1 = df[["id", "count", "sum", "sum2"]].groupby("id").sum().reset_index()
    ag2 = df[["id", "min"]].groupby("id").min().reset_index()
    ag3 = df[["id", "max"]].groupby("id").max().reset_index()

    # Mask for valid values
    where = ag1["count"].values > 0

    # Calculate mean with safe division
    avg = np.divide(
        ag1["sum"].values,
        ag1["count"].values,
        out=np.zeros_like(ag1["sum"].values, dtype=float),
        where=where,
    )

    # Calculate variance with checks
    var_raw = (
        np.divide(
            ag1["sum2"].values,
            ag1["count"].values,
            out=np.zeros_like(ag1["sum2"].values, dtype=float),
            where=where,
        )
        - avg * avg
    )
    var = np.maximum(var_raw, 0)  # Replace negative values with 0

    # Safe standard deviation calculation
    std = np.sqrt(var, where=var >= 0)

    # Handle prefix
    if prefix:
        prefix = f"{prefix}_"

    # Create output DataFrame
    out = ag2[["id"]].copy()
    out[prefix + "count"] = ag1["count"].values
    out[prefix + "sum"] = ag1["sum"].values
    out[prefix + "min"] = ag2["min"].values
    out[prefix + "max"] = ag3["max"].values
    out[prefix + "avg"] = avg
    out[prefix + "var"] = var
    out[prefix + "std"] = std

    # Filter by minimum count
    out = out[out[prefix + "count"] > min_count]

    # Replace NaN with 0 in statistics columns
    stats_cols = [prefix + x for x in ["avg", "var", "std"]]
    out[stats_cols] = out[stats_cols].fillna(0)

    return out


def get_windows(src, block_size: Optional[Tuple[int, int]] = (256, 256)):
    """
    Get block/window tiles for reading/writing raster, ensuring windows do not exceed raster dimensions.

    Args:
        src: rasterio.open
        block_size: tuple defining block/window size

    Returns:
        List of windows
    """
    windows = []
    for y in range(0, src.height, block_size[1]):
        for x in range(0, src.width, block_size[0]):
            width = min(block_size[0], src.width - x)
            height = min(block_size[1], src.height - y)
            windows.append(rasterio.windows.Window(x, y, width, height))
    return windows


def remask_layer(
    mastergrid: str,
    mask: str,
    mask_value: int,
    outfile: Optional[str] = "remasked_layer.tif",
    by_block: bool = True,
    max_workers: int = 4,
    block_size: Optional[Tuple[int, int]] = (512, 512),
) -> str:
    """
    Implement additional masking to the mastergrid.

    Args:
        mastergrid: Path to mastergrid file
        mask: Path to mask file
        mask_value: value to be masked out
        outfile: Path to the output file
        by_block: Whether to process by blocks
        max_workers: Number of worker processes
        block_size: Size of processing blocks

    Returns:
        str: Path to created masked file
    """
    with rasterio.open(mastergrid, "r") as mst, rasterio.open(mask, "r") as msk:
        nodata = mst.nodata
        dst = rasterio.open(outfile, "w", **mst.profile)

        if by_block:
            windows = get_windows(mst, block_size)
            executor = QThreadPool.globalInstance()
            executor.setMaxThreadCount(max_workers)
            workers = []

            MaskWorker.init_progress(len(windows), logger)

            for i, window in enumerate(windows):
                worker = MaskWorker(
                    window=window,
                    mst=mst,
                    msk=msk,
                    mask_value=mask_value,
                    nodata=nodata,
                    idx=i,
                )
                worker.setAutoDelete(False)
                workers.append(worker)
                executor.start(worker)

            executor.waitForDone()

            for i, worker in enumerate(workers):
                if worker.result is not None:
                    dst.write(worker.result, window=windows[i])

        else:
            m = mst.read()
            n = msk.read()
            m[n == mask_value] = nodata
            dst.write(m)

        dst.close()
        return outfile


def raster_stat(
    infile: str,
    mastergrid: str,
    by_block: bool = True,
    max_workers: int = 4,
    block_size: Optional[Tuple[int, int]] = None,
) -> pd.DataFrame:
    """
    Calculate zonal statistics for a raster.

    Args:
        infile: Input raster path
        mastergrid: Mastergrid raster path
        by_block: Whether to process by blocks
        max_workers: Number of worker processes
        block_size: Size of processing blocks

    Returns:
        DataFrame with zonal statistics

    """
    with rasterio.open(mastergrid, "r") as mst, rasterio.open(infile, "r") as tgt:

        if by_block:
            windows = get_windows(mst, block_size)

            file_paths = {"mastergrid": mastergrid, "target": infile}

            process_params = {"func": get_raster_stats}

            df = parallel_raster_processing(
                windows=windows,
                file_paths=file_paths,
                process_params=process_params,
                max_workers=max_workers,
                worker_type="single",
            )

            res = pd.concat(df, ignore_index=True)
        else:
            with rasterio.open(infile, "r") as tgt:
                m = mst.read(1)
                t = tgt.read(1)
                res = get_raster_stats(t, m, nodata=tgt.nodata, skip=mst.nodata)

    out_df = aggregate_table(res)

    return out_df


def raster_stat_stack(
    infiles: Dict[str, str],
    mastergrid: str,
    by_block: bool = True,
    max_workers: int = 4,
    block_size: Optional[Tuple[int, int]] = None,
) -> pd.DataFrame:
    """
    Calculate zonal statistics for multiple rasters.

    Args:
        infiles: Dictionary of raster names and paths
        mastergrid: Master grid raster path
        by_block: Whether to process by blocks
        max_workers: Number of worker processes
        block_size: Size of processing blocks

    Returns:
        DataFrame with combined statistics
    """
    file_paths = {
        "mastergrid": mastergrid,
        **{f"target_{k}": v for k, v in infiles.items()},
    }

    nodata_values = {}
    with rasterio.open(mastergrid, "r") as mst:
        skip = mst.nodata

        for key, path in infiles.items():
            with rasterio.open(path, "r") as src:
                nodata_values[key] = src.nodata

        if by_block:
            windows = get_windows(mst, block_size)
            process_params = {
                "func": get_raster_stats,
                "skip": skip,
                "nodata_values": nodata_values,
                "keys": list(infiles.keys()),
            }

            df = parallel_raster_processing(
                windows=windows,
                file_paths=file_paths,
                process_params=process_params,
                max_workers=max_workers,
                worker_type="stack",
            )
        else:
            m = mst.read(1)
            results = []
            for key, path in infiles.items():
                with rasterio.open(path, "r") as src:
                    t = src.read(1)
                    results.append(
                        get_raster_stats(t, m, nodata=nodata_values[key], skip=skip)
                    )
            df = [results]

    out_df = pd.DataFrame({"id": []})
    for i, key in enumerate(infiles):
        d = [a[i] for a in df if a is not None]
        res = pd.concat(d, ignore_index=True)
        out = aggregate_table(res, prefix=key)
        out_df = pd.merge(out, out_df, on="id", how="outer")

    return out_df


def parallel_raster_processing(
    windows: List[Window],
    file_paths: Dict[str, str],
    process_params: Dict[str, Any],
    max_workers: int,
    worker_type: str = "single",
) -> List[Any]:
    """
    Execute raster processing in parallel using QGIS thread pool.

    Args:
        windows: List of raster windows to process
        file_paths: Dictionary with paths to input files
        process_params: Dictionary with processing parameters and functions
        max_workers: Maximum number of worker threads
        worker_type: Type of worker to use ('single' or 'stack')
    """
    executor = QThreadPool.globalInstance()
    executor.setMaxThreadCount(max_workers)
    workers = []

    logger.debug(f"Processing {len(windows)} windows in QGIS environment")
    logger.debug(f"Starting parallel processing with {max_workers} workers")
    logger.debug(f"Using worker type: {worker_type}")

    WorkerClass = RasterWorker if worker_type == "single" else RasterStackWorker
    WorkerClass.init_progress(len(windows), logger)
    try:
        for i, window in enumerate(windows):
            worker = WorkerClass(
                window=window,
                file_paths=file_paths,
                process_params=process_params,
                idx=i,
            )
            worker.setAutoDelete(False)
            workers.append(worker)
            executor.start(worker)

        executor.waitForDone()
        WorkerClass.progress_bar.finish()

        results = [w.result for w in workers if w.result is not None]
        return results
    finally:
        workers.clear()
