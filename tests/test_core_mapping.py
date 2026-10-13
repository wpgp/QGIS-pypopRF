from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio

from core.pypoprf.core.dasymetric import DasymetricMapper
from core.pypoprf.core.feature_extraction import FeatureExtractor
from core.pypoprf.utils.raster import raster_stat
from core.pypoprf.utils.workers import DasymetricWorker
from core.pypoprf.utils.runtime import CancellationToken, CancelledError
from test_core_raster import write_raster


def settings_for(tmp_path, master, census, by_block=True, constrain=None, covariates=None):
    return SimpleNamespace(work_dir=str(tmp_path), output_dir=str(tmp_path / "custom-output"), mastergrid=master,
                           census={"path": str(census), "id_column": "zone", "pop_column": "people"},
                           by_block=by_block, max_workers=2, block_size=(2, 1), constrain=constrain,
                           covariate=covariates or {}, cancellation_token=CancellationToken())


@pytest.mark.parametrize("by_block", [True, False])
def test_mapping_keyed_conservation_singletons_and_zero_population(tmp_path, by_block):
    grid = write_raster(tmp_path / "grid.tif", [[80, 80, 7, 99, 0]])
    pred = write_raster(tmp_path / "pred.tif", [[1., 3., 2., 0., 50.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [99, 7, 80], "people": [0, 30, 100]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census, by_block)
    mapper = DasymetricMapper(settings)
    out = mapper.map(pred)["unconstrained"]
    assert mapper.diagnostics["unconstrained"]["excluded_grid_zone_ids"] == [0]
    assert out.parent == tmp_path / "custom-output"
    with rasterio.open(out) as src:
        np.testing.assert_allclose(src.read(1), [[25, 75, 30, 0, -99]])
    sums = raster_stat(out, grid).set_index("id")["sum"]
    assert sums.to_dict() == {7: 30, 80: 100, 99: 0}


@pytest.mark.parametrize("missing_support", ["zero", "absent", "nodata"])
def test_positive_population_without_support_fails_before_output(tmp_path, missing_support):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    pred = write_raster(tmp_path / "pred.tif", [[0. if missing_support != "nodata" else -99.]], nodata=-99)
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [2 if missing_support == "absent" else 1], "people": [10]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census)
    with pytest.raises(ValueError, match="no positive eligible"):
        DasymetricMapper(settings).map(pred)
    assert not (tmp_path / "custom-output" / "population_unconstrained.tif").exists()


@pytest.mark.parametrize("by_block", [True, False])
def test_zero_population_and_prediction_nodata_are_zero_only_on_eligible_grid(tmp_path, by_block):
    grid = write_raster(tmp_path / "grid.tif", [[1, 1, 1]], mask=[[1, 1, 0]])
    pred = write_raster(tmp_path / "pred.tif", [[np.nan, np.nan, np.nan]], nodata=np.nan)
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [0]}).to_csv(census, index=False)
    out = DasymetricMapper(settings_for(tmp_path, grid, census, by_block)).map(pred)["unconstrained"]
    with rasterio.open(out) as src:
        np.testing.assert_array_equal(src.read(1), [[0, 0, -99]])


@pytest.mark.parametrize("value", [-1., np.inf, np.nan])
def test_invalid_unmasked_weights_fail(tmp_path, value):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    pred = write_raster(tmp_path / "pred.tif", [[value]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [10]}).to_csv(census, index=False)
    with pytest.raises(ValueError, match="nonfinite or negative"):
        DasymetricMapper(settings_for(tmp_path, grid, census)).map(pred)


@pytest.mark.parametrize("by_block", [True, False])
def test_age_sex_reordered_sparse_ids_suffixes_and_constraints(tmp_path, by_block):
    grid = write_raster(tmp_path / "grid.tif", [[80, 80, 7]])
    constrained = write_raster(tmp_path / "constraint.tif", [[80, -99, 7]], nodata=-99)
    pred = write_raster(tmp_path / "pred.tif", [[1., 3., 2.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [7, 80], "people": [40, 160]}).to_csv(census, index=False)
    agesex = tmp_path / "age.csv"
    pd.DataFrame({"zone": [80, 7], "f0": [100, 5], "m_0_4": [60, 35], "flag": [9, 9], "mean": [8, 8]}).to_csv(agesex, index=False)
    mapper = DasymetricMapper(settings_for(tmp_path, grid, census, by_block, constrained))
    mapper.map(pred)
    norm_before = (tmp_path / "custom-output" / "normalized_census.tif").read_bytes()
    paths = mapper.map_agesex(pred, agesex)
    assert len(paths) == 4
    with rasterio.open(paths["unconstrained_f0"]) as src:
        np.testing.assert_allclose(src.read(1), [[25, 75, 5]])
    with rasterio.open(paths["constrained_f0"]) as src:
        np.testing.assert_allclose(src.read(1), [[100, -99, 5]])
    assert (tmp_path / "custom-output" / "normalized_census.tif").read_bytes() == norm_before
    assert (tmp_path / "custom-output" / "agesex" / "additional_files" / "normalized_census_f0.tif").exists()
    assert (tmp_path / "custom-output" / "agesex" / "additional_files" / "normalized_census_constrained_m_0_4.tif").exists()


@pytest.mark.parametrize("frame", [pd.DataFrame({"id": [1], "flag": [1]}),
                                    pd.DataFrame({"id": [1, 1], "f0": [1, 2]}),
                                    pd.DataFrame({"id": [1], "f0": [-1]}),
                                    pd.DataFrame({"id": [1], "f0": [np.inf]}),
                                    pd.DataFrame({"id": [1], "f0": ["bad"]})])
def test_agesex_validation(frame):
    with pytest.raises(ValueError):
        DasymetricMapper._validate_agesex(frame, "id")


def test_feature_density_independent_of_covariate_order_and_nodata(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[1, 1, 1, 1]])
    a = write_raster(tmp_path / "a.tif", [[1., 1., -99., -99.]], nodata=-99)
    b = write_raster(tmp_path / "b.tif", [[2., 2., 2., 2.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [100]}).to_csv(census, index=False)
    for covariates in ({"a": a, "b": b}, {"b": b, "a": a}):
        out = FeatureExtractor(settings_for(tmp_path, grid, census, covariates=covariates)).extract()
        assert out["dens"].tolist() == [25]
        assert out["eligible_pixel_count"].tolist() == [4]
    assert (tmp_path / "custom-output" / "features.csv").exists()


def test_missing_covariate_zone_means_fail_explicitly(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    a = write_raster(tmp_path / "a.tif", [[-99.]], nodata=-99)
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [100]}).to_csv(census, index=False)
    with pytest.raises(ValueError, match="lack valid covariate means"):
        FeatureExtractor(settings_for(tmp_path, grid, census, covariates={"a": a})).extract()


def test_on_disk_wrong_zone_totals_block_publication(tmp_path, monkeypatch):
    grid = write_raster(tmp_path / "grid.tif", [[1, 2]])
    pred = write_raster(tmp_path / "pred.tif", [[1., 1.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1, 2], "people": [100, 20]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census)
    mapper = DasymetricMapper(settings)
    out = tmp_path / "custom-output" / "population_unconstrained.tif"
    out.write_bytes(b"prior-result")
    original = DasymetricWorker.compute
    def corrupt(self):
        data = original(self)
        # Preserve global total while allocating it to the wrong zones.
        return data[..., ::-1].copy()
    monkeypatch.setattr(DasymetricWorker, "compute", corrupt)
    with pytest.raises(ValueError, match="conservation failed by zone"):
        mapper.map(pred)
    assert out.read_bytes() == b"prior-result"


def test_worker_failure_cannot_publish_partial_population(tmp_path, monkeypatch):
    grid = write_raster(tmp_path / "grid.tif", [[1, 1, 1, 1]])
    pred = write_raster(tmp_path / "pred.tif", [[1., 1., 1., 1.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [100]}).to_csv(census, index=False)
    original = DasymetricWorker.compute
    def broken(self):
        if self.window.col_off == 2:
            raise IOError("tile read failed")
        return original(self)
    monkeypatch.setattr(DasymetricWorker, "compute", broken)
    with pytest.raises(IOError, match="tile read failed"):
        DasymetricMapper(settings_for(tmp_path, grid, census)).map(pred)
    assert not (tmp_path / "custom-output" / "population_unconstrained.tif").exists()


def test_cancellation_propagates_before_writes(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    pred = write_raster(tmp_path / "pred.tif", [[1.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [100]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census)
    settings.cancellation_token.cancel()
    with pytest.raises(CancelledError):
        DasymetricMapper(settings).map(pred)
    assert not list((tmp_path / "custom-output").glob("*.tif"))


def test_csv_duplicate_header_and_atomic_write_cancellation(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    census = tmp_path / "census.csv"
    census.write_text("zone,people,people\n1,10,20\n", encoding="utf-8")
    settings = settings_for(tmp_path, grid, census)
    extractor = FeatureExtractor(settings)
    with pytest.raises(ValueError, match="Duplicate census column"):
        extractor.load_table(census)
    output = tmp_path / "saved.csv"
    output.write_bytes(b"prior-result")
    settings.cancellation_token.cancel()
    with pytest.raises(CancelledError):
        extractor.dump_table(pd.DataFrame({"x": [1]}), output)
    assert output.read_bytes() == b"prior-result"


def test_table_output_cannot_replace_input(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    census = tmp_path / "census.csv"
    census.write_text("zone,people\n1,10\n", encoding="utf-8")
    before = census.read_bytes()
    with pytest.raises(ValueError, match="conflicts with an input"):
        FeatureExtractor(settings_for(tmp_path, grid, census)).dump_table(pd.DataFrame({"x": [1]}), census)
    assert census.read_bytes() == before


def test_mapper_output_cannot_replace_input(tmp_path):
    output_dir = tmp_path / "custom-output"
    output_dir.mkdir()
    grid = write_raster(tmp_path / "grid.tif", [[1]])
    pred = write_raster(output_dir / "normalized_census.tif", [[1.]])
    census = tmp_path / "census.csv"
    census.write_text("zone,people\n1,10\n", encoding="utf-8")
    before = (output_dir / "normalized_census.tif").read_bytes()
    with pytest.raises(ValueError, match="conflicts with an input"):
        DasymetricMapper(settings_for(tmp_path, grid, census)).map(pred)
    assert (output_dir / "normalized_census.tif").read_bytes() == before


def test_grouped_cv_survives_keyed_feature_extraction(tmp_path):
    from core.pypoprf.core.model import Model
    grid = write_raster(tmp_path / "grid.tif", [[80, 80, 7, 99]])
    covariate = write_raster(tmp_path / "x.tif", [[1., 2., 3., 4.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [99, 7, 80], "people": [0, 30, 100],
                  "district": ["south", "north", "north"]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census, covariates={"x": covariate})
    settings.cv_group_column = "district"
    settings.n_estimators = 2
    settings.log_scale = True
    settings.selection_threshold = 0.01
    features = FeatureExtractor(settings).extract()
    assert features.set_index("zone")["district"].to_dict() == {7: "north", 80: "north", 99: "south"}
    model = Model(settings)
    model.train(features, save_model=False)
    assert model.cv_metrics["scheme"] == "group"
    assert model.cv_predictions.groupby("group")["fold"].nunique().to_dict() == {"north": 1, "south": 1}


def test_age_sex_rejects_case_insensitive_filename_collision():
    frame = pd.DataFrame({"zone": [1], "f0": [10], "F0": [90]})
    with pytest.raises(ValueError, match="unique ignoring case"):
        DasymetricMapper._validate_agesex(frame, "zone")


def test_legacy_serial_mode_bounds_every_raster_read(tmp_path, monkeypatch):
    from core.pypoprf.utils.raster import raster_stat_stack, remask_layer
    shape = (24, 30)
    grid = write_raster(tmp_path / "grid.tif", np.ones(shape, dtype="int32"))
    prediction = write_raster(tmp_path / "pred.tif", np.ones(shape, dtype="float32"))
    binary_mask = write_raster(tmp_path / "mask.tif", np.zeros(shape, dtype="uint8"))
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [1], "people": [720]}).to_csv(census, index=False)
    settings = settings_for(tmp_path, grid, census, by_block=False)
    settings.block_size = (6, 4)
    original = rasterio.open
    reads = []
    class TrackingReader:
        def __init__(self, source):
            self.source = source
        def __getattr__(self, name):
            return getattr(self.source, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.source.__exit__(*args)
        def read(self, *args, **kwargs):
            window = kwargs.get("window")
            assert window is not None, "Serial mode must never read the whole dataset"
            assert window.width <= 6 and window.height <= 4
            reads.append(window)
            return self.source.read(*args, **kwargs)
    def track_open(path, *args, **kwargs):
        source = original(path, *args, **kwargs)
        return TrackingReader(source) if source.mode == "r" else source
    monkeypatch.setattr(rasterio, "open", track_open)
    stats = raster_stat_stack({"x": prediction}, grid, by_block=False, block_size=settings.block_size)
    assert stats["eligible_pixel_count"].tolist() == [720]
    remasked = remask_layer(grid, binary_mask, 1, tmp_path / "remasked.tif", by_block=False,
                           block_size=settings.block_size)
    assert remasked
    out = DasymetricMapper(settings).map(prediction)["unconstrained"]
    assert out.is_file()
    assert len(reads) > 100


def test_age_sex_totals_diagnostic_is_keyed_and_does_not_force_subgroups(tmp_path):
    grid = write_raster(tmp_path / "grid.tif", [[80, 7]])
    prediction = write_raster(tmp_path / "pred.tif", [[1., 1.]])
    census = tmp_path / "census.csv"
    pd.DataFrame({"zone": [7, 80], "people": [50, 100]}).to_csv(census, index=False)
    agesex = tmp_path / "age.csv"
    pd.DataFrame({"zone": [80, 7], "f0_4": [10, 5], "m0_4": [20, 5]}).to_csv(agesex, index=False)
    mapper = DasymetricMapper(settings_for(tmp_path, grid, census))
    paths = mapper.map_agesex(prediction, agesex)
    diagnostic = mapper.diagnostics["age_sex_totals"]
    assert diagnostic["mismatch_count"] == 2
    assert set(diagnostic["mismatched_zone_ids"]) == {7, 80}
    deltas = {row["id"]: row["difference"] for row in diagnostic["differences"]}
    assert deltas == {7: -40, 80: -70}
    table = pd.read_csv(mapper.output_dir / diagnostic["table"]).set_index("id")
    assert table["difference"].to_dict() == deltas
    with rasterio.open(paths["unconstrained_f0_4"]) as src:
        np.testing.assert_array_equal(src.read(1), [[10, 5]])


def test_dummy_features_follow_configured_schema_without_file_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = settings_for(tmp_path, "not-read.tif", "not-read.csv", covariates={"x": "not-read.tif"})
    settings.cv_group_column = "district"
    features = FeatureExtractor(settings).get_dummy()
    assert features.columns.tolist() == ["zone", "people", "eligible_pixel_count", "x_avg", "dens", "district"]
    assert features.iloc[0]["dens"] == 1
    assert not list(tmp_path.iterdir())
