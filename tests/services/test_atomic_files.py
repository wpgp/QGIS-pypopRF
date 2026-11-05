import errno
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shared import atomic_files
from core.pypoprf.utils.runtime import atomic_output, CancellationToken, CancelledError


@pytest.fixture
def files(tmp_path):
    source, target = tmp_path / "staging", tmp_path / "published"
    source.write_bytes(b"new complete artifact")
    target.write_bytes(b"previous trusted artifact")
    return source, target


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_reader_sharing_retries_then_atomically_publishes(files, monkeypatch, winerror):
    source, target = files
    original = os.replace
    attempts, delays = [], []
    def sharing_reader(staging, destination):
        attempts.append((staging, destination))
        if len(attempts) <= 2:
            assert source.exists() and target.read_bytes() == b"previous trusted artifact"
            error = OSError("Reader currently denies delete sharing")
            error.winerror = winerror
            raise error
        original(staging, destination)
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "replace", sharing_reader)
    monkeypatch.setattr(atomic_files.time, "sleep", delays.append)
    atomic_files.atomic_replace(source, target)
    assert len(attempts) == 3 and delays == [0.02, 0.04]
    assert not source.exists() and target.read_bytes() == b"new complete artifact"


@pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM])
def test_permanent_windows_permission_error_is_bounded_and_keeps_both_files(files, monkeypatch, code):
    source, target = files
    attempts, delays = [], []
    def deny(*args):
        attempts.append(args)
        raise PermissionError(code, "persistent permission denial")
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "replace", deny)
    monkeypatch.setattr(atomic_files.time, "sleep", delays.append)
    with pytest.raises(PermissionError, match="persistent"):
        atomic_files.atomic_replace(source, target)
    assert len(attempts) == 6
    assert sum(delays) == pytest.approx(0.62)
    assert target.read_bytes() == b"previous trusted artifact"
    assert source.read_bytes() == b"new complete artifact"


@pytest.mark.parametrize("windows,code", [(False, errno.EACCES), (False, errno.EPERM),
                                        (True, errno.EIO), (True, errno.ENOENT), (True, errno.EXDEV)])
def test_unix_and_unrelated_errors_are_never_retried_or_ignored(files, monkeypatch, windows, code):
    source, target = files
    attempts = []
    def fail(*args):
        attempts.append(args)
        raise OSError(code, "real filesystem failure")
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", windows)
    monkeypatch.setattr(os, "replace", fail)
    monkeypatch.setattr(atomic_files.time, "sleep", lambda _: pytest.fail("Must not retry"))
    with pytest.raises(OSError) as caught:
        atomic_files.atomic_replace(source, target)
    assert caught.value.errno == code and len(attempts) == 1
    assert source.is_file() and target.read_bytes() == b"previous trusted artifact"


@pytest.mark.parametrize("cancel_before", [False, True])
def test_cancellation_before_publication_never_overwrites_existing_target(files, monkeypatch, cancel_before):
    source, target = files
    token, attempts = CancellationToken(), []
    if cancel_before:
        token.cancel()
    def deny(*args):
        attempts.append(args)
        raise PermissionError(errno.EACCES, "sharing violation")
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "replace", deny)
    monkeypatch.setattr(atomic_files.time, "sleep", lambda _: token.cancel())
    with pytest.raises(CancelledError):
        atomic_files.atomic_replace(source, target, token.check)
    assert len(attempts) == (0 if cancel_before else 1)
    assert source.is_file() and target.read_bytes() == b"previous trusted artifact"


def test_cancellation_after_success_does_not_report_uncommitted_publication(files):
    source, target = files
    checks = []
    def check():
        checks.append(True)
        if len(checks) > 1:
            raise CancelledError("A committed replacement must not be reported as cancelled")
    atomic_files.atomic_replace(source, target, check)
    assert len(checks) == 1
    assert target.read_bytes() == b"new complete artifact"


def test_atomic_output_cleans_only_staging_when_retry_is_cancelled(tmp_path, monkeypatch):
    target = tmp_path / "result.bin"
    target.write_bytes(b"trusted")
    token = CancellationToken()
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", True)
    def deny(*args):
        raise PermissionError(errno.EACCES, "sharing violation")
    monkeypatch.setattr(os, "replace", deny)
    monkeypatch.setattr(atomic_files.time, "sleep", lambda _: token.cancel())
    with pytest.raises(CancelledError):
        with atomic_output(target, token) as staging:
            staging.write_bytes(b"complete but unpublished")
    assert target.read_bytes() == b"trusted"
    assert list(tmp_path.iterdir()) == [target]


def test_plugin_namespace_and_top_level_engine_import_the_correct_atomic_helper(tmp_path):
    package = "pypoprf_atomic_import_probe"
    script = f"""import importlib, pathlib, sys, types
root = pathlib.Path({str(Path(__file__).resolve().parents[2])!r})
plugin = types.ModuleType({package!r}); plugin.__path__ = [str(root)]
sys.modules[{package!r}] = plugin
runtime = importlib.import_module({(package + '.core.pypoprf.utils.runtime')!r})
manager = importlib.import_module({(package + '.services.runtime_manager')!r})
helper = importlib.import_module({(package + '.shared.atomic_files')!r})
assert runtime.atomic_replace is helper.atomic_replace
assert manager.atomic_replace is helper.atomic_replace
assert not any(name in sys.modules for name in ('numpy', 'rasterio', 'qgis', 'sklearn'))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert importlib.import_module("core.pypoprf.utils.runtime").atomic_replace is atomic_files.atomic_replace


def test_runtime_pointer_uses_shared_atomic_helper(tmp_path, monkeypatch):
    from services.runtime_manager import RuntimeManager
    target = tmp_path / "active.json"
    target.write_text("previous", encoding="utf-8")
    original, attempts = os.replace, []
    def reader(*args):
        attempts.append(args)
        if len(attempts) < 3:
            raise PermissionError(errno.EACCES, "another reader")
        original(*args)
    monkeypatch.setattr(atomic_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "replace", reader)
    monkeypatch.setattr(atomic_files.time, "sleep", lambda _: None)
    RuntimeManager._write_json(target, {"ready": True})
    assert len(attempts) == 3 and json.loads(target.read_text()) == {"ready": True}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("alias", ["", "pypoprf_shared_contract_probe."])
def test_tools_and_shared_environment_import_without_provisioning_or_host_mutation(alias):
    root = Path(__file__).resolve().parents[2]
    script = f"""import importlib, os, pathlib, sys, types
root = pathlib.Path({str(root)!r})
sys.path.insert(0,str(root))
prefix = {alias!r}
if prefix:
    plugin = types.ModuleType(prefix[:-1]); plugin.__path__ = [str(root)]
    sys.modules[prefix[:-1]] = plugin
sys.modules[prefix+'services'] = None
before = dict(os.environ)
environment = importlib.import_module(prefix+'shared.runtime_environment')
tools = importlib.import_module(prefix+'core.pypoprf.tools')
assert tools.NATIVE_THREAD_LIMITS is environment.NATIVE_THREAD_LIMITS
assert dict(os.environ) == before
child = environment.child_environment(sys.executable)
assert all(child[key] == '1' for key in environment.NATIVE_THREAD_LIMITS)
assert dict(os.environ) == before
assert not any(name in sys.modules for name in ('numpy','rasterio','qgis','sklearn'))
"""
    result = subprocess.run([sys.executable, "-I", "-c", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
