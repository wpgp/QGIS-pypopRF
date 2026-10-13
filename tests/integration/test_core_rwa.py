"""Real bundled case-study regression; skips only if that dataset is absent."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio

from core.pypoprf.config.settings import Settings
from core.pypoprf.algorithms.feature_extraction import FeatureExtractor
from core.pypoprf.algorithms.dasymetric import DasymetricMapper
from core.pypoprf.utils.raster import get_windows, raster_stat


def test_rwanda_feature_extraction_and_416_zone_conservation(tmp_path):
    data = Path(__file__).resolve().parents[2] / "case_study" / "RWA"
    if not (data / "rwa_mastergrid.tif").is_file():
        pytest.skip("Bundled Rwanda case-study rasters are not available")
    covariates = {path.stem: path.name for path in data.glob("*.tif") if path.name != "rwa_mastergrid.tif"}
    settings = Settings(work_dir=str(tmp_path), data_dir=str(data), mastergrid="rwa_mastergrid.tif",
                        covariates=covariates, census_data="RWA_2026.csv", census_pop_column="pop",
                        census_id_column="id", max_workers=2)
    features = FeatureExtractor(settings).extract()
    assert len(features) == 416
    assert np.isfinite(features["dens"]).all()
    assert (features["eligible_pixel_count"] > 0).all()
    expected = pd.read_csv(data / "RWA_2026.csv").set_index("id")["pop"]
    np.testing.assert_allclose(features["pop"].sum(), expected.sum(), rtol=1e-12)
    prediction = tmp_path / "uniform_weights.tif"
    # Geometry comes from the real grid; weights are deliberately independent of RF.
    with rasterio.open(settings.mastergrid) as master:
        profile = master.profile.copy()
        profile.update(dtype="float32", nodata=-99, count=1)
        with rasterio.open(prediction, "w", **profile) as dst:
            for window in get_windows(master, settings.block_size):
                zones = master.read(1, window=window, masked=True)
                output = np.ones(zones.shape, dtype="float32")
                output[np.ma.getmaskarray(zones)] = -99
                dst.write(output, 1, window=window)
    population = DasymetricMapper(settings).map(str(prediction))["unconstrained"]
    actual = raster_stat(population, settings.mastergrid, max_workers=2, block_size=settings.block_size).set_index("id")["sum"]
    assert set(actual.index) == set(expected.index)
    np.testing.assert_allclose(actual.reindex(expected.index), expected, rtol=1e-6, atol=1e-5)
