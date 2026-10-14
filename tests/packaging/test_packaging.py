import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile
import xmlrpc.client

import pytest

from scripts import plugin_upload
from scripts.build_plugin import ROOT, RUNTIME_DIRECTORIES, build_plugin, package_files, verify_package


def test_package_is_reproducible_complete_and_excludes_user_data(tmp_path):
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    build_plugin(first)
    build_plugin(second)
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    manifest = verify_package(first)
    assert "core/pypoprf/utils/runtime.py" in manifest["files"]
    from core.pypoprf import __version__
    assert manifest["version"] == __version__
    with zipfile.ZipFile(first) as package:
        names = package.namelist()
        assert not any(any(part in name for part in ("case_study", "audit_", "/tests/", "/deps/"))
                       for name in names)


def test_package_failure_preserves_previous_zip(tmp_path):
    target = tmp_path / "existing.zip"
    target.write_bytes(b"previous")
    with pytest.raises(ValueError, match="Missing"):
        build_plugin(target, root=tmp_path / "nonexistent")
    assert target.read_bytes() == b"previous"


@pytest.mark.parametrize("name", ["README.md", "metadata.txt", "__init__.py"])
def test_build_cannot_replace_nonarchive_source_files(tmp_path, name):
    source = tmp_path / name
    source.write_bytes(b"trusted source")
    with pytest.raises(ValueError, match=".zip archive"):
        build_plugin(source)
    assert source.read_bytes() == b"trusted source"


def copy_runtime_source(destination):
    for name, source in package_files(ROOT):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


@pytest.mark.parametrize("directory", RUNTIME_DIRECTORIES)
def test_build_cannot_write_an_archive_into_any_runtime_package(tmp_path, directory):
    source = copy_runtime_source(tmp_path / "source")
    destination = source / directory / "preserved.zip"
    destination.write_bytes(b"previous archive")
    with pytest.raises(ValueError, match="source package"):
        build_plugin(destination, root=source)
    assert destination.read_bytes() == b"previous archive"


@pytest.mark.parametrize("missing", [
    "core/__init__.py", "core/pypoprf/__main__.py", "core/pypoprf/algorithms/model.py",
    "core/pypoprf/utils/zone_ids.py",
    "gui/__init__.py", "controllers/__init__.py", "services/__init__.py", "shared/__init__.py",
    "services/engine_snapshot.py",
    "services/project_location.py", "gui/widgets/workflow_status.py", "gui/widgets/visual_style.py",
    "gui/widgets/fitted_label.py",
    "gui/widgets/light_theme.py", "gui/icons/check.svg", "gui/icons/down.svg",
    "gui/icons/partial.svg", "gui/icons/up.svg", "gui/icons/radio.svg",
    "gui/icons/play.svg", "gui/icons/play-disabled.svg", "gui/icons/stop.svg", "gui/icons/stop-disabled.svg",
    "gui/presenters/project_presenter.py", "docs/user-guide/projects.md",
    "docs/assets/screenshots/project.png",
    "docs/assets/screenshots/home.png", "docs/assets/screenshots/engine.png",
    "docs/assets/screenshots/workflow.png", "docs/assets/screenshots/quality.png",
])
def test_missing_runtime_boundary_file_cannot_publish_an_incomplete_archive(tmp_path, missing):
    source = copy_runtime_source(tmp_path / "source")
    (source / missing).unlink()
    destination = tmp_path / "preserved.zip"
    destination.write_bytes(b"previous archive")
    with pytest.raises(ValueError, match="Missing"):
        build_plugin(destination, root=source)
    assert destination.read_bytes() == b"previous archive"


def test_relocated_upload_module_help_has_no_publication_side_effect():
    completed = subprocess.run([sys.executable, "-m", "scripts.plugin_upload", "--help"],
                               cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert "archive" in completed.stdout and "username" in completed.stdout


def test_packaged_readme_and_guides_have_no_dangling_local_links_or_images(tmp_path):
    archive = tmp_path / "documentation.zip"
    build_plugin(archive)
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            contents = package.read(name).decode("utf-8")
            for link in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", contents):
                if link.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                target = link.split("#", 1)[0]
                normalized = Path(name).parent.joinpath(target)
                # Normalize ../ without using host drive/path semantics.
                parts = []
                for part in normalized.parts:
                    if part == "..":
                        assert parts, (name, link)
                        parts.pop()
                    elif part != ".":
                        parts.append(part)
                assert "/".join(parts) in names, (name, link)
        for screenshot in ("home", "engine", "project", "workflow", "quality"):
            assert package.read(f"pypopRF/docs/assets/screenshots/{screenshot}.png").startswith(b"\x89PNG\r\n\x1a\n")


def test_password_special_characters_encoded_and_never_logged(tmp_path, capsys):
    archive = tmp_path / "plugin.zip"
    archive.write_bytes(b"test archive")
    captured = []

    class Proxy:
        def __init__(self, address, verbose):
            captured.append(address)
            self.plugin = SimpleNamespace(upload=lambda data: (1, 2))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    assert plugin_upload.upload(archive, "alice@x", "a:b@c?", proxy_factory=Proxy) == (1, 2)
    assert "alice%40x:a%3Ab%40c%3F@" in captured[0]
    printed = capsys.readouterr().out
    assert "alice" not in printed and "a:b@c?" not in printed
    assert "https://plugins.qgis.org:443/plugins/RPC2/" in printed


def test_protocol_failure_is_nonzero_and_does_not_echo_server_secrets(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "alice")
    monkeypatch.setattr(plugin_upload.getpass, "getpass", lambda prompt: "secret")

    def failed(*args):
        raise xmlrpc.client.ProtocolError("https://alice:secret@server", 401, "secret", {"auth": "secret"})

    monkeypatch.setattr(plugin_upload, "upload", failed)
    assert plugin_upload.main(["fake.zip"]) == 1
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


def test_pb_tool_lists_are_literal_valid_paths():
    import configparser

    config = configparser.ConfigParser()
    config.read(ROOT / "pb_tool.cfg")
    for key in ("python_files", "extras", "extra_dirs"):
        for name in config["files"][key].split():
            assert (ROOT / name).exists(), name
