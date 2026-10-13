import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os

import joblib
import numpy as np
import pandas as pd
import pytest
import rasterio

from core.pypoprf.config.settings import Settings
from core.pypoprf.core.model import Model
from core.pypoprf.utils.runtime import CancellationToken, CancelledError
from core.pypoprf.utils.joblib_manager import joblib_resources
from core.pypoprf.utils.logger import PopRFLogger
from test_settings import settings_inputs as settings_inputs, write_raster
from rasterio.transform import from_origin


def training_data(n=12):
    return pd.DataFrame({"id": np.arange(1, n + 1), "sum": np.arange(1, n + 1) * 10,
                         "x_avg": np.arange(n, dtype=float),
                         "dens": np.arange(n, dtype=float) / 20,
                         "eligible_pixel_count": np.ones(n), "metadata": "ignored"})


def test_reproducibility_bundle_roundtrip_and_custom_output(settings_inputs, tmp_path):
    settings = Settings(**settings_inputs, output_dir="custom/results")
    first = Model(settings)
    data = training_data()
    first.train(data)
    second = Model(settings)
    second.train(data, save_model=False)
    prediction = first.model.predict(first.scaler.transform(data[first.selected_features]))
    np.testing.assert_array_equal(prediction, second.model.predict(second.scaler.transform(data[second.selected_features])))
    loaded = Model(settings)
    loaded.load_model(settings.output_dir / "model_bundle.pkl.gz")
    np.testing.assert_array_equal(prediction, loaded.model.predict(loaded.scaler.transform(data[loaded.selected_features])))
    assert first.target_transform == "log1p"
    assert list(first.feature_names) == ["x_avg"]
    assert not (tmp_path / "output").exists()
    assert json.loads((settings.output_dir / "cv_metrics.json").read_text())["scale"] == "density"


@pytest.mark.parametrize("n", [1, 2, 3, 9])
@pytest.mark.parametrize("log_scale", [False, True])
def test_small_and_zero_density_training_is_finite(settings_inputs, n, log_scale):
    settings = Settings(**settings_inputs)
    data = training_data(n)
    data["dens"] = 0
    model = Model(settings)
    model.train(data, log_scale=log_scale)
    assert len(model.selected_features) == 1
    assert np.isfinite(model.model.predict(model.scaler.transform(data[model.selected_features]))).all()
    if n == 1:
        assert model.cv_metrics["status"] == "unavailable"
    else:
        assert model.cv_metrics["r2"] is None
        assert model.cv_metrics["normalized_rmse"] is None
    model.predict(log_scale=log_scale)


def test_group_cross_validation_keeps_groups_together(settings_inputs):
    model = Model(Settings(**settings_inputs))
    data = training_data(12)
    groups = np.repeat(["west", "east", "north"], 4)
    model.train(data, groups=groups, save_model=False)
    assert model.cv_predictions.groupby("group")["fold"].nunique().eq(1).all()
    assert model.cv_metrics["scheme"] == "group"
    # Group identifiers by themselves do not establish spatial independence.
    assert not model.cv_metrics["spatial_validation"]


def test_cv_refits_full_procedure_using_training_fold_only(settings_inputs, monkeypatch):
    model = Model(Settings(**settings_inputs))
    observed = []
    original = model._fit_procedure
    def wrapped(X, y):
        observed.append(set(X.index))
        return original(X, y)
    monkeypatch.setattr(model, "_fit_procedure", wrapped)
    data = training_data(12)
    model.train(data, save_model=False)
    assert len(observed) == model.cv_metrics["n_folds"] + 1
    for fold, subset in enumerate(observed[:-1]):
        test_rows = set(model.cv_predictions.index[model.cv_predictions.fold == fold])
        assert not subset.intersection(test_rows)
        assert subset | test_rows == set(data.index)


@pytest.mark.parametrize("bad", ["nan", "negative", "missing", "duplicate"])
def test_invalid_training_contract_is_explicit(settings_inputs, bad):
    model = Model(Settings(**settings_inputs))
    data = training_data()
    if bad == "nan": data.loc[3, "x_avg"] = np.nan
    if bad == "negative": data.loc[3, "dens"] = -1
    if bad == "missing": data = data.drop(columns="x_avg")
    if bad == "duplicate": data.loc[3, "id"] = 1
    with pytest.raises(ValueError):
        model.train(data)


def test_complex_predictor_is_rejected_without_silent_cast(settings_inputs):
    data = training_data(2)
    data["x_avg"] = [1 + 3j, 2 + 4j]
    with pytest.raises(ValueError, match="real"):
        Model(Settings(**settings_inputs)).train(data)


def test_prediction_masks_nodata_zero_values_and_correct_inverse(settings_inputs, tmp_path):
    values = np.zeros((32, 32), dtype=np.float32)
    values[0, 0] = -9999
    write_raster(Path(settings_inputs["covariates"]["x"]), values)
    model = Model(Settings(**settings_inputs))
    data = training_data(2)
    data["dens"] = 5
    model.train(data)
    with rasterio.open(model.predict()) as output:
        assert output.count == 1
        result = output.read(1, masked=True)
        assert result.mask[0, 0]
        np.testing.assert_allclose(result.compressed(), 5, rtol=1e-6)
    with pytest.raises(ValueError, match="transform"):
        model.predict(log_scale=False)


def test_prediction_failure_preserves_previous_raster(settings_inputs, monkeypatch):
    model = Model(Settings(**settings_inputs))
    model.train(training_data(2))
    path = Path(model.predict())
    original = path.read_bytes()
    monkeypatch.setattr(model.model, "predict", lambda X: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError, match="injected"):
        model.predict()
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.partial*"))


def test_prediction_open_failure_closes_previously_opened_readers(settings_inputs, monkeypatch):
    model = Model(Settings(**settings_inputs))
    model.train(training_data(2))
    original_open = rasterio.open
    handles = []
    def failing_open(path, *args, **kwargs):
        if str(path) == model.settings.covariate["x"]:
            raise OSError("covariate open failed")
        handle = original_open(path, *args, **kwargs)
        handles.append(handle)
        return handle
    monkeypatch.setattr(rasterio, "open", failing_open)
    with pytest.raises(OSError, match="open failed"):
        model.predict()
    assert handles and all(handle.closed for handle in handles)
    assert not (model.output_dir / "prediction.tif").exists()


@pytest.mark.parametrize("by_block", [False, True])
def test_prediction_limits_each_inference_batch_to_tile_size(settings_inputs, monkeypatch, by_block):
    model = Model(Settings(**(settings_inputs | {"by_block": by_block})))
    model.train(training_data(2))
    original_predict = model.model.predict
    batch_sizes = []
    def record_predict(features):
        batch_sizes.append(len(features))
        return original_predict(features)
    monkeypatch.setattr(model.model, "predict", record_predict)
    model.predict()
    assert len(batch_sizes) == 4
    assert max(batch_sizes) <= 16 * 16


def test_prediction_profile_preserves_valid_zero_density(settings_inputs):
    model = Model(Settings(**settings_inputs))
    data = training_data(2)
    data["dens"] = 0
    model.train(data)
    with rasterio.open(model.predict()) as output:
        values = output.read(1, masked=True)
        assert values.count() == 32 * 32
        assert np.all(values.compressed() == 0)
        assert np.isnan(output.nodata)
        assert output.count == 1 and output.dtypes == ("float32",)
        assert output.block_shapes == [(16, 16)]
        assert output.compression.value == "DEFLATE"


def test_publication_rechecks_input_alias_after_settings_mutation(settings_inputs, tmp_path):
    model = Model(Settings(**settings_inputs))
    model.train(training_data(2))
    source = tmp_path / "prediction.tif"
    write_raster(source)
    original = source.read_bytes()
    model.settings.covariate["x"] = str(source)
    model.output_dir = tmp_path
    with pytest.raises(ValueError, match="overwrite an input"):
        model.predict()
    assert source.read_bytes() == original


def test_cancellation_during_tree_batches_does_not_publish_model(settings_inputs, monkeypatch):
    settings = Settings(**settings_inputs)
    settings.cancellation_token = CancellationToken()
    model = Model(settings)
    original = model._forest
    def forest():
        instance = original()
        original_fit = instance.fit
        def fit(*args, **kwargs):
            result = original_fit(*args, **kwargs)
            settings.cancellation_token.cancel()
            return result
        instance.fit = fit
        return instance
    monkeypatch.setattr(model, "_forest", forest)
    with pytest.raises(CancelledError):
        model.train(training_data(2))
    assert not (settings.output_dir / "model_bundle.pkl.gz").exists()


def test_failed_retraining_cannot_reinterpret_previous_forest(settings_inputs):
    model = Model(Settings(**settings_inputs))
    model.train(training_data(2), log_scale=True)
    invalid = training_data(2)
    invalid.loc[0, "dens"] = -1
    with pytest.raises(ValueError):
        model.train(invalid, log_scale=False)
    with pytest.raises(RuntimeError, match="not trained"):
        model.predict()


def test_single_zone_retraining_clears_previous_oof_csv(settings_inputs):
    model = Model(Settings(**settings_inputs))
    model.train(training_data(3))
    assert len(pd.read_csv(model.output_dir / "cv_predictions.csv")) == 3
    model.train(training_data(1))
    assert pd.read_csv(model.output_dir / "cv_predictions.csv").empty


@pytest.mark.parametrize("mutation", ["version", "transform", "schema", "legacy"])
def test_bundle_validation_and_legacy_retrain_requirement(settings_inputs, mutation, tmp_path):
    settings = Settings(**settings_inputs)
    model = Model(settings)
    model.train(training_data(2))
    bundle = joblib.load(settings.output_dir / "model_bundle.pkl.gz")
    if mutation == "version": bundle["versions"]["sklearn"] = "0.0"
    if mutation == "transform": bundle["target_transform"] = "log_density_plus_point_one"
    if mutation == "schema": bundle["selected_features"] = ["bogus"]
    if mutation == "legacy": bundle = bundle["model"]
    path = tmp_path / "invalid.gz"
    joblib.dump(bundle, path)
    with pytest.raises(ValueError):
        Model(settings).load_model(path)


def test_bundle_rejects_new_pixel_geometry(settings_inputs, tmp_path):
    original = Settings(**settings_inputs)
    model = Model(original)
    model.train(training_data(2))
    master = write_raster(tmp_path / "other-master.tif", transform=from_origin(20, 10, .02, .02))
    covariate = write_raster(tmp_path / "other-x.tif", transform=from_origin(20, 10, .02, .02))
    other = Settings(**(settings_inputs | {"mastergrid": master, "covariates": {"x": covariate}}))
    with pytest.raises(ValueError, match="pixel geometry"):
        Model(other).load_model(original.output_dir / "model_bundle.pkl.gz")
    original.mastergrid = master
    with pytest.raises(ValueError, match="pixel geometry"):
        model.predict()


def test_joblib_resources_are_private_and_do_not_mutate_environment(tmp_path):
    original = os.environ.get("JOBLIB_TEMP_FOLDER")
    def context():
        with joblib_resources(base_dir=str(tmp_path), qgis_mode=True) as folder:
            assert Path(folder).is_dir()
            assert os.environ.get("JOBLIB_TEMP_FOLDER") == original
            return folder
    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda _: context(), range(2)))
    assert paths[0] != paths[1]
    assert all(not Path(path).exists() for path in paths)


def test_logger_escapes_html_and_appends_utf8(tmp_path):
    logger = PopRFLogger("test-pypoprf-logger")
    record = __import__("logging").LogRecord("test", 20, "test", 1, '<a href="file">& текст</a>', (), None)
    formatted = logger._get_formatter(colored=True).format(record)
    assert '&lt;a href=&quot;file&quot;&gt;&amp; текст&lt;/a&gt;' in formatted
    path = tmp_path / "run.log"
    path.write_text("existing\n", encoding="utf-8")
    logger.set_log_file(str(path))
    logger.info("текст")
    logger.close()
    assert path.read_text(encoding="utf-8").startswith("existing\n")
    assert "текст" in path.read_text(encoding="utf-8")


def test_disabling_file_logging_preserves_console(tmp_path):
    from io import StringIO
    stream = StringIO()
    logger = PopRFLogger("test-pypoprf-null-file")
    logger.set_output_stream(stream)
    path = tmp_path / "run.log"
    logger.set_log_file(str(path))
    logger.info("before")
    logger.set_log_file(None)
    before = path.read_bytes()
    logger.info("after")
    assert path.read_bytes() == before
    assert "after" in stream.getvalue()
    assert logger.file_handler is None
    assert logger.console_handler is not None
    logger.close()
