import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.pypoprf.population_summary import summarize_population
from core.pypoprf.utils.runtime import CancellationToken, CancelledError


@pytest.fixture
def summary_input(tmp_path):
    population = tmp_path / "population.tif"
    with rasterio.open(population, "w", driver="GTiff", width=2, height=2, count=1, dtype="float64",
                       crs="EPSG:3857", transform=from_origin(0, 2, 1, 1), nodata=np.nan) as out:
        out.write(np.array([[10.25, 20.25], [30.25, 40.25]]), 1)
    aoi = tmp_path / "aoi.geojson"
    gpd.GeoDataFrame(geometry=[box(0, 0, 2, 2)], crs="EPSG:3857").to_file(aoi)
    return {"schema_version": 1, "request_id": "b" * 32, "operation": "population_summary",
            "population_raster": str(population), "aoi": {"path": str(aoi)},
            "output_dir": str(tmp_path / "summary"), "inclusion": "cell_center", "units": "persons_per_pixel", "tile_size": 16}


def report(summary_input, **kwargs):
    return json.loads(summarize_population(summary_input, **kwargs).read_text())


def set_aoi(summary_input, geometry, reproject=False):
    frame = gpd.GeoDataFrame(geometry=geometry, crs="EPSG:3857")
    if reproject:
        frame = frame.to_crs("EPSG:4326")
    frame.to_file(summary_input["aoi"]["path"])


def test_supported_persons_sum_coverage_and_honest_precision(summary_input):
    before = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in
              (summary_input["population_raster"], summary_input["aoi"]["path"])}
    data = report(summary_input)
    result = data["summary"]
    assert result["sum_persons"] == 101 and result["display_persons"] == 101
    assert result["valid_cells"] == result["selected_cells"] == 4
    assert result["coverage_fraction"] == 1 and result["complete_coverage"]
    assert data["request_id"] == "b" * 32
    assert "estimate" in result["precision"]
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())


def test_overlap_union_counted_once_and_aoi_reprojected(summary_input):
    set_aoi(summary_input, [box(0, 0, 2, 2), box(0, 0, 1, 2)], reproject=True)
    assert report(summary_input)["summary"]["sum_persons"] == 101


def test_exact_cell_centers_not_all_touched_or_bresenham_edges(summary_input):
    set_aoi(summary_input, [box(0.01, 0.01, .49, 1.99)])
    result = report(summary_input)["summary"]
    assert result["selected_cells"] == 0 and result["sum_persons"] == 0
    assert result["coverage_fraction"] is None and not result["complete_coverage"]


def test_centers_on_boundary_are_explicitly_included(summary_input):
    set_aoi(summary_input, [box(.5, .5, 1.5, 1.5)])
    result = report(summary_input)["summary"]
    assert result["selected_cells"] == 4 and result["sum_persons"] == 101


def test_nodata_and_nonfinite_coverage_does_not_claim_complete_aoi(summary_input):
    with rasterio.open(summary_input["population_raster"], "r+") as source:
        source.write(np.array([[np.nan, 20.25], [np.inf, 40.25]]), 1)
    data = report(summary_input)
    assert data["summary"]["sum_persons"] == 60.5
    assert data["summary"]["valid_cells"] == 2 and data["summary"]["coverage_fraction"] == .5
    assert not data["summary"]["complete_coverage"] and data["warnings"]


def test_extent_outside_raster_never_presents_supported_sum_as_complete(summary_input):
    set_aoi(summary_input, [box(-1, -1, 3, 3)])
    result = report(summary_input)["summary"]
    assert result["sum_persons"] == 101 and result["coverage_fraction"] == 1
    assert result["aoi_extends_outside_raster"] and not result["complete_coverage"]


def test_negative_supported_population_rejected_without_publishing(summary_input):
    with rasterio.open(summary_input["population_raster"], "r+") as source:
        source.write(np.array([[-1., 2.], [3., 4.]]), 1)
    with pytest.raises(ValueError, match="nonnegative"):
        summarize_population(summary_input)
    assert not Path(summary_input["output_dir"]).exists()


def test_external_validity_mask_accounted_for_and_fingerprinted(summary_input):
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(summary_input["population_raster"], "r+") as source:
            source.write_mask(np.array([[0, 255], [255, 255]], dtype="uint8"))
    result = report(summary_input)
    assert result["summary"]["sum_persons"] == 90.75
    assert any(item["path"].endswith(".msk") for item in result["inputs"])


def test_summary_detects_new_sidecar_at_commit_and_never_deletes_it(summary_input):
    source = Path(summary_input["population_raster"])
    sidecar = Path(str(source) + ".aux.xml")
    def add_resource(percent, message):
        if percent == 95:
            sidecar.write_text("<PAMDataset/>")
    with pytest.raises(ValueError, match="resource set changed"):
        summarize_population(summary_input, progress=add_resource)
    assert sidecar.exists() and not Path(summary_input["output_dir"]).exists()


def test_summary_cancel_before_commit_cleans_only_its_owned_report_dir(summary_input):
    token = CancellationToken()
    def cancel(percent, message):
        if percent == 95:
            token.cancel()
    with pytest.raises(CancelledError):
        summarize_population(summary_input, token, cancel)
    assert not Path(summary_input["output_dir"]).exists() and Path(summary_input["population_raster"]).exists()


@pytest.mark.parametrize("changed", [False, True])
def test_selected_run_population_sha_is_bound_before_summary(summary_input, changed):
    path = Path(summary_input["population_raster"])
    summary_input["expected_population_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if changed:
        with rasterio.open(path, "r+") as source:
            source.write(np.full((2, 2), 100., dtype="float64"), 1)
        with pytest.raises(ValueError, match="differs from the selected run artifact"):
            summarize_population(summary_input)
        assert not Path(summary_input["output_dir"]).exists()
    else:
        assert report(summary_input)["summary"]["sum_persons"] == 101


@pytest.mark.parametrize("population,accepted", [(2**53, True), (2**53 + 1, False)])
def test_integer_storage_counts_cannot_be_silently_rounded_into_float64(summary_input, population, accepted):
    path = Path(summary_input["population_raster"])
    with rasterio.open(path, "w", driver="GTiff", count=1, width=1, height=1,
                       dtype="uint64", crs="EPSG:3857", transform=from_origin(0, 2, 1, 1)) as writer:
        writer.write(np.array([[population]], dtype="uint64"), 1)
    before = path.read_bytes()
    if accepted:
        assert report(summary_input)["summary"]["sum_persons"] == population
    else:
        with pytest.raises(ValueError, match="exactly representable"):
            summarize_population(summary_input)
        assert not Path(summary_input["output_dir"]).exists()
    assert path.read_bytes() == before


def test_projected_source_wrapping_after_geographic_reprojection_is_refused(summary_input):
    path = Path(summary_input["population_raster"])
    with rasterio.open(path, "w", driver="GTiff", width=360, height=2, count=1, dtype="float64",
                       crs="EPSG:4326", transform=from_origin(-180, 1, 1, 1)) as writer:
        writer.write(np.ones((2, 360), dtype="float64"), 1)
    set_aoi(summary_input, [box(20_000_000, -100_000, 20_200_000, 100_000)])
    with pytest.raises(ValueError, match="dateline-safe"):
        summarize_population(summary_input)
    assert not Path(summary_input["output_dir"]).exists()


@pytest.mark.parametrize("additional,accepted", [(1, True), (2, False)])
def test_exact_integer_total_range_is_guarded_even_when_each_cell_fits(summary_input, additional, accepted):
    path = Path(summary_input["population_raster"])
    with rasterio.open(path, "w", driver="GTiff", count=1, width=2, height=1,
                       dtype="uint64", crs="EPSG:3857", transform=from_origin(0, 2, 1, 1)) as writer:
        writer.write(np.array([[2**53 - 1, additional]], dtype="uint64"), 1)
    if accepted:
        assert report(summary_input)["summary"]["sum_persons"] == 2**53
    else:
        with pytest.raises(ValueError, match="total exceeds the exact float64 range"):
            summarize_population(summary_input)
        assert not Path(summary_input["output_dir"]).exists()


def test_file_symlink_source_is_refused_before_dropping_alias_sidecars(summary_input, tmp_path):
    alias = tmp_path / "alias.tif"
    try:
        alias.symlink_to(summary_input["population_raster"])
    except OSError:
        pytest.skip("Platform/user cannot create symbolic links; fake-link boundary tested separately")
    Path(str(alias) + ".msk").write_bytes(b"alias-specific mask")
    summary_input["population_raster"] = str(alias)
    with pytest.raises(ValueError, match="File-symlink sources"):
        summarize_population(summary_input)
    assert not Path(summary_input["output_dir"]).exists()


def test_file_symlink_boundary_is_checked_before_resolve_without_os_privileges(summary_input, monkeypatch):
    source = Path(summary_input["population_raster"])
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == source or original(self))
    with pytest.raises(ValueError, match="File-symlink sources"):
        summarize_population(summary_input)
    assert not Path(summary_input["output_dir"]).exists()


@pytest.mark.parametrize("key,value", [("units", "people_per_km2"), ("inclusion", "all_touched"), ("tile_size", True)])
def test_unknown_units_inclusion_and_invalid_tile_size_are_refused(summary_input, key, value):
    summary_input[key] = value
    with pytest.raises(ValueError):
        summarize_population(summary_input)
    assert not Path(summary_input["output_dir"]).exists()
