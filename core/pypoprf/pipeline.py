"""One headless calculation workflow shared by adapters and integration tests."""

from copy import copy
from pathlib import Path
import re
import tempfile
import time

from .algorithms.dasymetric import DasymetricMapper
from .algorithms.feature_extraction import FeatureExtractor
from .algorithms.model import Model
from .utils.raster import remask_layer
from .utils.runtime import check_cancelled


def execute_analysis(settings, progress=None):
    """Execute validated inputs inside a fresh run directory owned by the caller.

    This function never accesses Qt objects. The adapter owns status/manifests,
    creates a new run for every attempt, and only presents completed outputs.
    Input paths and the caller's settings are preserved; derived grids are local.
    """
    local = copy(settings)
    token = getattr(local, "cancellation_token", None)
    check_cancelled(token)
    output = Path(local.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    allowed_metadata = {"run_config.yaml", "manifest.json"}
    if any(path.is_symlink() or not path.is_file() or
           (path.name not in allowed_metadata and not re.fullmatch(r".+\.log(?:\.\d+)?", path.name))
           for path in output.iterdir()):
        raise ValueError("Analysis needs a fresh run directory; existing results are preserved")
    started = time.monotonic()

    def stage(percent, message):
        check_cancelled(token)
        if progress is not None:
            progress(percent, message)

    stage(0, "Validating run inputs")
    with tempfile.TemporaryDirectory(prefix="grids-", dir=output) as temporary:
        grids = Path(temporary)
        for attribute, value in (("mask", 1), ("constrain", 0)):
            source = getattr(local, attribute)
            if source:
                stage(10 if attribute == "mask" else 15, f"Applying {attribute}")
                result = remask_layer(
                    local.mastergrid, source, value,
                    outfile=str(grids / f"{attribute}.tif"),
                    by_block=local.by_block, block_size=local.block_size,
                    max_workers=local.max_workers, cancellation_token=token,
                )
                setattr(local, "mastergrid" if attribute == "mask" else "constrain", result)
        stage(20, "Extracting zonal features")
        features = FeatureExtractor(local).extract()
        stage(40, "Training and validating model")
        model = Model(local)
        model.train(features, log_scale=local.log_scale)
        stage(60, "Predicting population weights")
        prediction = model.predict()
        stage(75, "Allocating and checking census totals")
        mapper = DasymetricMapper(local)
        population = mapper.map(prediction)
        agesex = {}
        if local.agesex_data:
            stage(85, "Allocating and checking age-sex groups")
            agesex = mapper.map_agesex(prediction, local.agesex_data)
        stage(95, "Finishing verified outputs")
    check_cancelled(token)
    return {
        "prediction": Path(prediction), "population": population, "agesex": agesex,
        "cv_metrics": model.cv_metrics, "diagnostics": mapper.diagnostics,
        "elapsed_seconds": time.monotonic() - started,
    }
