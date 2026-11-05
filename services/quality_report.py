"""Bounded, read-only diagnostics from saved run artifacts; no Qt/numerical imports."""
import csv
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path, PureWindowsPath

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20000
MAX_FEATURES = 500
MAX_ERROR_ROWS = 100


@dataclass(frozen=True)
class ZonePoint:
    zone_id: int
    observed: float
    predicted: float
    fold: int
    group: str = ""
    centroid_x: float | None = None
    centroid_y: float | None = None

    @property
    def absolute_error(self):
        return abs(self.predicted - self.observed)


@dataclass(frozen=True)
class FeatureImportance:
    feature: str
    importance: float
    std: float | None


@dataclass(frozen=True)
class QualityReport:
    run_dir: Path | None = None
    run_status: str = "not_selected"
    conservation_label: str = "No run selected"
    cv_status: str = "unavailable"
    validation_scheme: str = "not recorded"
    target_units: str = "zone density (units not recorded)"
    metrics: tuple = ()
    baseline_metrics: tuple = ()
    points: tuple[ZonePoint, ...] = ()
    feature_importance: tuple[FeatureImportance, ...] = ()
    crs: str | None = None
    limits: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def high_error_zones(self):
        return tuple(sorted(self.points, key=lambda point: (-point.absolute_error, point.zone_id))[:MAX_ERROR_ROWS])

    def zone_request(self, zone_ids=None):
        wanted = set(zone_ids) if zone_ids is not None else {
            point.zone_id for point in self.high_error_zones[:10]}
        points = [point for point in self.points if point.zone_id in wanted][:MAX_ERROR_ROWS]
        return {"zone_ids": [point.zone_id for point in points],
                "centroids": [{"zone_id": point.zone_id, "x": point.centroid_x, "y": point.centroid_y}
                              for point in points if self.crs is not None
                              and point.centroid_x is not None and point.centroid_y is not None],
                "crs": self.crs, "run_dir": str(self.run_dir) if self.run_dir else None}


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _safe_path(root, name):
    relative = Path(str(name).replace("\\", "/"))
    if (relative.is_absolute() or PureWindowsPath(name).drive
            or ".." in relative.parts or not relative.parts):
        raise ValueError("Artifact path is not contained in the run")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if _is_link(candidate):
            raise ValueError("Linked artifacts are not read")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        raise ValueError("Artifact is missing or escaped the run")
    return candidate


def _read(root, name, limit, hashes):
    if _is_link(root) or root.resolve() != root:
        raise ValueError("Run directory was redirected")
    path = _safe_path(root, name)
    before = path.stat()
    if before.st_size > limit:
        raise ValueError(f"Artifact exceeds {limit} byte limit")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    after = path.stat()
    if (len(data) > limit or _is_link(path) or path.resolve().parent != root
            or (before.st_size, before.st_mtime_ns, before.st_ino) !=
               (after.st_size, after.st_mtime_ns, after.st_ino)):
        raise ValueError("Artifact changed during reading")
    if hashes and name not in hashes:
        raise ValueError("Artifact is missing from the manifest SHA-256 inventory")
    if name in hashes and hashlib.sha256(data).hexdigest() != hashes[name]:
        raise ValueError("Artifact SHA-256 differs from the run manifest")
    return data.decode("utf-8-sig")


def _json(root, name, hashes):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    result = json.loads(_read(root, name, MAX_JSON_BYTES, hashes), parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError("Metadata must be an object")
    return result


def _csv(root, name, required, hashes, max_rows=MAX_ROWS):
    reader = csv.DictReader(io.StringIO(_read(root, name, MAX_CSV_BYTES, hashes), newline=""))
    header = reader.fieldnames
    if (not header or len(header) > 64 or len(header) != len(set(header))
            or not required.issubset(header)):
        raise ValueError("CSV header is missing required columns or contains duplicates")
    rows = []
    for index, row in enumerate(reader):
        if index >= max_rows:
            raise ValueError(f"CSV exceeds {max_rows} row limit")
        if None in row or any(value is None for value in row.values()):
            raise ValueError("CSV row does not match its header")
        rows.append(row)
    return rows


def _integer(value, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Expected an exact integer")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Expected an exact integer") from exc
    if (not number.is_finite() or number.copy_abs() > 2 ** 53
            or number != number.to_integral_value() or (nonnegative and number < 0)):
        raise ValueError("Integer is invalid or outside the supported exact range")
    return int(number)


def _number(value, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError("Expected a finite number")
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError("Expected a finite nonnegative number" if nonnegative else "Expected a finite number")
    return number


def _text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Text field is invalid or too long")
    return value


def _scores(observed, predicted):
    errors = [abs(a - b) for a, b in zip(observed, predicted, strict=True)]
    scale = max(errors, default=0.)
    if scale == 0:
        return (("rmse", 0.), ("mae", 0.))
    return (("rmse", scale * min(1., math.sqrt(math.fsum((error / scale) ** 2 for error in errors) / len(errors)))),
            ("mae", scale * min(1., math.fsum(error / scale for error in errors) / len(errors))))


def _mean(values):
    scale = max(values, default=0.)
    return scale * min(1., math.fsum(value / scale for value in values) / len(values)) if scale else 0.


def _combine_means(first, second):
    """Combine nonnegative (count, mean) states without subtracting large sums."""
    n_first, mean_first = first
    n_second, mean_second = second
    count = n_first + n_second
    scale = max(mean_first, mean_second)
    if not count or not scale:
        return count, 0.
    fraction = math.fsum(((mean_first / scale) * (n_first / count),
                          (mean_second / scale) * (n_second / count)))
    return count, scale * min(1., fraction)


def _training_means(points):
    # Linear in zones + folds. Prefix/suffix states avoid total-minus-test-fold
    # cancellation when the excluded fold dominates all other target values.
    targets = {}
    for point in points:
        targets.setdefault(point.fold, []).append(point.observed)
    folds = sorted(targets)
    states = [(len(targets[fold]), _mean(targets[fold])) for fold in folds]
    prefix = [(0, 0.)]
    for state in states:
        prefix.append(_combine_means(prefix[-1], state))
    suffix = [(0, 0.)] * (len(states) + 1)
    for index in range(len(states) - 1, -1, -1):
        suffix[index] = _combine_means(states[index], suffix[index + 1])
    return {fold: _combine_means(prefix[index], suffix[index + 1])[1]
            for index, fold in enumerate(folds)}


def _points(root, metrics, hashes):
    if metrics.get("scheme") not in {"spatial_blocks", "group", "shuffled_zone"}:
        raise ValueError("Unrecognized validation strategy; OOF interpretation unavailable")
    rows = _csv(root, "cv_predictions.csv", {"zone_id", "density", "prediction", "fold"}, hashes)
    points, seen, groups = [], set(), {}
    for row in rows:
        zone_id, fold = _integer(row["zone_id"]), _integer(row["fold"], True)
        if zone_id in seen:
            raise ValueError("OOF predictions contain duplicate zone IDs")
        seen.add(zone_id)
        group = _text(row.get("group", ""))
        if metrics.get("scheme") in {"spatial_blocks", "group"}:
            if not group or (group in groups and groups[group] != fold):
                raise ValueError("Held-out groups are missing or cross fold boundaries")
            groups[group] = fold
        points.append(ZonePoint(zone_id, _number(row["density"], True),
                                _number(row["prediction"], True), fold, group))
    folds = {point.fold for point in points}
    n_folds = _integer(metrics.get("n_folds"), True)
    if (not points or len(points) != _integer(metrics.get("n_zones"), True)
            or n_folds < 2 or n_folds > len(points) or folds != set(range(n_folds))):
        raise ValueError("OOF coverage/folds do not match the recorded validation")
    observed = [point.observed for point in points]
    scores = _scores(observed, [point.predicted for point in points])
    for name, actual in scores:
        if not math.isclose(actual, _number(metrics.get(name), True), rel_tol=1e-6, abs_tol=1e-12):
            raise ValueError("OOF predictions disagree with recorded validation scores")
    training_means = _training_means(points)
    baseline = _scores(observed, [training_means[point.fold] for point in points])
    return tuple(points), baseline


_READ_ERRORS = (ValueError, TypeError, OSError, UnicodeError, OverflowError, RecursionError, csv.Error)


def load_quality_report(run_dir):
    """Return display-safe diagnostics, never execute/import artifact contents.

    Missing or malformed components yield bounded messages, not a UI exception.
    Manifest completion represents the engine's conservation check, not an
    independent revalidation by this numerical-dependency-free panel.
    """
    if run_dir is None:
        return QualityReport()
    errors, hashes = [], {}
    try:
        supplied = Path(run_dir)
        if any(_is_link(path) for path in (supplied, *supplied.absolute().parents)) or not supplied.is_dir():
            raise ValueError("Run directory is missing or linked")
        root = supplied.resolve()
        manifest = _json(root, "manifest.json", {})
        status = manifest.get("status")
        if status not in {"complete", "failed", "cancelled", "running"}:
            raise ValueError("Manifest status is invalid")
        inventory = manifest.get("artifacts", [])
        if not isinstance(inventory, list) or len(inventory) > MAX_ROWS:
            raise ValueError("Artifact inventory is invalid or too large")
        for record in inventory:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValueError("Artifact inventory contains an invalid entry")
            name, digest = record["path"], record.get("sha256")
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest) or name in hashes):
                raise ValueError("Artifact inventory digest is invalid or duplicated")
            hashes[name] = digest
        outputs = manifest.get("outputs", [])
        if not isinstance(outputs, list) or len(outputs) > 1000:
            raise ValueError("Output inventory is invalid or too large")
        population_present = False
        for name in outputs:
            path = _safe_path(root, _text(name, 1024))
            population_present |= path.suffix.lower() in {".tif", ".tiff"} and path.name != "prediction.tif"
        conservation = ("Engine-reported census totals verified; not pixel accuracy"
                        if status == "complete" and population_present else "Census conservation not established for this run")
        report = QualityReport(root, status, conservation)
    except _READ_ERRORS as exc:
        return QualityReport(run_status="invalid", conservation_label="Run metadata unavailable",
                             errors=(f"manifest.json: {str(exc)[:240]}",))

    metrics = {}
    try:
        metrics = _json(root, "cv_metrics.json", hashes)
        if metrics.get("status") not in {"complete", "unavailable"} or metrics.get("scale") != "density":
            raise ValueError("Unsupported validation status or target scale")
        summary = tuple((key, None if metrics.get(key) is None else _number(metrics[key], key != "r2"))
                        for key in ("rmse", "mae", "r2", "normalized_rmse", "normalized_mae"))
        if metrics.get("r2") is not None and _number(metrics["r2"]) > 1:
            raise ValueError("Recorded R² cannot exceed one")
        provenance = metrics.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("Validation provenance is invalid")
        limits = provenance.get("limitations", [])
        if not isinstance(limits, list) or len(limits) > 50:
            raise ValueError("Validation limitations are invalid")
        limits = tuple(_text(value, 1000) for value in limits)
        limits += ("Held-out census-zone density error is not independent fine-pixel population accuracy.",
                   "Permutation-importance spread is not a population uncertainty interval.")
        limits += ({"spatial_blocks": ("Spatial blocking alone does not establish independence; inspect block scale, zone overlap and buffering.",),
                    "group": ("User-supplied groups do not by themselves prove spatial independence.",),
                    "shuffled_zone": ("Shuffled-zone validation ignores geographic dependence and can be optimistic.",)}
                   .get(metrics.get("scheme"), ()))
        if not hashes:
            limits += ("No artifact SHA inventory; diagnostic contents are not hash-verified.",)
        if status != "complete":
            limits += ("Training diagnostics may be available, but this run did not complete population allocation.",)
        report = replace(report, cv_status=metrics["status"], metrics=summary,
                         validation_scheme=_text(metrics.get("scheme", "not recorded")),
                         target_units=_text(metrics.get("target_units", "zone density (units not recorded)")), limits=limits)
        if metrics["status"] == "complete":
            points, baseline = _points(root, metrics, hashes)
            report = replace(report, points=points, baseline_metrics=baseline)
        else:
            report = replace(report, limits=report.limits + (_text(metrics.get("reason", "Validation unavailable"), 1000),))
    except _READ_ERRORS as exc:
        errors.append(f"Validation: {str(exc)[:240]}")
        report = replace(report, cv_status="unavailable", metrics=(), points=(), baseline_metrics=())

    if report.points:
        try:
            provenance = metrics.get("provenance", {})
            crs = provenance.get("crs")
            if provenance.get("source") == "mastergrid_valid_pixel_centroids" and crs is not None:
                crs = _text(crs, 16000)
                if not crs.strip():
                    raise ValueError("Centroid CRS is empty")
                rows = _csv(root, "cv_zone_geometry.csv", {"zone_id", "centroid_x", "centroid_y"}, hashes)
                geometry = {}
                for row in rows:
                    zone_id = _integer(row["zone_id"])
                    if zone_id in geometry:
                        raise ValueError("Centroid geometry contains duplicate IDs")
                    geometry[zone_id] = (_number(row["centroid_x"]), _number(row["centroid_y"]))
                if set(geometry) != {point.zone_id for point in report.points}:
                    raise ValueError("Centroid geometry does not match held-out zones")
                report = replace(report, crs=crs, points=tuple(replace(point, centroid_x=geometry[point.zone_id][0],
                                                                    centroid_y=geometry[point.zone_id][1]) for point in report.points))
        except _READ_ERRORS as exc:
            errors.append(f"Centroids unavailable: {str(exc)[:240]}")
    try:
        rows = _csv(root, "feature_importance.csv", {"feature", "importance"}, hashes, MAX_FEATURES)
        features, seen = [], set()
        for row in rows:
            feature = _text(row["feature"])
            if not feature.strip() or feature in seen:
                raise ValueError("Feature names are empty or duplicated")
            seen.add(feature)
            features.append(FeatureImportance(feature, _number(row["importance"]),
                                              _number(row["std"], True) if row.get("std") else None))
        report = replace(report, feature_importance=tuple(sorted(features, key=lambda feature: -feature.importance)))
    except _READ_ERRORS as exc:
        errors.append(f"Feature importance unavailable: {str(exc)[:240]}")
    return replace(report, errors=tuple(errors))
