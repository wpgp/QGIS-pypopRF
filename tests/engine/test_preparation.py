import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, Polygon

from core.pypoprf.preparation import prepare_or_inspect
from core.pypoprf.config.settings import Settings
from core.pypoprf.utils.runtime import CancellationToken, CancelledError


def raster(path, data, transform=None, crs="EPSG:3857", nodata=None, mask=None):
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1,
                           dtype=data.dtype, crs=crs, transform=transform or from_origin(0, 2, 1, 1), nodata=nodata) as dst:
            dst.write(data, 1)
            if mask is not None:
                dst.write_mask(mask.astype("uint8") * 255)
    return path


def polygons(path, geometries, ids=None, crs="EPSG:3857", layer=None):
    frame = gpd.GeoDataFrame({"zone": ids or list(range(1, len(geometries) + 1))}, geometry=geometries, crs=crs)
    frame.to_file(path, layer=layer)
    return path


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    zones = raster(source / "zones.tif", np.array([[1, 1], [2, 2]], dtype="int32"))
    covariate = raster(source / "feature.tif", np.array([[1., 2.], [3., 4.]], dtype="float32"))
    census = source / "census.csv"
    census.write_text("zone,people\n2,20\n1,10\n", encoding="utf-8")
    return {"schema_version": 1, "request_id": "a" * 32, "operation": "prepare",
            "output_dir": str(tmp_path / "derived"), "reference_raster": str(zones),
            "census": {"path": str(census), "id_column": "zone", "population_column": "people"},
            "covariates": [{"name": "feature", "path": str(covariate), "quantity": "continuous", "resampling": "nearest"}],
            "tile_size": 16}


def inspect(request):
    request = dict(request, operation="inspect")
    return json.loads(prepare_or_inspect(request).read_text())


def hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


def test_new_self_contained_project_passes_settings_and_preserves_sources(inputs):
    source = Path(inputs["reference_raster"]).parent
    before = hashes(source)
    report = json.loads(prepare_or_inspect(inputs).read_text())
    assert report["ready"] and report["request_id"] == "a" * 32
    settings = Settings.from_file(report["config_path"])
    root = Path(inputs["output_dir"])
    assert settings.work_dir == root and settings.data_dir == root / "data"
    for path in [settings.mastergrid, settings.census["path"], *settings.covariate.values()]:
        assert Path(path).is_relative_to(root)
    assert report["coverage"]["zones"]["1"]["eligible"] == 2
    assert hashes(source) == before
    assert not list(root.glob(".scratch-*"))


def test_reports_each_source_before_slow_raster_normalization(inputs, monkeypatch):
    from core.pypoprf import preparation
    messages, starts = [], []
    original = preparation._normalized
    def normalize(path, *args, **kwargs):
        assert messages and Path(path).name in messages[-1][1]
        assert "Validating source raster" in messages[-1][1]
        starts.append(str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(preparation, "_normalized", normalize)
    report = prepare_or_inspect(dict(inputs, operation="inspect"),
                                progress=lambda value, message: messages.append((value,message)))
    assert json.loads(report.read_text())["ready"]
    assert starts == [inputs["reference_raster"], inputs["covariates"][0]["path"]]
    assert [value for value,_ in messages] == sorted(value for value,_ in messages)


def test_source_stage_cancellation_prevents_normalization(inputs, monkeypatch):
    from core.pypoprf import preparation
    token = CancellationToken()
    normalized = []
    monkeypatch.setattr(preparation, "_normalized", lambda *args: normalized.append(args))
    def progress(value, message):
        if "Validating source raster" in message:
            token.cancel()
    with pytest.raises(CancelledError):
        prepare_or_inspect(dict(inputs, operation="inspect"), token=token, progress=progress)
    assert not normalized


def test_reference_nodata_is_only_grid_template_not_implicit_study_mask(inputs):
    root = Path(inputs["reference_raster"]).parent
    zones = inputs["reference_raster"]
    reference = raster(root / "template.tif", np.array([[np.nan, 1.], [np.nan, 1.]]), nodata=np.nan)
    inputs.update(reference_raster=str(reference), zone_raster=zones)
    report = json.loads(prepare_or_inspect(inputs).read_text())
    assert report["ready"]
    with rasterio.open(report["derived_paths"]["zones"]) as result:
        assert np.array_equal(result.read(1), [[1, 1], [2, 2]])


@pytest.mark.parametrize("quantity,values,ready", [("categorical", [[0, 1], [1, 0]], True),
                                                  ("categorical", [[1, 2], [3, 4]], False),
                                                  ("count", [[1, -2], [3, 4]], False),
                                                  ("continuous", [[1, -2], [3, 4]], True)])
def test_explicit_quantity_semantics_binary_counts_and_signed_continuous(inputs, quantity, values, ready):
    raster(Path(inputs["covariates"][0]["path"]), np.asarray(values, dtype="float64"))
    inputs["covariates"][0]["quantity"] = quantity
    report = inspect(inputs)
    assert report["ready"] is ready
    if not ready:
        assert any(item["code"] == "raster_values" for item in report["errors"])


def test_count_resampling_is_refused_instead_of_silent_average(inputs):
    raster(Path(inputs["covariates"][0]["path"]), np.ones((4, 4), dtype="float64"), from_origin(0, 2, .5, .5))
    inputs["covariates"][0]["quantity"] = "count"
    report = inspect(inputs)
    assert not report["ready"] and any(item["code"] == "count_resampling" for item in report["errors"])


def test_count_aligned_passthrough_and_continuous_average_are_explicit(inputs):
    path = Path(inputs["covariates"][0]["path"])
    raster(path, np.arange(16, dtype="float64").reshape(4, 4), from_origin(0, 2, .5, .5))
    inputs["covariates"][0]["resampling"] = "average"
    report = json.loads(prepare_or_inspect(inputs).read_text())
    with rasterio.open(report["derived_paths"]["feature"]) as result:
        assert np.allclose(result.read(1), [[2.5, 4.5], [10.5, 12.5]])


def test_external_masks_and_nonfinite_values_preserved_without_copying_sidecars(inputs):
    path = Path(inputs["covariates"][0]["path"])
    raster(path, np.array([[0., 999.], [np.inf, 4.]]), mask=np.array([[1, 0], [1, 1]]))
    before = hashes(path.parent)
    report = json.loads(prepare_or_inspect(inputs).read_text())
    with rasterio.open(report["derived_paths"]["feature"]) as result:
        values = result.read(1, masked=True)
        assert values[0, 0] == 0 and values.mask.tolist() == [[False, True], [True, False]]
        assert len(result.files) == 1
    assert str(path) + ".msk" in [record["path"] for record in report["inputs"]]
    assert hashes(path.parent) == before


@pytest.mark.parametrize("value", [1.5, float(2**53 + 2)])
def test_invalid_zone_ids_rejected(inputs, value):
    raster(Path(inputs["reference_raster"]), np.array([[value, 1.], [2., 2.]]))
    report = inspect(inputs)
    assert not report["ready"] and any("exact integers" in item["message"] for item in report["errors"])


def test_large_int64_id_cannot_round_into_supported_range(inputs):
    raster(Path(inputs["reference_raster"]), np.array([[2**53 + 1, 1], [2, 2]], dtype="int64"))
    assert not inspect(inputs)["ready"]


@pytest.mark.parametrize("problem", ["overlap", "invalid", "duplicate", "clipped", "mismatched_ids"])
def test_polygon_geometry_ids_and_full_footprint_are_strict(inputs, problem):
    geometries, ids = [box(0, 1, 2, 2), box(0, 0, 2, 1)], [1, 2]
    if problem == "overlap":
        geometries[1] = box(0, 0, 2, 1.5)
    elif problem == "invalid":
        geometries[1] = Polygon([(0, 0), (2, 1), (0, 1), (2, 0), (0, 0)])
    elif problem == "duplicate":
        ids = [1, 1]
    elif problem == "clipped":
        geometries[1] = box(-1, 0, 2, 1)
    else:
        ids = [1, 3]
    path = polygons(Path(inputs["reference_raster"]).parent / "boundaries.geojson", geometries, ids)
    inputs["census_polygons"] = {"path": str(path), "id_column": "zone"}
    report = inspect(inputs)
    assert not report["ready"] and report["errors"]
    assert not Path(inputs["output_dir"]).joinpath("config.yaml").exists()


def test_polygon_grid_rasterization_uses_keyed_shuffled_census(inputs):
    path = polygons(Path(inputs["reference_raster"]).parent / "boundaries.geojson",
                    [box(0, 0, 2, 1), box(0, 1, 2, 2)], [2, 1])
    inputs["census_polygons"] = {"path": str(path), "id_column": "zone"}
    report = json.loads(prepare_or_inspect(inputs).read_text())
    with rasterio.open(report["derived_paths"]["zones"]) as source:
        assert np.array_equal(source.read(1), [[1, 1], [2, 2]])


def test_polygon_dateline_wrap_is_checked_after_reprojection(inputs):
    raster(Path(inputs["reference_raster"]), np.ones((2, 360), dtype="uint8"), from_origin(-180, 1, 1, 1), crs="EPSG:4326")
    path = polygons(Path(inputs["reference_raster"]).parent / "wrapped.geojson",
                    [box(20_000_000, -100_000, 20_200_000, 100_000)], [1])
    inputs["census_polygons"] = {"path": str(path), "id_column": "zone"}
    data = inspect(inputs)
    assert not data["ready"] and any("dateline-safe" in item["message"] for item in data["errors"])


@pytest.mark.parametrize("population,ready", [(0, True), (10, False)])
def test_constraint_is_separate_allocation_support_not_training_mask(inputs, population, ready):
    Path(inputs["census"]["path"]).write_text(f"zone,people\n1,{population}\n2,20\n")
    path = raster(Path(inputs["reference_raster"]).parent / "constraint.tif", np.array([[0, 0], [1, 1]], dtype="uint8"))
    inputs["constrain"] = {"path": str(path), "quantity": "categorical", "resampling": "nearest"}
    report = inspect(inputs)
    assert report["ready"] is ready
    assert report["coverage"]["zones"]["1"]["eligible"] == 2
    assert report["coverage"]["zones"]["1"]["constrained_eligible"] == 0


@pytest.mark.parametrize("reserved", ["dens", "eligible_pixel_count", "feature_avg"])
def test_census_training_columns_conflicts_detected_during_inspect(inputs, reserved):
    Path(inputs["census"]["path"]).write_text(f"zone,{reserved}\n1,10\n2,20\n")
    inputs["census"]["population_column"] = reserved
    report = inspect(inputs)
    assert not report["ready"] and any(item["code"] == "training_columns" for item in report["errors"])


def test_multiple_metadata_and_schema_errors_are_reported_without_analysis(inputs):
    raster(Path(inputs["reference_raster"]), np.array([[1, 1], [2, 2]], dtype="int32"), crs=None)
    Path(inputs["census"]["path"]).write_text("zone,people,people\n1,10,10\n")
    inputs["covariates"][0]["resampling"] = "cubic"
    report = inspect(inputs)
    assert not report["ready"] and len(report["errors"]) >= 3
    assert report["inputs"]


@pytest.mark.parametrize("added", [".aux.xml", ".msk", ".tfw"])
def test_new_source_sidecar_before_commit_prevents_publication(inputs, added):
    source = Path(inputs["covariates"][0]["path"])
    def mutate(percent, message):
        if percent == 95:
            sidecar = source.with_suffix(added) if added == ".tfw" else Path(str(source) + added)
            sidecar.write_bytes(b"late source resource")
    with pytest.raises(ValueError, match="resource set changed"):
        prepare_or_inspect(inputs, progress=mutate)
    assert not Path(inputs["output_dir"]).exists()


def test_changed_source_bytes_and_cancel_preserve_sources_and_prior_outputs(inputs, tmp_path):
    output = Path(inputs["output_dir"])
    output.mkdir()
    (output / "keep.bin").write_bytes(b"prior")
    with pytest.raises(ValueError, match="already exists"):
        prepare_or_inspect(inputs)
    assert (output / "keep.bin").read_bytes() == b"prior"
    inputs["output_dir"] = str(tmp_path / "cancelled")
    before = hashes(Path(inputs["reference_raster"]).parent)
    token = CancellationToken()
    def cancel(percent, message):
        if percent >= 10:
            token.cancel()
    with pytest.raises(CancelledError):
        prepare_or_inspect(inputs, token, cancel)
    assert not Path(inputs["output_dir"]).exists()
    assert hashes(Path(inputs["reference_raster"]).parent) == before


def test_multilayer_vector_requires_explicit_layer(inputs):
    path = Path(inputs["reference_raster"]).parent / "layers.gpkg"
    polygons(path, [box(0, 0, 2, 1), box(0, 1, 2, 2)], [2, 1], layer="zones")
    polygons(path, [box(0, 0, 1, 1)], [9], layer="other")
    inputs["census_polygons"] = {"path": str(path), "id_column": "zone"}
    assert not inspect(inputs)["ready"]


def test_unknown_raster_background_ids_are_reported_not_silently_reassigned(inputs):
    path = Path(inputs["reference_raster"])
    raster(path, np.array([[0, 1], [2, 2]], dtype="int32"))
    report = json.loads(prepare_or_inspect(inputs).read_text())
    assert report["ready"] and report["coverage"]["unknown_grid_ids"] == [0]
    assert report["coverage"]["unknown_grid_pixel_count"] == 1
    assert any(item["code"] == "unknown_grid_ids" for item in report["warnings"])
    with rasterio.open(report["derived_paths"]["zones"]) as source:
        assert source.read(1)[0, 0] == 0


def test_all_source_reads_are_windowed_and_bounded(inputs, monkeypatch):
    source_paths = {Path(inputs["reference_raster"]), Path(inputs["covariates"][0]["path"])}
    zones = np.repeat([[1], [2]], 20, axis=0).repeat(40, axis=1).astype("int32")
    raster(Path(inputs["reference_raster"]), zones, from_origin(0, 40, 1, 1))
    raster(Path(inputs["covariates"][0]["path"]), np.ones((40, 40), dtype="float64"), from_origin(0, 40, 1, 1))
    original = rasterio.open
    seen = []
    class Reader:
        def __init__(self, underlying):
            self.underlying = underlying
        def __getattr__(self, name):
            return getattr(self.underlying, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.underlying.__exit__(*args)
        def read(self, *args, **kwargs):
            window = kwargs.get("window")
            assert window is not None and window.width <= 16 and window.height <= 16
            seen.append(window)
            return self.underlying.read(*args, **kwargs)
    def tracked(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return Reader(result) if Path(path) in source_paths and (not args or args[0] == "r") else result
    monkeypatch.setattr(rasterio, "open", tracked)
    assert inspect(inputs)["ready"]
    assert len(seen) >= 18


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junction safety")
def test_redirected_scratch_is_never_recursively_deleted(inputs, tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.bin").write_bytes(b"must remain")
    redirected = []
    def replace_scratch(percent, message):
        if percent == 95 and not redirected:
            scratch = next(Path(inputs["output_dir"]).glob(".scratch-*"))
            original = scratch.with_name("retained-original-scratch")
            scratch.rename(original)
            subprocess.run(["cmd", "/c", "mklink", "/J", str(scratch), str(foreign)], check=True, capture_output=True)
            redirected.append(scratch)
    with pytest.raises(ValueError, match="replaced or redirected"):
        prepare_or_inspect(inputs, progress=replace_scratch)
    assert (foreign / "keep.bin").read_bytes() == b"must remain"
    assert not (Path(inputs["output_dir"]) / "report.json").exists()
    # Remove only the exact empty junction entry (never its target).
    redirected[0].rmdir()


def test_tools_import_is_headless_and_does_not_change_callers_environment():
    script = "import os,sys; before=dict(os.environ); import core.pypoprf.tools; assert dict(os.environ)==before; assert not any(x in sys.modules for x in ('numpy','qgis','rasterio','geopandas','sklearn'))"
    child = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=dict(os.environ, OMP_NUM_THREADS="64"))
    assert child.returncode == 0, child.stderr


@pytest.mark.parametrize("mutation", [None, "census", "new_sidecar"])
def test_preparation_binds_to_the_reviewed_file_content_snapshot(inputs, tmp_path, mutation):
    preview = inspect(inputs)
    assert preview["ready"]
    inputs["output_dir"] = str(tmp_path / "prepared_after_preview")
    inputs["expected_inputs"] = preview["inputs"]
    if mutation == "census":
        Path(inputs["census"]["path"]).write_text("zone,people\n2,200\n1,100\n")
    elif mutation == "new_sidecar":
        Path(inputs["covariates"][0]["path"] + ".aux.xml").write_text("<PAMDataset/>")
    if mutation is None:
        assert json.loads(prepare_or_inspect(inputs).read_text())["ready"]
    else:
        with pytest.raises(ValueError, match="Inputs changed since compatibility check; inspect again"):
            prepare_or_inspect(inputs)
        assert not Path(inputs["output_dir"]).exists()


def test_real_tools_cli_caps_loaded_native_pools_in_its_owned_process(inputs, tmp_path):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(dict(inputs, operation="inspect")), encoding="utf-8")
    script = "import runpy,sys; sys.argv=['tools','--request',sys.argv[1]];\ntry: runpy.run_module('core.pypoprf.tools',run_name='__main__')\nexcept SystemExit as exc: assert exc.code==0\nimport sklearn,scipy.linalg; from threadpoolctl import threadpool_info; pools=threadpool_info(); assert pools and all(p['num_threads']<=1 for p in pools),pools"
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(path)], capture_output=True,
                           text=True, timeout=30, env=dict(os.environ, OMP_NUM_THREADS="64", OPENBLAS_NUM_THREADS="64"))
    assert child.returncode == 0, child.stdout + child.stderr


@pytest.mark.parametrize("raw", ['{"operation":"inspect","operation":"prepare"}', '{"operation":"inspect","schema_version":NaN}', '[]'])
def test_tools_json_request_failures_are_structured_and_non_destructive(tmp_path, raw):
    request = tmp_path / "request.json"
    request.write_text(raw)
    completed = subprocess.run([sys.executable, "-m", "core.pypoprf.tools", "--request", str(request)], capture_output=True, text=True)
    event = json.loads(completed.stdout.splitlines()[-1])
    assert completed.returncode == 1 and event["status"] == "failed" and event["report_path"] is None
    assert list(tmp_path.iterdir()) == [request]


@pytest.mark.parametrize("name", ["x" * 241, "bad\nname", "bad\x7fname"])
def test_covariate_names_have_bounded_control_free_report_contract(inputs, name):
    inputs["covariates"][0]["name"] = name
    report = inspect(inputs)
    assert not report["ready"] and any(item["code"] == "raster_policy" for item in report["errors"])


def test_report_byte_limit_never_publishes_an_unreadable_completed_report(tmp_path):
    from core.pypoprf.preparation import write_json
    path = tmp_path / "report.json"
    with pytest.raises(ValueError, match="4 MiB interface limit"):
        write_json(path, {"oversized": "x" * (4 * 1024 * 1024)})
    assert not path.exists()


def test_high_cardinality_unknown_zone_counts_are_exact_and_cancellable(inputs):
    path = Path(inputs["reference_raster"])
    # Wrong-role but integer-valued input: most cells are unmatched identifiers.
    values = np.arange(1, 65 * 65 + 1, dtype="int32").reshape(65, 65)
    raster(path, values, from_origin(0, 65, 1, 1))
    raster(Path(inputs["covariates"][0]["path"]), np.ones((65, 65), dtype="float64"), from_origin(0, 65, 1, 1))
    result = inspect(inputs)
    assert result["coverage"]["unknown_id_count"] == 65 * 65 - 2
    assert result["coverage"]["unknown_grid_pixel_count"] == 65 * 65 - 2


def test_file_symlink_reference_is_rejected_before_resolve(inputs, monkeypatch):
    source = Path(inputs["reference_raster"])
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == source or original(self))
    with pytest.raises(ValueError, match="File-symlink sources"):
        prepare_or_inspect(inputs)
    assert not Path(inputs["output_dir"]).exists()
