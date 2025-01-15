# src/pypoprf/utils/raster.py
import numpy as np
import pandas as pd
import rasterio
import threading
from typing import Dict, List, Tuple, Optional, Any, Callable

from .logger import get_logger
from .raster_processing import parallel
from ..utils.matplotlib_utils import with_non_interactive_matplotlib

logger = get_logger()

def raster_compare(p1: Dict,
                   p2: Dict) -> List[str]:
    """
    Compare two raster profiles for compatibility.

    Args:
        p1: First raster profile
        p2: Second raster profile

    Returns:
        List of required processing steps
    """
    process = {
        'crs': 'reprojection',
        'width': 'clipping',
        'height': 'clipping'
    }

    required = []
    for p in ['crs', 'width', 'height']:
        if p1[p] != p2[p]:
            logger.info(f'Rasters have different [{p}]')
            logger.info(f'Required process: {process[p]}')
            required.append(process[p])

    if p1['transform'][0] != p2['transform'][0]:
        logger.info('Rasters have different resolutions')
        logger.info('Required process: resampling')

        required.append('resampling')

    return required


def get_raster_stats(t: np.ndarray,
                     m: np.ndarray,
                     nodata: Optional[float] = None,
                     skip: Optional[float] = None) -> pd.DataFrame:
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
        d = pd.DataFrame({
            'id': i,
            'count': count,
            'sum': np.nansum(tm),
            'sum2': np.nansum(tm * tm),
            'min': np.nanmin(tm),
            'max': np.nanmax(tm)
        }, index=[0])

        df_list.append(d)

    if df_list:
        return pd.concat(df_list, ignore_index=True)

    return pd.DataFrame()


def aggregate_table(df: pd.DataFrame, prefix: str = '', min_count: int = 1) -> pd.DataFrame:
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
    ag1 = df[['id', 'count', 'sum', 'sum2']].groupby('id').sum().reset_index()
    ag2 = df[['id', 'min']].groupby('id').min().reset_index()
    ag3 = df[['id', 'max']].groupby('id').max().reset_index()

    # Mask for valid values
    where = ag1['count'].values > 0

    # Calculate mean with safe division
    avg = np.divide(ag1['sum'].values,
                    ag1['count'].values,
                    out=np.zeros_like(ag1['sum'].values, dtype=float),
                    where=where)

    # Calculate variance with checks
    var_raw = np.divide(ag1['sum2'].values,
                        ag1['count'].values,
                        out=np.zeros_like(ag1['sum2'].values, dtype=float),
                        where=where) - avg * avg
    var = np.maximum(var_raw, 0)  # Replace negative values with 0

    # Safe standard deviation calculation
    std = np.sqrt(var, where=var >= 0)

    # Handle prefix
    if prefix:
        prefix = f"{prefix}_"

    # Create output DataFrame
    out = ag2[['id']].copy()
    out[prefix + 'count'] = ag1['count'].values
    out[prefix + 'sum'] = ag1['sum'].values
    out[prefix + 'min'] = ag2['min'].values
    out[prefix + 'max'] = ag3['max'].values
    out[prefix + 'avg'] = avg
    out[prefix + 'var'] = var
    out[prefix + 'std'] = std

    # Filter by minimum count
    out = out[out[prefix + 'count'] > min_count]

    # Replace NaN with 0 in statistics columns
    stats_cols = [prefix + x for x in ['avg', 'var', 'std']]
    out[stats_cols] = out[stats_cols].fillna(0)

    return out


def get_windows(src, 
                block_size: Optional[Tuple[int, int]] = (512, 512)
    ):
    """
    Get block/window tiles for reading/writing raster

    Args:
        src: rasterio.open
        block_size: tuple defining block/window size

    Returns:
        List of windows

    """

    x0 = np.arange(0, src.width, block_size[0])
    y0 = np.arange(0, src.height, block_size[1])
    grid = np.meshgrid(x0, y0)
    windows = [rasterio.windows.Window(a, b, block_size[0], block_size[1])
                for (a, b) in zip(grid[0].flatten(), grid[1].flatten())]

    return windows


def remask_layer(mastergrid: str,
                 mask: str,
                 mask_value: int | float,
                 outfile: Optional[str] = 'remasked_layer.tif',
                 by_block: bool = True,
                 max_workers: int = 4,
                 block_size: Optional[Tuple[int, int]] = None,
                 show_progress: bool = False
    ):

    """
    Implement additional masking to the mastergrid, e.g., use water mask.

    Args:
        mastergrid: Path to mastergrid file
        mask: Path to mask file
        mask_value: value to be masked out
        outfile: Path to the output file (remasked mastergrid)

    Returns:
        nothing

    Raises:
        FileNotFoundError: If input files don't exist
        RuntimeError: If processing fails
    """
    try:
        with rasterio.open(mastergrid, 'r') as mst, rasterio.open(mask, 'r') as msk:
            nodata = mst.nodata
            dst = rasterio.open(outfile, 'w', **mst.profile)
            reading_lock = threading.Lock()
            writing_lock = threading.Lock()

            def process(window):
                with reading_lock:
                    m = mst.read(window=window)
                    n = msk.read(window=window)

                m[n == mask_value] = nodata
                with writing_lock:
                    dst.write(m, 1, window=window)

            if by_block:
                windows = get_windows(mst, block_size if block_size else (512, 512))
                parallel(
                    windows=windows,
                    process_func=process,
                    max_workers=max_workers,
                    show_progress=show_progress,
                    desc="Remasking mastergrid"
                )

            else:
                m = mst.read(1)
                n = msk.read(1)
                m[n == mask_value] = nodata
                dst.write(m, 1)

            dst.close()
        
    except Exception as e:
        raise RuntimeError(f"Error processing rasters: {str(e)}")


@with_non_interactive_matplotlib
def raster_stat(infile: str,
                mastergrid: str,
                by_block: bool = True,
                max_workers: int = 4,
                block_size: Optional[Tuple[int, int]] = None,
                show_progress: bool = True) -> pd.DataFrame:
    """
    Calculate zonal statistics for a raster.

    Args:
        infile: Input raster path
        mastergrid: Mastergrid raster path
        by_block: Whether to process by blocks
        max_workers: Number of worker processes
        block_size: Size of processing blocks
        show_progress: Whether to show progress bar

    Returns:
        DataFrame with zonal statistics

    Raises:
        FileNotFoundError: If input files don't exist
        RuntimeError: If processing fails
    """
    import time
    t0 = time.time()

    try:
        with rasterio.open(mastergrid, 'r') as mst, rasterio.open(infile, 'r') as tgt:
            nodata = tgt.nodata
            skip = mst.nodata
            lock = threading.Lock()

            def process(window):
                with lock:
                    m = mst.read(window=window)
                    t = tgt.read(window=window)
                d = get_raster_stats(t, m, nodata=nodata, skip=skip)
                return d

            if by_block:
                windows = get_windows(mst, block_size if block_size else (512, 512))

                df = parallel(
                    windows=windows,
                    process_func=process,
                    max_workers=max_workers,
                    show_progress=show_progress,
                    desc="Dasymetric raster statistics"
                )

                res = pd.concat(df, ignore_index=True)

            else:
                m = mst.read(1)
                t = tgt.read(1)
                res = get_raster_stats(t, m, nodata=nodata, skip=skip)

    except Exception as e:
        raise RuntimeError(f"Error processing rasters: {str(e)}")

    out_df = aggregate_table(res)
    duration = time.time() - t0
    logger.info(f'Raster statistics is finished in {duration:.2f} sec')


    return out_df


@with_non_interactive_matplotlib
def raster_stat_stack(infiles: Dict[str, str],
                      mastergrid: str,
                      by_block: bool = True,
                      max_workers: int = 4,
                      block_size: Optional[Tuple[int, int]] = None,
                      show_progress: bool = True) -> pd.DataFrame:
    """
    Calculate zonal statistics for multiple rasters.

    Args:
        infiles: Dictionary of raster names and paths
        mastergrid: Master grid raster path
        by_block: Whether to process by blocks
        max_workers: Number of worker processes
        block_size: Size of processing blocks
        show_progress: Whether to show progress bar

    Returns:
        DataFrame with combined statistics

    Raises:
        RuntimeError: If processing fails
        FileNotFoundError: If input files don't exist
    """
    import time
    t0 = time.time()

    try:
        with rasterio.open(mastergrid, 'r') as mst:
            targets = []
            try:
                targets = [rasterio.open(path, 'r') for path in infiles.values()]
                nodata = [t.nodata for t in targets]
                skip = mst.nodata
                lock = threading.Lock()

                def process(window):
                    with lock:
                        m = mst.read(window=window)
                        t = [tgt.read(window=window) for tgt in targets]
                    d = [get_raster_stats(ta, m, nodata=na, skip=skip)
                         for (ta, na) in zip(t, nodata)]
                    return d

                if by_block:
                    windows = get_windows(mst, block_size if block_size else (512, 512))

                    df = parallel(
                        windows=windows,
                        process_func=process,
                        max_workers=max_workers,
                        show_progress=show_progress,
                        desc="Feature Extraction"
                    )
                else:
                    m = mst.read(1)
                    df = [get_raster_stats(t.read(1), m, nodata=na, skip=skip)
                          for t, na in zip(targets, nodata)]

                # Create output DataFrame
                out_df = pd.DataFrame({'id': []})
                for i, key in enumerate(infiles):
                    d = [a[i] for a in df]
                    res = pd.concat(d, ignore_index=True)
                    out = aggregate_table(res, prefix=key)
                    out_df = pd.merge(out, out_df, on='id', how='outer')

            finally:
                # Close all opened rasters
                for t in targets:
                    try:
                        t.close()
                    except Exception:
                        pass  # Ignore errors on closing

    except Exception as e:
        raise RuntimeError(f"Error processing raster stack: {str(e)}")

    duration = time.time() - t0
    logger.info(f'Raster statistics is finished in {duration:.2f} sec')

    return out_df
