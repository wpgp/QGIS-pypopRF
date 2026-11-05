"""Cell-center population estimates, never a claim of fine-pixel accuracy."""
from pathlib import Path
import re

import numpy as np
import rasterio
import shapely
from shapely.geometry import Polygon

from .preparation import (check_keys, local_file, raster_description, declared_resources,
                          read_polygons, tiles, fingerprint, verify_resource_set, new_output, write_json, issue,
                          owned_identity, assert_owned)
from .utils.raster import valid_mask
from .utils.runtime import check_cancelled


def summarize_population(request, token=None, progress=None):
    allowed = {"schema_version", "request_id", "operation", "output_dir", "population_raster", "aoi",
               "inclusion", "units", "tile_size", "expected_population_sha256"}
    check_keys(request, allowed, {"schema_version", "operation", "output_dir", "population_raster", "aoi", "inclusion", "units"})
    if (type(request["schema_version"]) is not int or request["schema_version"] != 1
            or request["operation"] != "population_summary"):
        raise ValueError("Unsupported summary schema/operation")
    if request["inclusion"] != "cell_center" or request["units"] != "persons_per_pixel":
        raise ValueError("Explicit cell_center inclusion and persons_per_pixel units are required; density rasters are unsupported")
    size = request.get("tile_size", 512)
    if type(size) is not int or not 16 <= size <= 2048:
        raise ValueError("tile_size must be an integer between 16 and 2048")
    path = local_file(request["population_raster"])
    sources = declared_resources(request)
    records = [fingerprint(item, token) for item in sorted(sources)]
    if "expected_population_sha256" in request:
        expected = request["expected_population_sha256"]
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("expected_population_sha256 must be the recorded lowercase SHA-256")
        actual = next(record["sha256"] for record in records if Path(record["path"]) == path)
        if actual != expected:
            raise ValueError("Population raster differs from the selected run artifact SHA-256; do not summarize an externally edited result")
    description = raster_description(path)
    frame = read_polygons(request["aoi"], description["crs"], token)
    geometry = shapely.union_all(frame.geometry.to_numpy())
    if not geometry.is_valid or geometry.is_empty:
        raise ValueError("AOI union is invalid/empty; no automatic geometry repair")
    report = {"schema_version": 1, "request_id": request.get("request_id"), "operation": "population_summary",
              "ready": True, "errors": [], "warnings": [], "inputs": records, "raster": description,
              "aoi": {"feature_count": len(frame), "crs": frame.crs.to_string(), "overlaps": "unioned, counted once"}}
    total, correction, selected, valid_count, integer_total = 0.0, 0.0, 0, 0, 0
    with new_output(request["output_dir"], sources) as root:
        identity = owned_identity(root)
        with rasterio.open(path) as source:
            footprint = Polygon([source.transform @ point for point in [(0, 0), (source.width, 0),
                                      (source.width, source.height), (0, source.height)]])
            extends = not footprint.covers(geometry)
            for index, window in enumerate(tiles(source.width, source.height, size)):
                check_cancelled(token)
                if progress:
                    progress(min(85, 10 + index), "Summing finite supported population cells")
                check_cancelled(token)
                assert_owned(root, identity)
                affine = source.window_transform(window)
                rows, cols = np.indices((int(window.height), int(window.width)))
                x = affine.a * (cols + 0.5) + affine.b * (rows + 0.5) + affine.c
                y = affine.d * (cols + 0.5) + affine.e * (rows + 0.5) + affine.f
                # GDAL all_touched=False also uses Bresenham boundary pixels;
                # exact point predicates are required for the stated center rule.
                included = shapely.intersects_xy(geometry, x, y)
                selected += int(included.sum())
                if not included.any():
                    continue
                array = source.read(1, window=window, masked=True)
                raw = np.asarray(np.ma.getdata(array))
                valid = included & valid_mask(array)
                if np.issubdtype(raw.dtype, np.integer) and (raw[valid] > 2 ** 53).any():
                    raise ValueError("Selected integer-storage population counts must be exactly representable within float64 (at most 2**53)")
                values = np.asarray(raw, dtype="float64")
                if (values[valid] < 0).any():
                    raise ValueError("Selected supported population values must be nonnegative")
                if np.issubdtype(raw.dtype, np.integer):
                    integer_total += sum(map(int, raw[valid]))
                    if integer_total > 2 ** 53:
                        raise ValueError("Selected integer-storage population total exceeds the exact float64 range (2**53); not rounded or published")
                valid_count += int(valid.sum())
                subtotal = float(np.sum(values[valid], dtype="float64"))
                # Compensated tile aggregation; reported precision is still an estimate.
                adjusted = subtotal - correction
                updated = total + adjusted
                correction = (updated - total) - adjusted
                total = updated
                if not np.isfinite(total):
                    raise ValueError("Population sum exceeds supported finite float64 range")
        coverage = valid_count / selected if selected else None
        complete = bool(selected and valid_count == selected and not extends)
        if not complete:
            report["warnings"].append(issue("partial_coverage", "This is only the supported-cell sum, not a complete AOI population estimate"))
        if not selected:
            report["warnings"].append(issue("no_selected_centers", "AOI contains no raster cell centers; zero supported sum is not evidence of zero population"))
        report["summary"] = {"sum_persons": total, "display_persons": round(total), "valid_cells": valid_count,
                             "selected_cells": selected, "coverage_fraction": coverage,
                             "aoi_extends_outside_raster": extends, "complete_coverage": complete,
                             "inclusion": "cell_center", "boundary": "include center on polygon boundary",
                             "units": "persons_per_pixel", "precision": "model estimate; display rounded to whole persons",
                             "coverage_denominator": "selected centers within the raster, not total AOI area"}
        check_cancelled(token)
        if progress:
            progress(95, "Verifying source resources and committing the summary")
        check_cancelled(token)
        assert_owned(root, identity)
        verify_resource_set(request, records, token)
        write_json(root / "provenance.json", {"request": request, "inputs": records}, token)
        write_json(root / "report.json", dict(report, status="complete", output_dir=str(root)), token)
        return Path(root / "report.json")
