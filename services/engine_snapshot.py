"""Bounded per-job engine source freeze outside the mutable installed plugin.

No numerical/Qt imports, input datasets, GUI code, shared content cache or GC.
The caller owns the job directory and retains it until its actual child exits.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

if __package__ == "services":
    from shared.runtime_environment import engine_arguments
else:
    from ..shared.runtime_environment import engine_arguments

__all__ = ["create_engine_snapshot", "engine_arguments", "SnapshotError"]

MAX_FILES = 512
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 2048
MANIFEST_NAME = ".engine_snapshot.json"
PROVENANCE_FILES = ("services/__init__.py", "services/runtime_manager.py", "services/owned_process.py")
REQUIRED_FILES = ("core/__init__.py", "core/pypoprf/__init__.py", "core/pypoprf/__main__.py",
                  "core/pypoprf/tools.py", "shared/__init__.py", "shared/runtime_environment.py",
                  "shared/atomic_files.py")


class SnapshotError(ValueError):
    """A bounded, unchanged, isolated code snapshot could not be produced."""


def _check(token):
    if token is not None:
        token.check()


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise SnapshotError(f"Engine snapshot refuses links/junctions: {part}")


def _directory(value):
    path = Path(value).expanduser().absolute()
    _no_links(path)
    if not path.is_dir():
        raise SnapshotError(f"Existing directory required for engine snapshot: {path}")
    return path.resolve()


def _read_source(path, token=None):
    _check(token)
    _no_links(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise SnapshotError(f"Missing or oversized engine source file: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise SnapshotError(f"Engine source exceeds {MAX_FILE_BYTES} bytes: {path}")
    _check(token)
    return data


def _logical_lines(data):
    pending = ""
    for physical in data.decode("utf-8-sig").splitlines():
        pending += physical.strip()
        if pending.endswith("\\"):
            pending = pending[:-1] + " "
            continue
        line = re.sub(r"(^|\s)#.*$", "", pending).strip()
        pending = ""
        if line:
            yield line
    if pending:
        raise SnapshotError("Unterminated snapshot requirements continuation")


def _nested(line):
    return re.fullmatch(r"(?:-r\s*|--requirement(?:\s+|=))(.+)", line)


def _inventory(source, token=None):
    files = set()
    entries = 0
    for folder in (source / "core", source / "shared"):
        _no_links(folder)
        if not folder.is_dir():
            raise SnapshotError(f"Missing engine source directory: {folder}")
        pending_directories = [folder]
        while pending_directories:
            _check(token)
            directory = pending_directories.pop()
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        raise SnapshotError("Engine source directory has too many entries")
                    path = Path(child.path)
                    _no_links(path)
                    if child.is_dir(follow_symlinks=False):
                        if child.name != "__pycache__":
                            pending_directories.append(path)
                    elif child.name.endswith(".py"):
                        files.add(path.relative_to(source).as_posix())
    files.update(PROVENANCE_FILES)
    files.add("metadata.txt")
    # Include exact nested requirement bytes, never data or arbitrary siblings.
    pending = ["requirements-engine.lock", "requirements.txt"]
    visited = set()
    while pending:
        _check(token)
        relative = pending.pop()
        if relative in visited:
            continue
        visited.add(relative)
        path = source / relative
        _no_links(path)
        if not path.resolve().is_relative_to(source):
            raise SnapshotError("Snapshot requirements escape the plugin source")
        data = _read_source(path, token)
        files.add(relative)
        for line in _logical_lines(data):
            nested = _nested(line)
            if nested:
                child = path.parent / nested.group(1).strip()
                _no_links(child)
                child = child.resolve()
                if not child.is_relative_to(source):
                    raise SnapshotError("Snapshot requirements escape the plugin source")
                pending.append(child.relative_to(source).as_posix())
        if len(files) + len(pending) > MAX_FILES:
            raise SnapshotError("Too many engine snapshot files")
    if len(files) > MAX_FILES:
        raise SnapshotError("Too many engine snapshot files")
    if not set(REQUIRED_FILES).issubset(files):
        raise SnapshotError("Required engine entrypoint/shared source is missing")
    return sorted(files)


def _dependency_pins(source, copied):
    """Bind the actual child interpreter to exactly these frozen lock versions."""
    visited, visiting, pins = set(), set(), {}
    def visit(relative):
        if relative in visiting:
            raise SnapshotError("Cyclic snapshot engine requirements")
        if relative in visited:
            return
        visiting.add(relative)
        for line in _logical_lines(copied[relative]):
            nested = _nested(line)
            if nested:
                child = (source / relative).parent / nested.group(1).strip()
                visit(child.resolve().relative_to(source).as_posix())
                continue
            fields = line.split()
            match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)", fields[0])
            if not match or len(fields) < 2 or any(re.fullmatch(r"--hash=sha256:[0-9a-fA-F]{64}", option) is None for option in fields[1:]):
                raise SnapshotError("Snapshot engine lock requires exact SHA-256-verified pins")
            name, version = match.groups()
            canonical = re.sub(r"[-_.]+", "-", name).lower()
            if canonical in pins and pins[canonical] != version:
                raise SnapshotError("Conflicting snapshot dependency pins")
            pins[canonical] = version
        visiting.remove(relative)
        visited.add(relative)
    visit("requirements-engine.lock")
    if not pins:
        raise SnapshotError("Snapshot engine lock must contain hashed dependency pins")
    return pins


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def create_engine_snapshot(package_root, job_dir, cancellation_token=None):
    """Freeze source into NEW ``job_dir/engine_source`` and return its Path.

    Existing destination is never reused/replaced. Failure removes only this
    invocation's verified child directory; success cleanup belongs to the caller
    after actual interpreter reaping, not merely QProcess launcher completion.
    """
    source, job = _directory(package_root), _directory(job_dir)
    if source == job or source.is_relative_to(job) or job.is_relative_to(source):
        raise SnapshotError("Engine snapshot job directory must not overlap plugin source")
    parent_identity = _identity(job)
    destination = job / "engine_source"
    _no_links(destination)
    files = _inventory(source, cancellation_token)
    _check(cancellation_token)
    _no_links(job)
    if _identity(job) != parent_identity or job.resolve() != job:
        raise SnapshotError("Engine snapshot job ownership changed before creation")
    destination.mkdir(exist_ok=False)
    destination_identity = _identity(destination)

    def owned():
        _no_links(job)
        _no_links(destination)
        if job.resolve() != job or _identity(job) != parent_identity or _identity(destination) != destination_identity:
            raise SnapshotError("Engine snapshot ownership changed; temporary files retained")

    complete = False
    try:
        records, copied = {}, {}
        total = 0
        for relative in files:
            owned()
            data = _read_source(source / relative, cancellation_token)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise SnapshotError("Engine snapshot exceeds its total byte limit")
            target = destination / relative
            _no_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            _no_links(target)
            with target.open("xb") as stream:
                stream.write(data)
            records[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            copied[relative] = data
        if _inventory(source, cancellation_token) != files:
            raise SnapshotError("Plugin source files changed while freezing engine; retry")
        for relative, record in records.items():
            data = _read_source(source / relative, cancellation_token)
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise SnapshotError("Plugin source bytes changed while freezing engine; retry")
        owned()
        _check(cancellation_token)
        manifest = {"schema_version": 1, "source_root": str(source), "files": records,
                    "file_count": len(records), "total_bytes": total,
                    "locked_dependencies": _dependency_pins(source, copied)}
        with (destination / MANIFEST_NAME).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=True, allow_nan=False, sort_keys=True)
        owned()
        _check(cancellation_token)
        complete = True
        return destination
    finally:
        if not complete:
            owned()
            for directory, children, names in os.walk(destination, followlinks=False):
                for name in (*children, *names):
                    _no_links(Path(directory) / name)
            shutil.rmtree(destination)
