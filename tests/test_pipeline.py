import hashlib

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from core.pypoprf.config.settings import Settings
from core.pypoprf.pipeline import execute_analysis
from core.pypoprf.utils.runtime import CancellationToken, CancelledError


def _write(path, data, nodata=None):
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0],
                       count=1, dtype=data.dtype, crs="EPSG:3857",
                       transform=from_origin(0, 100, 10, 10), nodata=nodata) as out:
        out.write(data, 1)


@pytest.fixture
def inputs(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    zones = np.repeat(np.arange(1, 13, dtype=np.int32), 16).reshape(8, 24)
    positions = np.arange(zones.size).reshape(zones.shape) % 16
    covariate = (zones + positions / 16).astype("float32")
    covariate[positions == 1] = -9999
    mask = (positions == 15).astype("uint8")
    constrain = (positions != 0).astype("uint8")
    _write(data / "zones.tif", zones)
    _write(data / "covariate.tif", covariate, -9999)
    _write(data / "water.tif", mask)
    _write(data / "support.tif", constrain)
    census = pd.DataFrame({"zone": np.arange(1, 13), "people": np.arange(12) * 80.0})
    census.sample(frac=1, random_state=17).to_csv(data / "census.csv", index=False)
    groups = census.rename(columns={"people": "f0_4"})
    groups["f0_4"] *= 0.3
    groups["m0_4"] = census["people"] * 0.7
    groups.sample(frac=1, random_state=9).to_csv(data / "agesex.csv", index=False)
    return tmp_path, zones, positions, census


@pytest.mark.integration
@pytest.mark.parametrize("log_scale", [False, True])
@pytest.mark.parametrize("by_block", [False, True])
def test_complete_pipeline_preserves_sources_and_keyed_population(inputs, log_scale, by_block):
    root, zones, positions, census = inputs
    originals = {p: hashlib.sha256(p.read_bytes()).digest() for p in (root / "data").iterdir()}
    settings = Settings(
        work_dir=str(root), mastergrid="zones.tif", mask="water.tif", constrain="support.tif",
        covariates={"building": "covariate.tif"}, census_data="census.csv",
        census_pop_column="people", census_id_column="zone", agesex_data="agesex.csv",
        output_dir="run", block_size=(16, 16), max_workers=2, by_block=by_block,
        log_scale=log_scale, n_estimators=8, cv_folds=3, cv_strategy="shuffled_zone",
    )
    progress = []
    result = execute_analysis(settings, lambda value, message: progress.append(value))
    assert progress == sorted(progress) and progress[-1] == 95
    assert result["cv_metrics"]["status"] == "complete"
    assert result["cv_metrics"]["spatial_validation"] is False
    assert settings.mastergrid == str(root / "data" / "zones.tif")
    assert settings.constrain == str(root / "data" / "support.tif")
    for mode, path in result["population"].items():
        with rasterio.open(path) as src:
            population = src.read(1, masked=True)
        assert np.ma.getmaskarray(population)[positions == 15].all()
        if mode == "constrained":
            assert np.ma.getmaskarray(population)[positions == 0].all()
        for row in census.to_dict("records"):
            actual = float(population[zones == row["zone"]].sum())
            assert actual == pytest.approx(row["people"], abs=1e-5)
        for group, fraction in (("f0_4", 0.3), ("m0_4", 0.7)):
            with rasterio.open(result["agesex"][f"{mode}_{group}"]) as src:
                layer = src.read(1, masked=True)
            assert np.ma.allclose(layer, population * fraction, atol=1e-5)
    assert all(hashlib.sha256(p.read_bytes()).digest() == digest for p, digest in originals.items())
    assert not list((root / "run").glob("grids-*"))


def test_cancelled_pipeline_creates_no_result_and_preserves_sources(inputs):
    root, _, _, _ = inputs
    token = CancellationToken()
    settings = Settings(work_dir=str(root), mastergrid="zones.tif",
                        covariates={"building": "covariate.tif"}, census_data="census.csv",
                        census_pop_column="people", census_id_column="zone", output_dir="run",
                        n_estimators=8, cancellation_token=token)
    token.cancel()
    with pytest.raises(CancelledError):
        execute_analysis(settings)
    assert not list((root / "run").rglob("*.tif"))


@pytest.mark.parametrize("artifact", ["model_bundle.pkl.gz", "feature_importance.csv", "cv_metrics.json"])
def test_incomplete_previous_run_is_preserved_before_any_calculation(inputs, artifact):
    root, _, _, _ = inputs
    output = root / "previous"
    output.mkdir()
    old = output / artifact
    old.write_bytes(b"previous attempt, needs inspection")
    settings = Settings(work_dir=str(root), mastergrid="zones.tif",
                        covariates={"building": "covariate.tif"}, census_data="census.csv",
                        census_pop_column="people", census_id_column="zone", output_dir="previous")
    with pytest.raises(ValueError, match="fresh run"):
        execute_analysis(settings)
    assert old.read_bytes() == b"previous attempt, needs inspection"
    assert list(output.iterdir()) == [old]
