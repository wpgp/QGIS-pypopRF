import hashlib
from types import SimpleNamespace
import zipfile
import xmlrpc.client

import pytest

import plugin_upload
from scripts.build_plugin import ROOT, build_plugin, verify_package


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
