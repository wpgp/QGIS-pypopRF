"""Build a small, reproducible plugin ZIP from an explicit runtime allowlist."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "pypopRF"
PUBLIC_DOCUMENTATION = (
    "docs/index.md", "docs/development.md",
    "docs/getting-started/installation.md", "docs/getting-started/quickstart.md",
    "docs/user-guide/interface.md", "docs/user-guide/input-data.md",
    "docs/user-guide/projects.md",
    "docs/user-guide/settings.md", "docs/user-guide/running-analysis.md",
    "docs/user-guide/troubleshooting.md",
    "docs/assets/screenshots/home.png", "docs/assets/screenshots/engine.png",
    "docs/assets/screenshots/project.png",
    "docs/assets/screenshots/workflow.png", "docs/assets/screenshots/quality.png",
)
REQUIRED_FILES = (
    "__init__.py", "qgis_pypoprf.py", "gui/dialogs/main_dialog.py",
    "gui/forms/main_dialog.ui", "services/runtime_manager.py", "shared/atomic_files.py",
    "services/owned_process.py", "services/engine_snapshot.py", "services/project_location.py",
    "shared/runtime_environment.py", "gui/widgets/workflow_status.py",
    "gui/widgets/home_panel.py", "gui/widgets/task_activity.py", "gui/widgets/visual_style.py",
    "gui/widgets/fitted_label.py", "gui/dialogs/about_dialog.py",
    "gui/widgets/light_theme.py", "gui/icons/check.svg", "gui/icons/partial.svg",
    "gui/icons/down.svg", "gui/icons/up.svg", "gui/icons/radio.svg",
    "gui/icons/play.svg", "gui/icons/play-disabled.svg", "gui/icons/stop.svg", "gui/icons/stop-disabled.svg",
    "gui/dialogs/import_conflict_dialog.py", "gui/presenters/runtime_presenter.py", "services/plugin_info.py",
    "gui/presenters/project_presenter.py",
    "core/__init__.py", "core/pypoprf/__init__.py", "core/pypoprf/__main__.py",
    "core/pypoprf/cli.py", "core/pypoprf/pipeline.py", "core/pypoprf/tools.py",
    "core/pypoprf/algorithms/model.py", "core/pypoprf/utils/zone_ids.py",
    "gui/__init__.py", "controllers/__init__.py", "services/__init__.py", "shared/__init__.py",
    "metadata.txt", "icon.png", "wp_logo.png",
    "requirements.txt", "requirements-engine.lock", "requirements-engine-wheels.json",
    "LICENSE", "README.md", "CHANGELOG.md", "CITATION.cff",
) + PUBLIC_DOCUMENTATION
RUNTIME_DIRECTORIES = ("core", "gui", "controllers", "services", "shared")
MAX_ARCHIVE_FILES = 10_000
MAX_MEMBER_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024


def _portable_member(name):
    """Reject aliases/device paths before trusting a cross-platform ZIP member.

    Windows naming rules: https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
    ZIP names use POSIX separators even when verification runs on Windows.
    """
    parts = name.split("/")
    devices = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
        prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"}
    if any(not part or part in {".", ".."} or part.endswith((".", " "))
           or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
           or part.split(".", 1)[0].rstrip(" ").upper() in devices for part in parts):
        raise ValueError(f"Unsafe archive member: {name}")
    return name.casefold()


def package_files(root):
    root = Path(root).resolve()
    names = set(REQUIRED_FILES)
    for directory in RUNTIME_DIRECTORIES:
        names.update(path.relative_to(root).as_posix()
                     for path in (root / directory).rglob("*.py")
                     if "__pycache__" not in path.parts)
    for name in sorted(names):
        _portable_member(name)
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Missing or unsafe package file: {name}")
        yield name, path


def verify_package(archive):
    if Path(archive).stat().st_size > 25_000_000:
        raise ValueError("Plugin archive exceeds 25 MB")
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        if (len(infos) > MAX_ARCHIVE_FILES
                or any(info.file_size > MAX_MEMBER_BYTES for info in infos)
                or sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES):
            raise ValueError("Plugin archive exceeds the expanded-file verification budget")
        manifest_info = package.getinfo(f"{PLUGIN_NAME}/PACKAGE_MANIFEST.json")
        if manifest_info.file_size > 4 * 1024 * 1024:
            raise ValueError("Package manifest is unexpectedly large")
        if package.testzip() is not None:
            raise ValueError("Corrupt archive")
        # ZipInfo.filename normalizes backslashes on Windows and truncates NUL.
        # Validate the original ZIP spelling before using normalized lookups.
        members = [info.orig_filename for info in infos]
        prefix = f"{PLUGIN_NAME}/"
        if len(members) != len(set(members)):
            raise ValueError("Duplicate archive members")
        portable = set()
        for info in infos:
            member = info.orig_filename
            key = _portable_member(member)
            if (not member.startswith(prefix) or key in portable
                    or stat.S_IFMT(info.external_attr >> 16) not in {0, stat.S_IFREG}):
                raise ValueError(f"Unsafe archive member: {member}")
            portable.add(key)
        for member in members:
            parts = member.casefold().split("/")
            if any("/".join(parts[:end]) in portable for end in range(1, len(parts))):
                raise ValueError(f"Unsafe archive member with a file parent: {member}")
        for name in REQUIRED_FILES:
            if prefix + name not in members:
                raise ValueError(f"Missing package requirement: {name}")
        manifest = json.loads(package.read(manifest_info))
        if (not isinstance(manifest, dict) or type(manifest.get("format_version")) is not int
                or manifest["format_version"] != 1 or manifest.get("plugin") != PLUGIN_NAME
                or not isinstance(manifest.get("version"), str) or not manifest["version"]
                or not isinstance(manifest.get("files"), dict)):
            raise ValueError("Invalid package manifest identity or schema")
        declared = manifest["files"]
        if any(not isinstance(name, str) or not isinstance(digest, str)
               or re.fullmatch(r"[0-9a-f]{64}", digest) is None for name, digest in declared.items()):
            raise ValueError("Invalid package manifest file hashes")
        actual = set(members) - {prefix + "PACKAGE_MANIFEST.json"}
        if actual != {prefix + name for name in declared}:
            raise ValueError("Archive contents differ from manifest")
        for name, digest in declared.items():
            if hashlib.sha256(package.read(prefix + name)).hexdigest() != digest:
                raise ValueError(f"Hash mismatch: {name}")
        metadata = configparser.ConfigParser(interpolation=None)
        try:
            metadata.read_string(package.read(prefix + "metadata.txt").decode("utf-8-sig"))
            version = metadata.get("general", "version")
        except (configparser.Error, UnicodeError) as exc:
            raise ValueError("Invalid packaged metadata") from exc
        if version != manifest["version"]:
            raise ValueError("Package manifest version differs from metadata")
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
