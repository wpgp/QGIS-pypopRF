"""Explicit, non-destructive preparation on a user-selected reference grid.

Only the engine imports this module. Raster data are processed in bounded tiles;
vector geometries and the census table must fit memory (no silent repair).
"""
from contextlib import contextmanager, ExitStack
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from shapely.geometry import Polygon, box
import yaml

from .utils.raster import valid_mask, validate_alignment, validate_census
from .utils.runtime import atomic_output, check_cancelled


def issue(code, message, path=None):
    return {"code": code, "message": str(message)[:4000], "path": str(path) if path else None}


def check_keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"Expected fields {sorted(required)}; allowed fields {sorted(allowed)}")


def local_file(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("Input paths must be absolute local file paths")
    supplied = Path(value)
    if supplied.is_symlink():
        raise ValueError("File-symlink sources may have different GDAL sidecars; select the canonical file or export an explicit copy")
    path = supplied.resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Not a local regular file: {path}")
    return path


def tiles(width, height, size=512):
    for row in range(0, height, size):
        for col in range(0, width, size):
            yield Window(col, row, min(size, width - col), min(size, height - row))


def fingerprint(path, token=None):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancelled(token)
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Input changed during hashing: {path}")
    return {"path": str(path.resolve()), "bytes": after.st_size, "mtime_ns": after.st_mtime_ns,
            "sha256": digest.hexdigest()}


def vector_resources(path):
    path = Path(path)
    if path.suffix.lower() == ".shp":
        return [candidate.resolve() for candidate in path.parent.iterdir()
                if candidate.is_file() and (candidate.stem.casefold() == path.stem.casefold()
                   or candidate.name.casefold() in {path.name.casefold() + ".xml", path.with_suffix(".dbf").name.casefold() + ".xml"})]
    if path.suffix.lower() == ".gpkg" and any(Path(str(path) + ext).exists() for ext in ("-wal", "-shm", "-journal")):
        raise ValueError("Close the active GeoPackage writer before preparation")
    return [path]


def raster_resources(path):
    with rasterio.open(path) as dataset:
        paths = {Path(item).resolve() for item in dataset.files}
    # Include explicit world files even when GDAL does not list them as resources.
    path = Path(path)
    paths.add(path.resolve())
    paths.update(candidate.resolve() for candidate in
                 (Path(str(path) + ".aux.xml"), Path(str(path) + ".msk"), Path(str(path) + ".ovr"),
                  path.with_suffix(".tfw"), path.with_suffix(".wld"), path.with_suffix(".tifw"))
                 if candidate.exists())
    if any(not item.is_file() for item in paths):
        raise ValueError("Raster resources must be regular local files")
    return sorted(paths)


def declared_resources(request):
    """Re-enumerate resources, including sidecars added after initial inspection."""
    resources = set()
    raster_paths = [request.get(key) for key in ("reference_raster", "zone_raster", "population_raster")]
    for spec in request.get("covariates", []):
        if isinstance(spec, dict):
            raster_paths.append(spec.get("path"))
    raster_paths += [request[key].get("path") for key in ("mask", "constrain")
                     if isinstance(request.get(key), dict)]
    for value in raster_paths:
        if isinstance(value, str) and Path(value).is_absolute() and Path(value).is_file():
            path = local_file(value)
            try:
                resources.update(raster_resources(path))
            except rasterio.errors.RasterioError:
                resources.add(path)
    for key in ("census_polygons", "aoi"):
        spec = request.get(key)
        if isinstance(spec, dict) and isinstance(spec.get("path"), str) and Path(spec["path"]).is_absolute() and Path(spec["path"]).is_file():
            resources.update(vector_resources(local_file(spec["path"])))
    spec = request.get("census")
    if isinstance(spec, dict) and isinstance(spec.get("path"), str) and Path(spec["path"]).is_absolute() and Path(spec["path"]).is_file():
        path = local_file(spec["path"])
        resources.add(path)
        resources.update(item.resolve() for item in (path.with_suffix(".csvt"), path.with_suffix(".prj")) if item.exists())
    return resources


def verify_resource_set(request, records, token=None):
    if {Path(record["path"]) for record in records} != declared_resources(request):
        raise ValueError("Input resource set changed during the operation (added/removed sidecar or dataset resource)")
    verify_sources(records, token)


def verify_inspected_inputs(expected, records):
    if not isinstance(expected, list) or not expected:
        raise ValueError("expected_inputs must be the nonempty inspected input fingerprint list")
    indexed = {}
    for record in expected:
        check_keys(record, {"path", "bytes", "sha256", "mtime_ns"}, {"path", "bytes", "sha256"})
        if (not isinstance(record["path"], str) or not Path(record["path"]).is_absolute()
                or type(record["bytes"]) is not int or record["bytes"] < 0
                or not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
            raise ValueError("Malformed expected_inputs fingerprint")
        path = Path(record["path"]).resolve()
        if path in indexed:
            raise ValueError("Duplicate expected_inputs path")
        indexed[path] = record["bytes"], record["sha256"]
    fresh = {Path(record["path"]): (record["bytes"], record["sha256"]) for record in records}
    if indexed != fresh:
        raise ValueError("Inputs changed since compatibility check; inspect again before preparing")


def verify_sources(records, token=None):
    for record in records:
        current = fingerprint(record["path"], token)
        if current != record:
            raise ValueError(f"Source changed during the operation: {record['path']}")


def is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def owned_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def assert_owned(path, identity, parent=None):
    if (is_link(path) or not path.is_dir() or path.resolve() != path
            or owned_identity(path) != identity or (parent is not None and path.parent.resolve() != parent)):
        raise ValueError("Owned output directory was replaced or redirected; refusing further publication/cleanup")


def remove_owned(path, identity, parent):
    if not path.exists() and not is_link(path):
        return True
    try:
        assert_owned(path, identity, parent)
        if any(is_link(item) for item in path.rglob("*")):
            return False
    except (ValueError, OSError):
        return False
    shutil.rmtree(path)
    return True


@contextmanager
def new_output(value, input_paths=()):
    """Reserve a NEW directory; a final atomic report is its commit marker.

    Failures remove only our exact newly-created directory. No existing directory
    is reused or renamed over; consumers must wait for the complete report/event.
    """
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("output_dir must be an absolute NEW directory")
    requested = Path(value)
    root = requested.resolve()
    if requested.exists() or requested.is_symlink() or (hasattr(requested, "is_junction") and requested.is_junction()):
        raise ValueError("Output directory already exists; select a NEW derived directory")
    if any(Path(path).resolve().is_relative_to(root) for path in input_paths):
        raise ValueError("Output directory cannot contain an input resource")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=False)
    identity = owned_identity(root)
    complete = False
    try:
        yield root
        complete = True
    finally:
        if not complete:
            remove_owned(root, identity, root.parent)


def write_json(path, document, token=None):
    serialized = json.dumps(document, indent=2, allow_nan=False)
    if len(serialized.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("Tool report exceeds the 4 MiB interface limit; use shorter paths/fields or fewer inputs")
    with atomic_output(path, token) as staging:
        staging.write_text(serialized, encoding="utf-8")


def read_polygons(spec, reference_crs=None, token=None):
    check_keys(spec, {"path", "layer", "id_column"}, {"path"})
    path = local_file(spec["path"])
    if path.suffix.lower() not in {".shp", ".gpkg", ".geojson", ".json"}:
        raise ValueError("Supported local polygon formats: GeoJSON, GeoPackage and shapefile")
    check_cancelled(token)
    layers = gpd.list_layers(path)
    layer = spec.get("layer")
    if layer is None and len(layers) != 1:
        raise ValueError("Select an explicit vector layer for a multi-layer dataset")
    if layer is not None and (not isinstance(layer, str) or layer not in layers["name"].tolist()):
        raise ValueError("Unknown vector layer")
    frame = gpd.read_file(path, layer=layer)
    if frame.crs is None or frame.empty:
        raise ValueError("Polygon data must be nonempty and define a CRS")
    if (frame.geometry.isna().any() or frame.geometry.is_empty.any() or
            not frame.geometry.is_valid.all() or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all()):
        raise ValueError("All geometries must be valid nonempty Polygon/MultiPolygon; no automatic repair")
    if not np.isfinite(frame.total_bounds).all():
        raise ValueError("Polygon coordinates must be finite")
    def check_geographic_extent(candidate):
        if not candidate.crs.is_geographic:
            return
        geographic = candidate if candidate.crs.to_epsg() == 4326 else candidate.to_crs("EPSG:4326")
        for geometry in geographic.geometry:
            west, south, east, north = geometry.bounds
            if west < -180 or east > 180 or south < -90 or north > 90 or east - west > 180:
                raise ValueError("Antimeridian-spanning/out-of-range polygons need an explicit dateline-safe workflow outside this tool")
    check_geographic_extent(frame)
    if reference_crs is not None:
        frame = frame.to_crs(reference_crs)
        if not frame.geometry.is_valid.all() or not np.isfinite(frame.total_bounds).all():
            raise ValueError("Polygon reprojection produced invalid/nonfinite geometry")
        check_geographic_extent(frame)
    check_cancelled(token)
    return frame


def raster_description(path):
    with rasterio.open(path) as source:
        if source.count != 1 or source.crs is None or np.issubdtype(np.dtype(source.dtypes[0]), np.complexfloating):
            raise ValueError("Raster must have one real-valued band and a declared CRS")
        affine = np.array(tuple(source.transform), dtype=float)
        if not np.isfinite(affine).all() or source.transform.determinant == 0:
            raise ValueError("Raster affine transform is nonfinite or singular")
        if source.gcps[0] or source.rpcs:
            raise ValueError("GCP/RPC rasters must be explicitly orthorectified before preparation")
        return {"path": str(path), "crs": source.crs.to_string(), "width": source.width,
                "height": source.height, "transform": list(source.transform), "dtype": source.dtypes[0],
                "nodata": str(source.nodata) if source.nodata is not None else None,
                "resources": [str(item) for item in raster_resources(path)]}


def output_profile(reference):
    return {"driver": "GTiff", "count": 1, "width": reference.width, "height": reference.height,
            "transform": reference.transform, "crs": reference.crs, "dtype": "float64", "nodata": np.nan,
            "compress": "deflate", "tiled": True, "blockxsize": 256, "blockysize": 256, "BIGTIFF": "IF_SAFER"}


def _normalized(path, destination, size, token, categorical=False, ids=False, counts=False):
    with rasterio.open(path) as source:
        with atomic_output(destination, token) as staging:
            with rasterio.open(staging, "w", **output_profile(source)) as writer:
                for window in tiles(source.width, source.height, size):
                    check_cancelled(token)
                    array = source.read(1, window=window, masked=True)
                    valid = valid_mask(array)
                    raw = np.asarray(np.ma.getdata(array))
                    if ids and (((raw[valid] < -(2 ** 53)) | (raw[valid] > 2 ** 53)).any()
                                or (raw[valid] != np.floor(raw[valid])).any()):
                        raise ValueError("Zone IDs must be exact integers within ±2**53")
                    values = np.asarray(raw, dtype="float64")
                    if counts and ((values[valid] < 0).any() or
                                   (np.issubdtype(raw.dtype, np.integer) and (raw[valid] > 2 ** 53).any())):
                        raise ValueError("Count quantities must be nonnegative and integer storage exactly representable as float64")
                    if categorical and not np.isin(values[valid], [0, 1]).all():
                        raise ValueError("Categorical covariates/masks must be binary 0/1 indicators; explicitly encode class indicators first")
                    writer.write(np.where(valid, values, np.nan), 1, window=window)


def _census(spec):
    check_keys(spec, {"path", "id_column", "population_column"}, {"path", "id_column", "population_column"})
    path = local_file(spec["path"])
    if path.suffix.lower() != ".csv":
        raise ValueError("Census must be an explicit CSV table")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), [])
    if (not header or len(header) != len(set(header)) or any(not column.strip() or len(column) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in column) for column in header)):
        raise ValueError("CSV column names must be nonempty, unique, at most 256 characters and contain no controls")
    data = validate_census(pd.read_csv(path), spec["id_column"], spec["population_column"])
    return data, header


def prepare_or_inspect(request, token=None, progress=None):
    """Return the committed report path; quality failures are reported by inspect."""
    allowed = {"schema_version", "operation", "output_dir", "request_id", "expected_inputs", "reference_raster", "census", "zone_raster",
               "census_polygons", "covariates", "mask", "constrain", "tile_size"}
    check_keys(request, allowed, {"schema_version", "operation", "output_dir", "reference_raster", "census", "covariates"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["operation"] not in {"inspect", "prepare"}:
        raise ValueError("Unsupported request schema/operation")
    size = request.get("tile_size", 512)
    if type(size) is not int or not 16 <= size <= 2048:
        raise ValueError("tile_size must be an integer between 16 and 2048")
    if "zone_raster" in request and "census_polygons" in request:
        raise ValueError("Choose either an existing zone raster or census polygons")
    if not isinstance(request["covariates"], list) or not request["covariates"] or len(request["covariates"]) > 32:
        raise ValueError("Between 1 and 32 explicitly typed covariates are required")
    report = {"schema_version": 1, "operation": request["operation"], "request_id": request.get("request_id"), "ready": False,
              "errors": [], "warnings": [], "rasters": [], "coverage": {}, "derived_paths": {},
              "policies": {"zone_rasterization": "GDAL center/Bresenham, all_touched=false",
                           "reference_grid": "spatial template only; its data/NoData are not a study mask",
                           "warp_tolerance_pixels": 0.125,
                           "invalid_data": "finite values AND original GDAL validity; output NaN NoData",
                           "count_warp": "forbidden; aligned nearest passthrough only"}}
    errors, resources, raster_specs, census, polygons, reference = report["errors"], declared_resources(request), [], None, None, None
    sources = [fingerprint(path, token) for path in sorted(resources)]
    if "expected_inputs" in request:
        if request["operation"] != "prepare":
            raise ValueError("expected_inputs is supported only for preparing an inspected snapshot")
        verify_inspected_inputs(request["expected_inputs"], sources)
    report["inputs"] = sources
    output_root, output_id, scratch, scratch_id = None, None, None, None
    def stage(percent, message):
        check_cancelled(token)
        if progress:
            progress(percent, message)
        check_cancelled(token)
        if output_root is not None:
            assert_owned(output_root, output_id)
        if scratch is not None and scratch.exists():
            assert_owned(scratch, scratch_id, output_root)
    def attempt(code, callback, path=None):
        try:
            return callback()
        except (ValueError, OSError, KeyError, TypeError, rasterio.errors.RasterioError) as exc:
            errors.append(issue(code, exc, path))
            return None
    stage(0, "Inspecting declared inputs and policies")
    reference = attempt("reference_grid", lambda: local_file(request["reference_raster"]), request["reference_raster"])
    if reference:
        description = attempt("reference_grid", lambda: raster_description(reference), reference)
        if description:
            report["reference_grid"] = description
            resources.update(map(Path, description["resources"]))
    census_result = attempt("census", lambda: _census(request["census"]), request["census"].get("path") if isinstance(request["census"], dict) else None)
    if census_result:
        census, header = census_result
        report["recommended_columns"] = {"available": header, "id": request["census"]["id_column"],
                                         "population": request["census"]["population_column"]}
        resources.add(local_file(request["census"]["path"]))
    names = set()
    for index, spec in enumerate(request["covariates"] + [dict(request[key], name=key) for key in ("mask", "constrain") if key in request]):
        def validate_spec(spec=spec, index=index):
            check_keys(spec, {"name", "path", "quantity", "resampling"}, {"name", "path", "quantity", "resampling"})
            name = spec["name"]
            if (not isinstance(name, str) or not name.strip() or len(name) > 240
                    or any(ord(char) < 32 or ord(char) == 127 for char in name) or name.casefold() in names):
                raise ValueError("Raster names must be nonempty, at most 240 characters, control-free and case-insensitively unique")
            if name.casefold() in {"zones", "dens", "eligible_pixel_count"} or (index < len(request["covariates"]) and name.casefold() in {"mask", "constrain"}):
                raise ValueError("Covariate name conflicts with a reserved zone/mask role")
            names.add(name.casefold())
            quantity, method = spec["quantity"], spec["resampling"]
            if quantity not in {"continuous", "categorical", "count"} or method not in {"nearest", "bilinear", "average"}:
                raise ValueError("Explicit supported quantity and resampling are required")
            if (quantity != "continuous" and method != "nearest") or (name in {"mask", "constrain"} and quantity != "categorical"):
                raise ValueError("Masks/binary indicators require categorical nearest; count quantities require aligned nearest")
            path = local_file(spec["path"])
            description = raster_description(path)
            report["rasters"].append(dict(description, name=name, quantity=quantity, resampling=method))
            resources.update(map(Path, description["resources"]))
            return dict(spec, path=path, filename=f"covariate_{index:03}.tif" if name not in {"mask", "constrain"} else f"{name}.tif")
        checked = attempt("raster_policy", validate_spec, spec.get("path") if isinstance(spec, dict) else None)
        if checked:
            raster_specs.append(checked)
    if census is not None:
        reserved = {"dens", "eligible_pixel_count", *[spec["name"] + "_avg" for spec in raster_specs]}
        if set(census.columns) & reserved:
            errors.append(issue("training_columns", f"Census columns conflict with derived training columns: {sorted(set(census.columns) & reserved)}"))
    if "census_polygons" in request and reference and "reference_grid" in report:
        def get_polygons():
            spec = request["census_polygons"]
            check_keys(spec, {"path", "layer", "id_column"}, {"path", "id_column"})
            frame = read_polygons(spec, report["reference_grid"]["crs"], token)
            column = spec["id_column"]
            validated = validate_census(pd.DataFrame({"id": frame[column], "pop": np.zeros(len(frame))}), "id", "pop")
            frame = frame.copy()
            frame["_zone_id"] = validated["id"].to_numpy(dtype="float64")
            index = frame.sindex
            for position, geometry in enumerate(frame.geometry):
                check_cancelled(token)
                for other in index.query(geometry, predicate="intersects"):
                    if other > position and geometry.intersection(frame.geometry.iloc[other]).area > 0:
                        raise ValueError(f"Census polygons overlap: rows {position} and {other}")
            resources.update(vector_resources(local_file(spec["path"])))
            report["geometry"] = {"count": len(frame), "crs": frame.crs.to_string(), "valid": True,
                                  "overlaps": False, "id_column": column}
            return frame
        polygons = attempt("polygon_geometry", get_polygons, request["census_polygons"].get("path"))
    else:
        zone_path = attempt("zone_raster", lambda: local_file(request.get("zone_raster", request["reference_raster"])))
        if zone_path:
            descriptor = attempt("zone_raster", lambda: raster_description(zone_path), zone_path)
            if descriptor:
                resources.update(map(Path, descriptor["resources"]))
    with new_output(request["output_dir"], resources) as root:
        output_root, output_id = root, owned_identity(root)
        scratch = Path(tempfile.mkdtemp(prefix=".scratch-", dir=root))
        scratch_id = owned_identity(scratch)
        try:
            if not errors:
                with rasterio.open(reference) as grid:
                    if polygons is None:
                        with rasterio.open(zone_path) as zone:
                            attempt("zone_alignment", lambda: validate_alignment(grid.profile, zone.profile))
                    for spec in raster_specs:
                        with rasterio.open(spec["path"]) as source:
                            try:
                                validate_alignment(grid.profile, source.profile)
                                spec["aligned"] = True
                            except ValueError:
                                spec["aligned"] = False
                            if not spec["aligned"]:
                                if spec["quantity"] == "count":
                                    errors.append(issue("count_resampling", "Count raster must already match the reference; choose an explicit conservative workflow outside this tool", spec["path"]))
                                else:
                                    report["warnings"].append(issue("grid_resampling", f"Explicit {spec['resampling']} alignment is required for {spec['name']}", spec["path"]))
                    if polygons is not None and census is not None:
                        polygon_ids = set(polygons["_zone_id"])
                        census_ids = set(census[request["census"]["id_column"]])
                        if polygon_ids != census_ids:
                            errors.append(issue("polygon_census_ids", f"IDs differ: polygons-only {sorted(polygon_ids-census_ids)}, census-only {sorted(census_ids-polygon_ids)}"))
                        footprint = Polygon([grid.transform @ point for point in
                                             [(0, 0), (grid.width, 0), (grid.width, grid.height), (0, grid.height)]])
                        tolerance = max(np.hypot(grid.transform.a, grid.transform.d),
                                        np.hypot(grid.transform.b, grid.transform.e)) * 1e-7
                        for position, geometry in enumerate(polygons.geometry):
                            if not footprint.buffer(tolerance).covers(geometry):
                                errors.append(issue("polygon_clipped", f"Census polygon row {position} extends outside the reference footprint; choose a covering grid, do not redistribute a full polygon census into a crop"))
                    if not errors:
                        _process_grid(root, scratch, grid, zone_path if polygons is None else None,
                                      polygons, raster_specs, census, request, report, token, stage)
            report["ready"] = not errors
            if request["operation"] == "prepare" and errors:
                raise ValueError("Preparation refused: " + "; ".join(item["message"] for item in errors))
            if report["ready"] and request["operation"] == "prepare":
                config = {"work_dir": str(root), "data_dir": "data", "output_dir": "output",
                          "mastergrid": "mastergrid.tif", "census_data": "census.csv",
                          "census_id_column": request["census"]["id_column"],
                          "census_pop_column": request["census"]["population_column"],
                          "covariates": {spec["name"]: spec["filename"] for spec in raster_specs if spec["name"] not in {"mask", "constrain"}},
                          "mask": "mask.tif" if "mask" in request else None,
                          "constrain": "constrain.tif" if "constrain" in request else None}
                with atomic_output(root / "data" / "census.csv", token) as temporary:
                    census.to_csv(temporary, index=False)
                from .config.settings import Settings
                # Include all existing engine/UI defaults without importing the
                # GUI. Keep project-relative data/output paths for portability.
                config = {**Settings(**config).to_config(), **config}
                with atomic_output(root / "config.yaml", token) as temporary:
                    temporary.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
                Settings.from_file(root / "config.yaml")
                report["config_path"] = str(root / "config.yaml")
            stage(95, "Verifying source fingerprints and committing the report")
            verify_resource_set(request, sources, token)
            if not remove_owned(scratch, scratch_id, root):
                raise ValueError("Owned scratch directory was redirected; retained without deletion")
            scratch = None
            write_json(root / "provenance.json", {"request": request, "inputs": sources, "policies": report["policies"]}, token)
            with atomic_output(root / "provenance.csv", token) as temporary:
                pd.DataFrame(sources, columns=["path", "bytes", "mtime_ns", "sha256"]).to_csv(temporary, index=False)
            report["error_count"] = len(report["errors"])
            report["warning_count"] = len(report["warnings"])
            report["errors"] = report["errors"][:100]
            report["warnings"] = report["warnings"][:100]
            write_json(root / "report.json", dict(report, status="complete", output_dir=str(root)), token)
        finally:
            if scratch is not None:
                remove_owned(scratch, scratch_id, root)
        return root / "report.json"


def _process_grid(root, scratch, grid, zone_path, polygons, specs, census, request, report, token, stage):
    """One reference-grid pass collects every zone's support and writes derived data."""
    size, writing = request.get("tile_size", 512), request["operation"] == "prepare"
    ids = census[request["census"]["id_column"]].to_numpy(dtype="float64")
    known = set(ids)
    populations = dict(zip(ids, census[request["census"]["population_column"]].to_numpy(dtype="float64")))
    coverage = {int(zone): {"pixels": 0, "eligible": 0, "joint_valid": 0, "constrained_eligible": 0, "constrained_joint_valid": 0,
                           "features": {s["name"]: 0 for s in specs if s["name"] not in {"mask", "constrain"}}} for zone in ids}
    unknown, unknown_counts, outside = set(), {}, 0
    with ExitStack() as stack:
        readers, writers = {}, {}
        all_specs = ([{"name": "zones", "path": zone_path, "quantity": "ids", "resampling": "nearest"}] if zone_path else []) + specs
        for index, spec in enumerate(all_specs):
            normalized = scratch / f"normalized_{index}.tif"
            try:
                _normalized(spec["path"], normalized, size, token, spec["quantity"] == "categorical", spec["quantity"] == "ids", spec["quantity"] == "count")
            except ValueError as exc:
                report["errors"].append(issue("raster_values", exc, spec["path"]))
                continue
            source = stack.enter_context(rasterio.open(normalized))
            readers[spec["name"]] = stack.enter_context(WarpedVRT(source, crs=grid.crs, transform=grid.transform,
                width=grid.width, height=grid.height, dtype="float64", src_nodata=np.nan, nodata=np.nan,
                resampling=getattr(Resampling, spec["resampling"]), warp_mem_limit=64, tolerance=0.125))
        if report["errors"]:
            return
        if writing:
            (root / "data").mkdir()
            for name, filename in [("zones", "mastergrid.tif")] + [(spec["name"], spec["filename"]) for spec in specs]:
                path = stack.enter_context(atomic_output(root / "data" / filename, token))
                writers[name] = stack.enter_context(rasterio.open(path, "w", **output_profile(grid)))
                report["derived_paths"][name] = str(root / "data" / filename)
        total = math.ceil(grid.width / size) * math.ceil(grid.height / size)
        for counter, window in enumerate(tiles(grid.width, grid.height, size)):
            stage(10 + int(75 * counter / total), "Checking reference-grid coverage")
            reference_valid = np.ones((int(window.height), int(window.width)), dtype=bool)
            if polygons is None:
                zones = readers["zones"].read(1, window=window, masked=True).filled(np.nan)
            else:
                transform = grid.window_transform(window)
                corners = [transform @ pair for pair in [(0, 0), (window.width, 0), (window.width, window.height), (0, window.height)]]
                bounds = Polygon(corners).bounds
                selected = polygons.iloc[polygons.sindex.query(box(*bounds), predicate="intersects")]
                zones = rasterize(list(zip(selected.geometry, selected["_zone_id"])), out_shape=reference_valid.shape,
                                  transform=transform, fill=np.nan, dtype="float64", all_touched=False, skip_invalid=False) if len(selected) else np.full(reference_valid.shape, np.nan)
            zones = np.where(reference_valid, zones, np.nan)
            support = np.isfinite(zones)
            unknown.update(set(zones[support]) - known)
            outside += int((reference_valid & ~support).sum())
            arrays = {name: reader.read(1, window=window, masked=True).filled(np.nan) for name, reader in readers.items() if name != "zones"}
            eligible = support.copy()
            if "mask" in arrays:
                eligible &= np.isfinite(arrays["mask"]) & (arrays["mask"] != 1)
            constrained = eligible.copy()
            if "constrain" in arrays:
                constrained &= np.isfinite(arrays["constrain"]) & (arrays["constrain"] != 0)
            joint = eligible.copy()
            for name in coverage[int(ids[0])]["features"]:
                joint &= np.isfinite(arrays[name])
            unique_zones, pixel_counts = np.unique(zones[support], return_counts=True)
            for position, (zone, pixel_count) in enumerate(zip(unique_zones, pixel_counts)):
                if position % 1024 == 0:
                    check_cancelled(token)
                if zone not in known:
                    unknown_counts[int(zone)] = unknown_counts.get(int(zone), 0) + int(pixel_count)
                    continue
                entry = coverage[int(zone)]
                belongs = zones == zone
                entry["pixels"] += int(belongs.sum())
                entry["eligible"] += int((belongs & eligible).sum())
                entry["joint_valid"] += int((belongs & joint).sum())
                entry["constrained_eligible"] += int((belongs & constrained).sum())
                entry["constrained_joint_valid"] += int((belongs & constrained & joint).sum())
                for name in entry["features"]:
                    entry["features"][name] += int((belongs & eligible & np.isfinite(arrays[name])).sum())
            if writing:
                writers["zones"].write(zones, 1, window=window)
                for name in arrays:
                    writers[name].write(np.where(reference_valid, arrays[name], np.nan), 1, window=window)
        for zone, entry in coverage.items():
            if entry["pixels"] == 0:
                report["errors"].append(issue("missing_zone_support", f"Census ID {zone} has no pixels on the reference grid"))
            if entry["eligible"] == 0:
                report["errors"].append(issue("excluded_zone_support", f"Census ID {zone} has no eligible pixels after masks"))
            for name, count in entry["features"].items():
                if count == 0:
                    report["errors"].append(issue("missing_feature_support", f"Census ID {zone} has no valid eligible values for {name}"))
            if populations[zone] > 0 and entry["joint_valid"] == 0:
                report["errors"].append(issue("missing_joint_support", f"Census ID {zone} has no jointly valid predictor pixels"))
            if "constrain" in request and populations[zone] > 0 and entry["constrained_joint_valid"] == 0:
                report["errors"].append(issue("missing_constrained_support", f"Positive-population census ID {zone} has no jointly valid constrained allocation pixels"))
            if 0 < entry["joint_valid"] < entry["eligible"]:
                report["warnings"].append(issue("partial_predictor_coverage", f"Census ID {zone}: only {entry['joint_valid']} of {entry['eligible']} eligible pixels have all declared predictors"))
        if unknown:
            report["warnings"].insert(0, issue("unknown_grid_ids", f"{len(unknown)} grid IDs are not in census and are excluded from population allocation; sample {sorted(unknown)[:100]}"))
        if outside:
            report["warnings"].append(issue("uncovered_reference", f"{outside} reference-grid pixels are outside census-zone support"))
        report["coverage"] = {"zone_count": len(coverage), "zones": dict(list(coverage.items())[:100]),
                              "zones_truncated": len(coverage) > 100, "full_table": "coverage.csv",
                              "unknown_grid_ids": sorted(int(zone) for zone in unknown)[:1000], "unknown_id_count": len(unknown),
                              "unknown_grid_pixel_count": sum(unknown_counts.values()),
                              "uncovered_reference_pixels": outside}
    with atomic_output(root / "coverage.csv", token) as temporary:
        pd.DataFrame([dict(id=zone, is_census=True, **{k: v for k, v in value.items() if k != "features"}, **{f"valid_{k}": v for k, v in value["features"].items()}) for zone, value in coverage.items()]
                     + [dict(id=zone, is_census=False, pixels=count) for zone, count in unknown_counts.items()]).to_csv(temporary, index=False)
