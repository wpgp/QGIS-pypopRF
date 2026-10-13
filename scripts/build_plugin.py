"""Build a small, reproducible plugin ZIP from an explicit runtime allowlist."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "pypopRF"
REQUIRED_FILES = (
    "__init__.py", "qgis_pypoprf.py", "gui/dialogs/main_dialog.py",
    "gui/forms/main_dialog.ui", "services/runtime_manager.py", "shared/atomic_files.py",
    "services/owned_process.py", "shared/runtime_environment.py",
    "metadata.txt", "icon.png", "wp_logo.png",
    "requirements.txt", "requirements-engine.lock", "requirements-engine-wheels.json",
    "LICENSE", "README.md", "CHANGELOG.md", "CITATION.cff",
)
RUNTIME_DIRECTORIES = ("core", "gui", "controllers", "services", "shared")


def package_files(root):
    root = Path(root).resolve()
    names = set(REQUIRED_FILES)
    for directory in RUNTIME_DIRECTORIES:
        names.update(path.relative_to(root).as_posix()
                     for path in (root / directory).rglob("*.py")
                     if "__pycache__" not in path.parts)
    for name in sorted(names):
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Missing or unsafe package file: {name}")
        yield name, path


def verify_package(archive):
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("Corrupt archive")
        members = package.namelist()
        prefix = f"{PLUGIN_NAME}/"
        if len(members) != len(set(members)):
            raise ValueError("Duplicate archive members")
        for member in members:
            if not member.startswith(prefix) or ".." in Path(member).parts:
                raise ValueError(f"Unsafe archive member: {member}")
        for name in REQUIRED_FILES:
            if prefix + name not in members:
                raise ValueError(f"Missing package requirement: {name}")
        manifest = json.loads(package.read(prefix + "PACKAGE_MANIFEST.json"))
        declared = manifest["files"]
        actual = set(members) - {prefix + "PACKAGE_MANIFEST.json"}
        if actual != {prefix + name for name in declared}:
            raise ValueError("Archive contents differ from manifest")
        for name, digest in declared.items():
            if hashlib.sha256(package.read(prefix + name)).hexdigest() != digest:
                raise ValueError(f"Hash mismatch: {name}")
    if Path(archive).stat().st_size > 25_000_000:
        raise ValueError("Plugin archive exceeds 25 MB")
    return manifest


def build_plugin(destination, root=ROOT):
    root = Path(root).resolve()
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        raise ValueError("Package destination must be a .zip archive, never a source file")
    protected = {path.resolve() for _, path in package_files(root)}
    if destination.resolve() in protected:
        raise ValueError("Package destination overlaps a runtime source file")
    if any(destination.resolve().is_relative_to(root / directory)
           for directory in RUNTIME_DIRECTORIES):
        raise ValueError("Archive cannot be written into a source package")
    contents = {name: path.read_bytes() for name, path in package_files(root)}
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(contents["metadata.txt"].decode("utf-8"))
    manifest = {
        "format_version": 1, "plugin": PLUGIN_NAME,
        "version": config["general"]["version"],
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
    }
    contents["PACKAGE_MANIFEST.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(suffix=".zip", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, data in sorted(contents.items()):
                info = zipfile.ZipInfo(f"{PLUGIN_NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                package.writestr(info, data)
        verify_package(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "pypopRF.zip")
    options = parser.parse_args(argv)
    manifest = build_plugin(options.output)
    print(f"Built {options.output}: {len(manifest['files'])} files; version {manifest['version']}")


if __name__ == "__main__":
    main()
