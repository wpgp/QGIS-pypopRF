"""Bounded run metadata validation shared by process completion and history."""
import json
from pathlib import Path, PureWindowsPath

MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def read_manifest(path):
    path = Path(path)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Result metadata is unexpectedly large")
    with path.open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("Result metadata is unexpectedly large")
    manifest = json.loads(data)
    if not isinstance(manifest, dict):
        raise ValueError("Result metadata must be an object")
    status = manifest.get("status")
    if not isinstance(status, str) or status not in {"running", "complete", "failed", "cancelled"}:
        raise ValueError("Result metadata has an invalid status")
    names = manifest.get("outputs", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("Result metadata has an invalid output list")
    return manifest


def population_paths(root, manifest):
    root = Path(root).resolve()
    if manifest["status"] != "complete":
        return []
    result = []
    for name in manifest.get("outputs", []):
        # Old Windows runs used backslashes; new runs use portable POSIX names.
        # Normalize only contained relative paths, never drives/UNC/traversal.
        relative = Path(name.replace("\\", "/"))
        if relative.is_absolute() or PureWindowsPath(name).drive or ".." in relative.parts:
            raise ValueError("Invalid result path")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Result escaped its run directory or is missing")
        if path.suffix.lower() in {".tif", ".tiff"} and path.name != "prediction.tif":
            result.append(path)
    return result
