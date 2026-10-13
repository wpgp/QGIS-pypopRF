"""Geometric and no-leakage checks for the production spatial-CV contract."""
import json

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import Affine

from core.pypoprf.config.settings import Settings
from core.pypoprf.algorithms.model import Model
from core.pypoprf.utils.runtime import CancellationToken, CancelledError


@pytest.fixture
def spatial_inputs(tmp_path):
    # Eight vertical zones, each eight columns wide; four spatial blocks
    # each contain two zones. Pixel-centre centroids are hand-computable.
    zones = np.tile(np.repeat(np.arange(1, 9, dtype=np.int32), 8), (32, 1))
    affine = Affine(10, 0, 100, 0, -10, 500)
    for name, values, nodata in (("master.tif", zones, -9999),
                                 ("x.tif", zones.astype(np.float32), -9999)):
        with rasterio.open(tmp_path / name, "w", driver="GTiff", width=64, height=32,
                           count=1, dtype=values.dtype, crs="EPSG:3857",
                           transform=affine, nodata=nodata) as destination:
            destination.write(values, 1)
    census = pd.DataFrame({"id": np.arange(1, 9), "pop": np.arange(1, 9) * 256.0})
    census.to_csv(tmp_path / "census.csv", index=False)
    settings = Settings(work_dir=str(tmp_path), data_dir=".", mastergrid="master.tif",
                        covariates={"x": "x.tif"}, census_data="census.csv",
                        census_pop_column="pop", census_id_column="id",
                        block_size=(16, 16), spatial_grid=(4, 1), n_estimators=8,
                        cv_folds=4, max_workers=1)
    features = census.assign(x_avg=np.arange(1, 9), dens=np.arange(1, 9, dtype=float))
    return settings, features


def test_default_settings_use_explicit_spatial_strategy(spatial_inputs):
    settings, _ = spatial_inputs
    assert settings.cv_strategy == "spatial"


def test_centroids_and_block_membership_match_known_geometry(spatial_inputs):
    settings, features = spatial_inputs
    model = Model(settings)
    groups, provenance, geometry = model._spatial_groups(features.id.to_numpy())
    np.testing.assert_allclose(geometry.centroid_row, 16)
    np.testing.assert_allclose(geometry.centroid_column, np.arange(4, 64, 8))
    np.testing.assert_allclose(geometry.centroid_x, 100 + 10 * np.arange(4, 64, 8))
    np.testing.assert_allclose(geometry.centroid_y, 340)
    np.testing.assert_array_equal(geometry.eligible_pixel_count, 256)
    assert list(groups) == [f"row0_col{block}" for block in range(4) for _ in range(2)]
    assert provenance["block_width_pixels"] == 16
    assert provenance["block_width_native_units"] == 160
    assert provenance["buffer_pixels"] == 0
    assert provenance["n_occupied_blocks"] == 4


def test_spatial_folds_are_disjoint_and_fresh_procedure_never_sees_test_block(spatial_inputs, monkeypatch):
    settings, features = spatial_inputs
    model = Model(settings)
    original = model._fit_procedure
    observed = []
    def record(X, density):
        observed.append(set(X.index))
        return original(X, density)
    monkeypatch.setattr(model, "_fit_procedure", record)
    model.train(features)
    assert model.cv_metrics["scheme"] == "spatial_blocks"
    assert model.cv_metrics["spatial_validation"]
    assert model.cv_metrics["n_folds"] == 4
    predictions = model.cv_predictions
    assert predictions.groupby("group").fold.nunique().eq(1).all()
    for fold, training_rows in enumerate(observed[:-1]):
        test_rows = set(predictions.index[predictions.fold == fold])
        assert training_rows.isdisjoint(test_rows)
        training_groups = set(predictions.loc[list(training_rows), "group"])
        test_groups = set(predictions.loc[list(test_rows), "group"])
        assert training_groups.isdisjoint(test_groups)
    assert len(observed) == 5  # four independent outer procedures and final fit
    saved = json.loads((model.output_dir / "cv_metrics.json").read_text())
    assert saved["provenance"]["subdivisions"] == [4, 1]
    assert "fine-pixel" in " ".join(saved["provenance"]["limitations"])
    geometry = pd.read_csv(model.output_dir / "cv_zone_geometry.csv")
    assert set(geometry.zone_id) == set(features.id)


def test_one_occupied_spatial_block_does_not_fallback_to_random_cv(spatial_inputs):
    settings, features = spatial_inputs
    settings.spatial_grid = (1, 1)
    model = Model(settings)
    model.train(features)
    assert model.cv_metrics["status"] == "unavailable"
    assert model.cv_metrics["scheme"] == "spatial_blocks"
    assert "two occupied" in model.cv_metrics["reason"]
    assert model.cv_predictions.empty
    assert model.model is not None  # fitting remains possible; validation honestly unavailable


def test_missing_mastergrid_zone_does_not_get_invented_centroid(spatial_inputs):
    settings, features = spatial_inputs
    features.loc[0, "id"] = 999
    model = Model(settings)
    model.train(features)
    assert model.cv_metrics["status"] == "unavailable"
    assert model.cv_metrics["provenance"]["missing_zone_ids"] == [999]
    assert model.cv_predictions.empty


def test_valid_pixel_mask_changes_centroid_not_nodata_sentinel(spatial_inputs):
    settings, features = spatial_inputs
    with rasterio.open(settings.mastergrid, "r+") as master:
        values = master.read(1)
        values[:16, :8] = -9999
        master.write(values, 1)
    groups, _, geometry = Model(settings)._spatial_groups(features.id.to_numpy())
    assert geometry.loc[0, "centroid_row"] == 24
    assert geometry.loc[0, "centroid_column"] == 4
    assert geometry.loc[0, "eligible_pixel_count"] == 128
    assert groups[0] == "row0_col0"


def test_manual_groups_are_honored_but_not_called_spatial_provenance(spatial_inputs):
    settings, features = spatial_inputs
    manual = np.repeat(["north", "east"], 4)
    model = Model(settings)
    model.train(features, groups=manual)
    assert model.cv_metrics["scheme"] == "group"
    assert not model.cv_metrics["spatial_validation"]
    assert model.cv_metrics["provenance"]["source"] == "train_arguments"
    np.testing.assert_array_equal(model.cv_predictions.group, manual)


def test_explicit_group_retry_clears_stale_spatial_geometry(spatial_inputs):
    settings, features = spatial_inputs
    model = Model(settings)
    model.train(features)
    assert len(pd.read_csv(model.output_dir / "cv_zone_geometry.csv")) == len(features)
    model.train(features, groups=np.repeat(["a", "b"], 4))
    assert pd.read_csv(model.output_dir / "cv_zone_geometry.csv").empty
    assert model.cv_zone_geometry is None


def test_group_strategy_requires_groups_and_one_group_unavailable(spatial_inputs):
    settings, features = spatial_inputs
    settings.cv_strategy = "groups"
    model = Model(settings)
    with pytest.raises(ValueError, match="requires"):
        model.train(features)
    model.train(features, groups=np.repeat("only", len(features)))
    assert model.cv_metrics["status"] == "unavailable"
    assert not model.cv_metrics["spatial_validation"]


def test_centroid_scan_checks_cancellation_between_bounded_windows(spatial_inputs, monkeypatch):
    settings, features = spatial_inputs
    settings.cancellation_token = CancellationToken()
    model = Model(settings)
    checks = []
    original = model._check_cancelled
    def cancel_after_first():
        checks.append(None)
        if len(checks) == 2:
            settings.cancellation_token.cancel()
        original()
    monkeypatch.setattr(model, "_check_cancelled", cancel_after_first)
    with pytest.raises(CancelledError):
        model._spatial_groups(features.id.to_numpy())
    assert len(checks) == 2


def test_benchmark_uses_identical_recorded_spatial_folds_and_preserves_inputs(spatial_inputs, tmp_path):
    import hashlib
    import shutil
    from scripts.benchmark_models import run_benchmark
    from sklearn.metrics import mean_squared_error

    settings, features = spatial_inputs
    data = tmp_path / "benchmark-data"
    data.mkdir()
    shutil.copyfile(settings.mastergrid, data / "rwa_mastergrid.tif")
    shutil.copyfile(settings.covariate["x"], data / "rwa_buildings_surface.tif")
    features[["id", "pop"]].to_csv(data / "RWA_2026.csv", index=False)
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data.iterdir()}
    output = tmp_path / "benchmark-output"
    metrics, metadata = run_benchmark(data, output, n_estimators=4, cv_folds=2, spatial_grid=(2, 1))
    predictions = pd.read_csv(output / "candidate_predictions.csv")
    assert len(metrics) == 5
    assert predictions.groupby("group").fold.nunique().eq(1).all()
    for fold in metadata["folds"]:
        assert set(fold["train_groups"]).isdisjoint(fold["test_groups"])
    for row in metrics.to_dict("records"):
        expected_rmse = np.sqrt(mean_squared_error(predictions.density, predictions[row["candidate"]]))
        assert row["rmse_density"] == pytest.approx(expected_rmse)
    assert metadata["source_sha256"] == before
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data.iterdir()}
    replay_output = tmp_path / "benchmark-replay"
    _, replay_metadata = run_benchmark(data, replay_output, n_estimators=4, spatial_grid=(2, 1),
                                       folds_from=output / "benchmark_metadata.json")
    assert replay_metadata["folds"] == metadata["folds"]
    replay_predictions = pd.read_csv(replay_output / "candidate_predictions.csv")
    np.testing.assert_array_equal(predictions.fold, replay_predictions.fold)
    changed = metadata.copy()
    changed["source_sha256"] = {"changed": "data"}
    bad_metadata = tmp_path / "invalid-benchmark.json"
    bad_metadata.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="different source"):
        run_benchmark(data, tmp_path / "invalid-replay", n_estimators=4, spatial_grid=(2, 1), folds_from=bad_metadata)
    with pytest.raises(ValueError, match="fresh"):
        run_benchmark(data, output, n_estimators=4)
