"""Reject portable-path aliases and false package identity without extraction."""
import hashlib
import json
import stat
import zipfile

import pytest

from scripts.build_plugin import build_plugin, verify_package
from scripts import build_plugin as builder


@pytest.fixture
def package_entries(tmp_path):
    archive = tmp_path / "valid.zip"
    build_plugin(archive)
    with zipfile.ZipFile(archive) as package:
        return {info.filename: package.read(info) for info in package.infolist()}


def mutated_archive(tmp_path, entries, *, member=None, field=None, value=None, mode=stat.S_IFREG):
    manifest_name = "pypopRF/PACKAGE_MANIFEST.json"
    manifest = json.loads(entries[manifest_name])
    if member is not None:
        data = b"# synthetic, never executed\n"
        entries[member] = data
        manifest["files"][member[len("pypopRF/"):]] = hashlib.sha256(data).hexdigest()
    if field is not None:
        manifest[field] = value
    entries[manifest_name] = json.dumps(manifest).encode()
    archive = tmp_path / "mutated.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            # ZipInfo normalizes the host separator in its constructor on
            # Windows; retain the malicious ZIP spelling for the actual test.
            info.filename = name
            info.create_system = 3
            info.external_attr = ((mode if name == member else stat.S_IFREG) | 0o644) << 16
            output.writestr(info, data)
    return archive


@pytest.mark.parametrize("member", [
    "pypopRF/gui//stray.py", "pypopRF/gui/./stray.py", "pypopRF/gui/../stray.py",
    "pypopRF/gui/CON.py", "pypopRF/gui/NUL.tar.gz", "pypopRF/gui/COM¹.py",
    "pypopRF/gui/CONIN$.py", "pypopRF/gui/CONOUT$.py",
    "pypopRF/gui/CON .py", "pypopRF/gui/COM1 .py",
    "pypopRF/gui/stray.py.", "pypopRF/gui/stray.py ", "pypopRF/gui/stray.py:stream",
    "pypopRF/ICON.PNG", "pypopRF/gui\\stray.py", "pypopRF/gui/stray\x01.py",
    "pypopRF/icon.png/child.py", "pypopRF/ICON.PNG/child.py",
])
def test_portable_aliases_and_file_parent_conflicts_are_rejected(tmp_path, package_entries, member):
    archive = mutated_archive(tmp_path, package_entries, member=member)
    with pytest.raises(ValueError, match="archive member"):
        verify_package(archive)


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO])
def test_only_regular_zip_members_are_supported(tmp_path, package_entries, mode):
    archive = mutated_archive(tmp_path, package_entries, member="pypopRF/gui/stray.py", mode=mode)
    with pytest.raises(ValueError, match="archive member"):
        verify_package(archive)


@pytest.mark.parametrize("field,value", [
    ("format_version", 99), ("format_version", True), ("plugin", "wrong"),
    ("version", "9.9.9"), ("version", None), ("files", []),
    ("files", {"__init__.py": "not-a-hash"}),
])
def test_manifest_schema_and_packaged_identity_agree(tmp_path, package_entries, field, value):
    archive = mutated_archive(tmp_path, package_entries, field=field, value=value)
    with pytest.raises(ValueError, match="manifest"):
        verify_package(archive)


def test_size_limit_is_checked_before_opening_archive(tmp_path, monkeypatch):
    archive = tmp_path / "oversized.zip"
    with archive.open("wb") as output:
        output.truncate(25_000_001)
    monkeypatch.setattr(zipfile, "ZipFile", lambda *_args: pytest.fail("Oversized archive must not be opened"))
    with pytest.raises(ValueError, match="25 MB"):
        verify_package(archive)


def test_manifest_size_is_checked_before_full_read(tmp_path, package_entries, monkeypatch):
    package_entries["pypopRF/PACKAGE_MANIFEST.json"] = b" " * (4 * 1024 * 1024 + 1)
    archive = tmp_path / "large-manifest.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in package_entries.items():
            package.writestr(name, data)
    original_read = zipfile.ZipFile.read

    def guarded_read(package, name, *args, **kwargs):
        filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert filename != "pypopRF/PACKAGE_MANIFEST.json", "Must reject before materializing oversized JSON"
        return original_read(package, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", guarded_read)
    with pytest.raises(ValueError, match="manifest.*large"):
        verify_package(archive)


def test_valid_archive_still_verifies(tmp_path, package_entries):
    archive = mutated_archive(tmp_path, package_entries)
    assert verify_package(archive)["plugin"] == "pypopRF"


@pytest.mark.parametrize("budget,value", [
    ("MAX_ARCHIVE_FILES", 1), ("MAX_MEMBER_BYTES", 1), ("MAX_EXPANDED_BYTES", 1),
])
def test_expansion_budgets_reject_before_crc_or_content_read(tmp_path, package_entries, monkeypatch, budget, value):
    archive = mutated_archive(tmp_path, package_entries)
    monkeypatch.setattr(builder, budget, value)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda *_args: pytest.fail("Budget must precede CRC expansion"))
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_args: pytest.fail("Budget must precede materialization"))
    with pytest.raises(ValueError, match="budget"):
        verify_package(archive)


def test_post_build_verification_failure_preserves_previous_archive(tmp_path, monkeypatch):
    archive = tmp_path / "preserved.zip"
    archive.write_bytes(b"previous archive")

    def fail(_archive):
        raise ValueError("injected final verification failure")

    monkeypatch.setattr(builder, "verify_package", fail)
    with pytest.raises(ValueError, match="final verification"):
        build_plugin(archive)
    assert archive.read_bytes() == b"previous archive"
    assert list(tmp_path.iterdir()) == [archive]
