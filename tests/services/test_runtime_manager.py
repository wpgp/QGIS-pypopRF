from concurrent.futures import ThreadPoolExecutor
import base64
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from threading import Event
import zipfile
import shutil

import pytest

from services.runtime_manager import RuntimeManager, RuntimeBusy, RuntimeNotReady, RuntimeSetupError
from core.pypoprf.utils.runtime import CancellationToken, CancelledError


def pinned(name, version, digest="a" * 64):
    return f"{name}=={version} --hash=sha256:{digest}\n"


@pytest.fixture
def manager(tmp_path, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    (package / "requirements-engine.lock").write_text("-r requirements.txt\n" + pinned("helper", "2.0"), encoding="utf-8")
    (package / "requirements.txt").write_text(pinned("tiny-package", "1.0"), encoding="utf-8")
    instance = RuntimeManager(package, tmp_path / "user-cache")
    source_python = tmp_path / "source-python"
    source_python.write_bytes(b"original host interpreter placeholder")
    instance.source_python = source_python
    instance.calls = []
    def fake_run(command, cancellation_token=None, progress=None, percent=0, timeout=300):
        instance._check_cancel(cancellation_token)
        instance.calls.append([str(argument) for argument in command])
        if "venv" in command:
            environment = Path(command[-1])
            executable = instance._python_in(environment)
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"engine interpreter placeholder")
            (environment / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
            return "Created virtual environment\n"
        if "install" in command:
            return "Installed wheels\n"
        if "check" in command:
            return "No broken requirements found.\n"
        if "-c" in command and "_base_executable" in command[command.index("-c") + 1]:
            return json.dumps(dict(executable=str(instance.source_python), version=[3, 12, 10],
                                   bits=64, implementation="CPython", prefix=str(tmp_path), base_prefix=str(tmp_path)))
        if "-c" in command:
            return json.dumps(dict(version=[3, 12, 10], prefix=str(command[-1]), versions=json.loads(command[-2])))
        raise AssertionError(f"Unexpected command: {command}")
    monkeypatch.setattr(instance, "_run", fake_run)
    return instance


def test_provision_idempotence_exact_pins_and_no_host_mutations(manager):
    source_before = manager.source_python.read_bytes()
    package_before = {p.name: p.read_bytes() for p in manager.package_root.iterdir()}
    progress = []
    python = manager.setup(manager.source_python, lambda value, message: progress.append(value))
    assert python.is_file() and python.is_relative_to(manager.cache_root)
    assert progress[-1] == 100
    assert progress == sorted(progress)
    assert manager.runtime_ready()
    assert manager.get_python() == python
    first_installs = sum("install" in call for call in manager.calls)
    assert manager.setup(manager.source_python) == python
    assert sum("install" in call for call in manager.calls) == first_installs == 1
    install = next(call for call in manager.calls if "install" in call)
    assert "--only-binary=:all:" in install and "--isolated" in install and "--require-hashes" in install
    assert Path(install[0]) == python
    assert "-I" in install
    environment = python.parent.parent
    assert (environment / "READY.json").is_file()
    assert (environment / "requirements" / "requirements.txt").read_bytes() == package_before["requirements.txt"]
    assert manager.source_python.read_bytes() == source_before
    assert {p.name: p.read_bytes() for p in manager.package_root.iterdir()} == package_before


def test_new_environment_name_shortens_windows_paths_without_weakening_owner(manager):
    python = manager.setup(manager.source_python)
    directory = python.parent.parent
    assert directory.name.startswith("e-") and len(directory.name) == 34
    assert manager.ENV_PATTERN.fullmatch(directory.name)
    owner = json.loads((directory / "OWNER.json").read_text())["id"]
    assert len(owner) == 32 and owner != directory.name[2:]
    assert len("engine-" + "a" * 12 + "-" + "b" * 32) - len(directory.name) == 18
    marker = json.loads((directory / "READY.json").read_text())
    assert marker["fingerprint"] == manager._requirements()["fingerprint"]
    assert manager.get_python() == python


@pytest.mark.parametrize("name", ["e-a", "e-" + "a" * 31, "e-" + "a" * 33,
                                  "e-" + "G" * 32, "e-../outside", "foreign-folder"])
def test_short_environment_names_still_reject_unowned_forms(manager, name):
    with pytest.raises(RuntimeNotReady, match="Invalid engine environment name"):
        manager._owned_environment(name)


def test_legacy_active_environment_remains_read_only_and_usable(manager):
    python = manager.setup(manager.source_python)
    fingerprint = manager._requirements()["fingerprint"]
    legacy = manager.env_root / ("engine-" + fingerprint[:12] + "-" + "d" * 32)
    # Fake owned test environments only; production never relocates a venv.
    shutil.copytree(python.parent.parent, legacy)
    active = json.loads(manager.active_path.read_text())
    active["environment"] = legacy.name
    manager._write_json(manager.active_path, active)
    before = {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    pointer = manager.active_path.read_bytes()
    expected = manager._python_in(legacy)
    assert manager.get_python() == expected
    assert manager.setup(manager.package_root / "missing-base-python") == expected
    assert manager.active_path.read_bytes() == pointer
    assert before == {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}


def test_offline_rollback_reuses_legacy_name_without_moving_or_rebuilding(manager):
    first = manager.setup(manager.source_python)
    previous = (manager.package_root / "requirements.txt").read_bytes()
    fingerprint = manager._requirements()["fingerprint"]
    legacy = manager.env_root / ("engine-" + fingerprint[:12] + "-" + "d" * 32)
    shutil.copytree(first.parent.parent, legacy)
    # Force the scan to skip the separate modern-name test copy, not delete it.
    (first.parent.parent / "OWNER.json").write_text('{}', encoding="utf-8")
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    second = manager.setup(manager.source_python)
    (manager.package_root / "requirements.txt").write_bytes(previous)
    before = {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    calls = len(manager.calls)
    assert manager.setup(manager.package_root / "missing-base-python") == manager._python_in(legacy)
    assert not any("venv" in command or "install" in command for command in manager.calls[calls:])
    assert first.exists() and second.exists()
    assert before == {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}


def test_failed_new_upgrade_preserves_legacy_pointer_and_all_legacy_bytes(manager, monkeypatch):
    first = manager.setup(manager.source_python)
    fingerprint = manager._requirements()["fingerprint"]
    legacy = manager.env_root / ("engine-" + fingerprint[:12] + "-" + "d" * 32)
    shutil.copytree(first.parent.parent, legacy)
    active = json.loads(manager.active_path.read_text())
    active["environment"] = legacy.name
    manager._write_json(manager.active_path, active)
    before = {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    pointer = manager.active_path.read_bytes()
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    original = manager._run
    def fail_install(command, *args, **kwargs):
        if "install" in command:
            raise RuntimeSetupError("Network unavailable during new-name upgrade")
        return original(command, *args, **kwargs)
    monkeypatch.setattr(manager, "_run", fail_install)
    with pytest.raises(RuntimeSetupError, match="Network"):
        manager.setup(manager.source_python)
    assert manager.active_path.read_bytes() == pointer
    assert before == {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    assert first.exists() and len(list(manager.env_root.iterdir())) == 2


@pytest.mark.parametrize("contents,accepted", [
    ("home = owned-base\ninclude-system-site-packages = false\n", True),
    ("# include-system-site-packages = true\ninclude-system-site-packages = false\n", True),
    ("include-system-site-packages = true\n# include-system-site-packages = false\n", False),
    ("include-system-site-packages = false\ninclude-system-site-packages = true\n", False),
    ("include-system-site-packages = false\ninclude-system-site-packages = false\n", False),
    ("# include-system-site-packages = false\n", False),
    ("include-system-site-packages = false # comment\n", False),
    ("include-system-site-packages = false-ish\n", False),
    ("include-system-site-packages\n", False),
    ("prompt = note\vinclude-system-site-packages = false\n", False),
    ("prompt = note\finclude-system-site-packages = false\n", False),
    ("prompt = note\u0085include-system-site-packages = false\n", False),
    ("prompt = note\u2028include-system-site-packages = false\n", False),
    ("home = owned-base\rinclude-system-site-packages = false\r", True),
    ("  INCLUDE-SYSTEM-SITE-PACKAGES = FALSE  \n", True),
])
def test_pyvenv_cfg_isolation_requires_one_actual_false_field(manager, contents, accepted):
    python = manager.setup(manager.source_python)
    directory = python.parent.parent
    (directory / "pyvenv.cfg").write_text(contents, encoding="utf-8")
    before = len(manager.calls)
    if accepted:
        assert manager._health(directory, manager._requirements())["versions"] == manager._requirements()["pins"]
    else:
        with pytest.raises(RuntimeNotReady, match="isolated|system.site"):
            manager._health(directory, manager._requirements())
        assert len(manager.calls) == before


@pytest.mark.parametrize("payload", [b"", b"outside control file"])
def test_setup_lock_hardlink_refused_before_seed_or_setup(manager, tmp_path, payload):
    outside = tmp_path / "outside-control"
    outside.write_bytes(payload)
    manager.cache_root.mkdir()
    path = manager.cache_root / "setup.lock"
    os.link(outside, path)
    with pytest.raises(RuntimeSetupError, match="dedicated ordinary"):
        with manager._setup_lock():
            pytest.fail("Hardlinked lock must not be acquired")
    assert outside.read_bytes() == payload and path.read_bytes() == payload
    assert not manager.active_path.exists() and not manager.env_root.exists()


def test_setup_lock_symlink_refused_before_seed(manager, tmp_path):
    outside = tmp_path / "outside-control"
    outside.write_bytes(b"")
    manager.cache_root.mkdir()
    path = manager.cache_root / "setup.lock"
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("This platform/user cannot create symbolic links")
    with pytest.raises(RuntimeSetupError, match="Unsafe"):
        with manager._setup_lock():
            pytest.fail("Symlinked lock must not be acquired")
    assert outside.read_bytes() == b"" and path.is_symlink()


def test_setup_lock_control_replaced_after_open_refused_before_seed(manager, tmp_path, monkeypatch):
    manager.cache_root.mkdir()
    path = manager.cache_root / "setup.lock"
    path.write_bytes(b"")
    outside = tmp_path / "outside-control"
    outside.write_bytes(b"")
    original = Path.open
    def replaced(self, *args, **kwargs):
        if self == path and args and args[0] == "a+b":
            handle = original(outside, *args, **kwargs)
            return handle
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", replaced)
    with pytest.raises(RuntimeSetupError, match="changed"):
        with manager._setup_lock():
            pytest.fail("Changed fd/path identity must not be acquired")
    assert outside.read_bytes() == b"" and path.read_bytes() == b""


def test_nested_requirements_change_makes_active_runtime_stale(manager):
    old_python = manager.setup(manager.source_python)
    old_active = manager.active_path.read_bytes()
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    assert not manager.runtime_ready()
    assert "update" in manager.last_error
    assert old_python.exists()
    new_python = manager.setup(manager.source_python)
    assert new_python != old_python
    assert old_python.exists()
    assert manager.active_path.read_bytes() != old_active
    assert manager.get_python() == new_python


def test_failed_upgrade_preserves_previous_environment_and_pointer(manager, monkeypatch):
    old_python = manager.setup(manager.source_python)
    active_before = manager.active_path.read_bytes()
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    original = manager._run
    def fail_install(command, *args, **kwargs):
        if "install" in command:
            raise RuntimeSetupError("Network is unavailable")
        return original(command, *args, **kwargs)
    monkeypatch.setattr(manager, "_run", fail_install)
    with pytest.raises(RuntimeSetupError, match="Network"):
        manager.setup(manager.source_python)
    assert manager.active_path.read_bytes() == active_before
    assert old_python.exists()
    assert len(list(manager.env_root.iterdir())) == 1


def test_cancelled_creation_removes_only_attempt_directory(manager, monkeypatch):
    token = CancellationToken()
    original = manager._run
    unrelated = manager.cache_root / "my-unrelated-folder"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
    def cancel_install(command, *args, **kwargs):
        result = original(command, *args, **kwargs)
        if "install" in command:
            token.cancel()
        return result
    monkeypatch.setattr(manager, "_run", cancel_install)
    with pytest.raises(CancelledError):
        manager.setup(manager.source_python, cancellation_token=token)
    assert not list(manager.env_root.iterdir())
    assert not manager.active_path.exists()
    assert (unrelated / "keep.txt").read_text() == "keep"


def test_health_failure_cannot_publish_ready_marker(manager, monkeypatch):
    monkeypatch.setattr(manager, "_health", lambda *args: (_ for _ in ()).throw(RuntimeNotReady("Native imports failed")))
    with pytest.raises(RuntimeNotReady, match="Native imports"):
        manager.setup(manager.source_python)
    assert not manager.active_path.exists()
    assert not list(manager.env_root.iterdir())


def test_requirements_changed_during_setup_cannot_publish(manager, monkeypatch):
    original = manager._health
    def change_package(environment, requirements, token=None):
        report = original(environment, requirements, token)
        (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.2"), encoding="utf-8")
        return report
    monkeypatch.setattr(manager, "_health", change_package)
    with pytest.raises(RuntimeSetupError, match="changed during setup"):
        manager.setup(manager.source_python)
    assert not manager.active_path.exists()
    assert not list(manager.env_root.iterdir())


def test_requirements_changed_at_fresh_activation_preserves_previous_engine(manager):
    old_python = manager.setup(manager.source_python)
    previous_pointer = manager.active_path.read_bytes()
    previous_marker = (old_python.parent.parent / "READY.json").read_bytes()
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    def change_at_activation(percent, message):
        if percent == 95:
            (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.2"), encoding="utf-8")
    with pytest.raises(RuntimeSetupError, match="changed during setup"):
        manager.setup(manager.source_python, progress=change_at_activation)
    assert manager.active_path.read_bytes() == previous_pointer
    assert (old_python.parent.parent / "READY.json").read_bytes() == previous_marker
    assert old_python.exists()
    assert len(list(manager.env_root.iterdir())) == 1


@pytest.mark.parametrize("corruption", ["missing_marker", "marker_json", "marker_fingerprint", "pointer_json", "pointer_path", "interpreter", "versions", "system_site"])
def test_missing_partial_corrupt_stale_environments_are_not_ready(manager, corruption):
    python = manager.setup(manager.source_python)
    environment = python.parent.parent
    marker = environment / "READY.json"
    if corruption == "missing_marker":
        marker.unlink()
    elif corruption == "marker_json":
        marker.write_text("[]", encoding="utf-8")
    elif corruption == "marker_fingerprint":
        content = json.loads(marker.read_text())
        content["fingerprint"] = "outdated"
        marker.write_text(json.dumps(content), encoding="utf-8")
    elif corruption == "pointer_json":
        manager.active_path.write_text("[]", encoding="utf-8")
    elif corruption == "pointer_path":
        pointer = json.loads(manager.active_path.read_text())
        pointer["environment"] = "../../source-python"
        manager.active_path.write_text(json.dumps(pointer), encoding="utf-8")
    elif corruption == "interpreter":
        python.unlink()
    elif corruption == "versions":
        content = json.loads(marker.read_text())
        content["pins"] = {"tiny-package": "wrong"}
        marker.write_text(json.dumps(content), encoding="utf-8")
    elif corruption == "system_site":
        (environment / "pyvenv.cfg").write_text("include-system-site-packages = true", encoding="utf-8")
    assert not manager.runtime_ready()
    with pytest.raises(RuntimeNotReady):
        manager.get_python()
    assert manager.source_python.exists()


def test_concurrent_setup_is_locked_and_released(manager, monkeypatch):
    entered, release = Event(), Event()
    original = manager._run
    def hold_create(command, *args, **kwargs):
        if "venv" in command:
            entered.set()
            assert release.wait(5)
        return original(command, *args, **kwargs)
    monkeypatch.setattr(manager, "_run", hold_create)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(manager.setup, manager.source_python)
        assert entered.wait(5)
        try:
            with pytest.raises(RuntimeBusy, match="already running"):
                manager.setup(manager.source_python)
        finally:
            release.set()
        ready = first.result(timeout=5)
    assert manager.setup(manager.source_python) == ready


def test_lock_releases_after_setup_failure(manager, monkeypatch):
    original = manager._run
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeSetupError("creation failed")))
    with pytest.raises(RuntimeSetupError):
        manager.setup(manager.source_python)
    monkeypatch.setattr(manager, "_run", original)
    assert manager.setup(manager.source_python).is_file()


@pytest.mark.parametrize("line", ["-r ../outside.txt", "-r requirements-engine.lock", "numpy>=1.0", "numpy==1.0\nnumpy==2.0", "--index-url https://example.invalid"])
def test_unsafe_unlocked_or_cyclic_requirements_rejected(manager, line):
    (manager.package_root / "requirements-engine.lock").write_text(line, encoding="utf-8")
    with pytest.raises(RuntimeSetupError):
        manager.setup(manager.source_python)
    assert not manager.env_root.exists()


def test_cache_cannot_overlap_source_package(manager):
    with pytest.raises(ValueError, match="outside"):
        RuntimeManager(manager.package_root, manager.package_root / "cache")


def test_dll_python_and_qgis_environment_are_sanitized(manager, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "host-qgis-site-packages")
    monkeypatch.setenv("QGIS_PREFIX_PATH", "qgis-install")
    monkeypatch.setenv("GDAL_DATA", "foreign-gdal")
    monkeypatch.setenv("QT_PLUGIN_PATH", "foreign-qt")
    monkeypatch.setenv("PIP_INDEX_URL", "https://credentials.invalid")
    monkeypatch.setenv("PROJ_LIB", "foreign-proj")
    monkeypatch.setenv("LD_LIBRARY_PATH", "foreign-libraries")
    env = manager.child_environment(manager.source_python)
    assert not set(env) & {"PYTHONPATH", "QGIS_PREFIX_PATH", "GDAL_DATA", "QT_PLUGIN_PATH", "PIP_INDEX_URL", "PROJ_LIB", "LD_LIBRARY_PATH"}
    assert str(manager.source_python.parent) in env["PATH"]
    import os
    assert os.environ["PYTHONPATH"] == "host-qgis-site-packages"
    assert os.environ["PROJ_LIB"] == "foreign-proj"


def test_runtime_environment_api_delegates_to_shared_contract(manager):
    from shared.runtime_environment import child_environment
    assert manager._environment(manager.source_python) == child_environment(manager.source_python)
    assert manager.child_environment(manager.source_python) == child_environment(manager.source_python)
    assert manager.child_environment() == child_environment()


def test_actual_runtime_child_uses_explicit_external_cwd_without_changing_parent(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    manager = RuntimeManager(package, tmp_path / "cache")
    before = Path.cwd()
    value = json.loads(manager._run([sys.executable, "-I", "-c", "import json,os;print(json.dumps(os.getcwd()))"], timeout=10))
    assert Path(value).resolve() == Path(sys.executable).resolve().parent
    assert not Path(value).is_relative_to(package) and Path.cwd() == before


@pytest.mark.parametrize("failure", ["create", "configure", "assign"])
def test_extracted_windows_job_retains_runtime_error_and_handle_cleanup(monkeypatch, failure):
    import ctypes
    from types import SimpleNamespace
    from services.runtime_manager import _WindowsJob
    calls = []
    class NativeFunction:
        def __init__(self, name, result):
            self.name, self.result = name, result
        def __call__(self, *args):
            calls.append((self.name, args))
            return self.result
    kernel = SimpleNamespace(**{
        "CreateJobObjectW": NativeFunction("create", None if failure == "create" else 123),
        "SetInformationJobObject": NativeFunction("configure", failure != "configure"),
        "AssignProcessToJobObject": NativeFunction("assign", failure != "assign"),
        "TerminateJobObject": NativeFunction("terminate", True),
        "CloseHandle": NativeFunction("close", True),
    })
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 99, raising=False)
    if failure in {"create", "configure"}:
        with pytest.raises(RuntimeSetupError, match="99"):
            _WindowsJob()
        assert ("close", (123,)) in calls if failure == "configure" else not any(name == "close" for name, _ in calls)
    else:
        job = _WindowsJob()
        try:
            with pytest.raises(RuntimeSetupError, match="99"):
                job.assign(SimpleNamespace(_handle=456))
            assert ("assign", (123, 456)) in calls
        finally:
            job.close()
        assert ("close", (123,)) in calls


def test_native_thread_caps_replace_inherited_values_without_mutating_parent(manager, monkeypatch):
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
    for key in keys:
        monkeypatch.setenv(key, "64")
    monkeypatch.setenv("OMP_THREAD_LIMIT", "64")
    before = dict(os.environ)
    env = manager.child_environment(manager.source_python)
    assert all(env[key] == "1" for key in keys)
    assert dict(os.environ) == before


def test_real_child_numerical_native_pools_are_single_threaded(manager):
    modules = ("numpy", "sklearn", "scipy", "threadpoolctl")
    if any(importlib.util.find_spec(module) is None for module in modules):
        pytest.skip("Numerical engine dependencies are not installed in this test interpreter")
    script = ("import json, numpy, sklearn, scipy.linalg; "
              "from threadpoolctl import threadpool_info; print(json.dumps(threadpool_info()))")
    child = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", script],
                           env=manager.child_environment(sys.executable), capture_output=True,
                           text=True, encoding="utf-8", timeout=30, check=True)
    pools = json.loads(child.stdout)
    assert pools, "The integration check must load at least one native numerical pool"
    assert all(pool["num_threads"] <= 1 for pool in pools), pools


def test_actual_probe_and_cancelled_owned_process(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    manager = RuntimeManager(package, tmp_path / "cache")
    token = CancellationToken()
    def cancel_on_output(value, message):
        token.cancel()
    # A real long-lived child emits one line, then waits; cancellation reaps it.
    with pytest.raises(CancelledError):
        manager._run([sys.executable, "-I", "-u", "-c", "import time; print('started',flush=True); time.sleep(30)"],
                     cancellation_token=token, progress=cancel_on_output, timeout=5)
    if sys.version_info[:2] == (3, 12):
        assert manager.check_interpreter(sys.executable)["version"][:2] == [3, 12]
    else:
        with pytest.raises(RuntimeSetupError, match="3.12"):
            manager.check_interpreter(sys.executable)


def test_actual_minimal_venv_keeps_absolute_entrypoints_and_is_ready(tmp_path):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("This engine integration requires Python 3.12")
    package = tmp_path / "package"
    package.mkdir()
    (package / "requirements-engine.lock").write_text("-r requirements.txt\n", encoding="utf-8")
    (package / "requirements.txt").write_text("# lightweight integration: no downloads\n", encoding="utf-8")
    manager = RuntimeManager(package, tmp_path / "cache")
    source = Path(sys.executable)
    before = source.stat().st_mtime_ns
    python = manager.setup(source)
    assert manager.runtime_ready()
    assert manager.get_python() == python
    assert source.stat().st_mtime_ns == before
    report = subprocess.run([python, "-I", "-c", "import sys; print(sys.prefix)"],
                            capture_output=True, text=True, check=True)
    assert Path(report.stdout.strip()).resolve() == python.parent.parent.resolve()
    assert manager.setup(source) == python


def test_owner_marker_failure_leaves_no_partial_environment(manager, monkeypatch):
    monkeypatch.setattr(manager, "_write_json", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        manager.setup(manager.source_python)
    assert not manager.active_path.exists()
    assert not list(manager.env_root.iterdir())


def test_pointer_publication_failure_cleans_new_environment_and_preserves_previous(manager, monkeypatch):
    old_python = manager.setup(manager.source_python)
    previous_pointer = manager.active_path.read_bytes()
    (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    original = manager._write_json
    def fail_pointer(path, content, token=None):
        if path == manager.active_path:
            raise OSError("pointer is read-only")
        original(path, content, token)
    monkeypatch.setattr(manager, "_write_json", fail_pointer)
    with pytest.raises(OSError, match="read-only"):
        manager.setup(manager.source_python)
    assert manager.active_path.read_bytes() == previous_pointer
    assert old_python.exists()
    assert len(list(manager.env_root.iterdir())) == 1


def test_comments_and_nested_file_names_are_part_of_full_fingerprint(manager):
    before = manager._requirements()["fingerprint"]
    nested = manager.package_root / "requirements.txt"
    nested.write_text(nested.read_text() + "# audit-only comment\n", encoding="utf-8")
    assert manager._requirements()["fingerprint"] != before


def test_cleanup_refuses_foreign_directory_and_wrong_ownership(manager):
    before = manager.source_python.read_bytes()
    with pytest.raises(RuntimeNotReady, match="environment name"):
        manager._remove_owned_environment(manager.source_python.parent, "not-owned")
    assert manager.source_python.read_bytes() == before
    python = manager.setup(manager.source_python)
    with pytest.raises(RuntimeSetupError, match="ownership"):
        manager._remove_owned_environment(python.parent.parent, "not-owned")
    assert python.exists()


def test_setup_lock_is_exclusive_across_real_processes(manager):
    code = """import importlib,pathlib,sys,types
package=types.ModuleType('runtime_lock_probe')
package.__path__=[str(pathlib.Path(sys.argv[1]).parent.parent)]
sys.modules[package.__name__]=package
module=importlib.import_module('runtime_lock_probe.services.runtime_manager')
manager=module.RuntimeManager(sys.argv[2],sys.argv[3])
try:
    with manager._setup_lock(): print('unlocked')
except module.RuntimeBusy: print('busy')
"""
    from services import runtime_manager
    command = [sys.executable, "-I", "-c", code, runtime_manager.__file__,
               str(manager.package_root), str(manager.cache_root)]
    with manager._setup_lock():
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10)
        assert result.stdout.strip() == "busy"
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10)
    assert result.stdout.strip() == "unlocked"


def test_readiness_and_discovery_cancel_before_any_subprocess(manager, monkeypatch):
    token = CancellationToken()
    token.cancel()
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: pytest.fail("Cancelled discovery must not start Python"))
    for operation in (manager.get_python, manager.runtime_ready, manager.detect_python_candidates, manager.discover_interpreters):
        with pytest.raises(CancelledError):
            operation(cancellation_token=token)
    with pytest.raises(CancelledError):
        manager.check_interpreter(manager.source_python, cancellation_token=token)


def test_structured_discovery_verifies_deduplicates_and_prefers_standalone(manager, tmp_path, monkeypatch):
    standalone = tmp_path / "independent" / "python.exe"
    embedded = tmp_path / "QGIS" / "apps" / "Python312" / "python.exe"
    incompatible = tmp_path / "wrong" / "python.exe"
    store = tmp_path / "WindowsApps" / "python.exe"
    for path in (standalone, embedded, incompatible, store):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture interpreter")
    monkeypatch.setattr(manager, "_interpreter_candidates", lambda token: [
        ([str(embedded)], "host-base"), ([str(standalone)], "registry-user"),
        ([str(standalone)], "PATH"), ([str(incompatible)], "PATH"), ([str(store)], "PATH")])
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        assert command[1:4] == ["-I", "-X", "utf8"]
        return json.dumps({"executable": command[0], "version": [3, 13 if command[0] == str(incompatible) else 12, 10],
                           "bits": 64, "implementation": "CPython", "prefix": str(Path(command[0]).parent)})
    monkeypatch.setattr(manager, "_run", probe)
    records = manager.discover_interpreters()
    assert records == [{"path": str(standalone), "version": "3.12.10", "bits": 64, "source": "registry-user",
                        "embedded": False, "recommended": True},
                       {"path": str(embedded), "version": "3.12.10", "bits": 64, "source": "qgis-embedded",
                        "embedded": True, "recommended": False}]
    assert len(calls) == 3 and not any(command[0] == str(store) for command in calls)
    assert manager.detect_python_candidates() == [standalone, embedded]


def test_discovery_bound_and_cancellation_between_probes(manager, tmp_path, monkeypatch):
    paths = []
    for index in range(5):
        path = tmp_path / f"python-{index}"
        path.write_bytes(b"fixture")
        paths.append(path)
    monkeypatch.setattr(manager, "_interpreter_candidates", lambda token: [([str(path)], "PATH") for path in paths])
    monkeypatch.setattr(manager, "MAX_DISCOVERY_CANDIDATES", 2)
    calls = []
    token = CancellationToken()
    def probe(command, cancellation_token=None):
        calls.append(command)
        return {"executable": command[0], "version": [3, 12, 1], "bits": 64, "prefix": str(tmp_path)}
    monkeypatch.setattr(manager, "_probe", probe)
    assert len(manager.discover_interpreters()) == 2 and len(calls) == 2
    def cancelled(command, cancellation_token=None):
        token.cancel()
        return probe(command)
    calls.clear()
    monkeypatch.setattr(manager, "_probe", cancelled)
    with pytest.raises(CancelledError):
        manager.discover_interpreters(token)
    assert len(calls) == 1


def test_discovery_prefers_installed_base_over_unrelated_project_venv(manager, tmp_path, monkeypatch):
    venv, base = tmp_path / "aaa-venv-python", tmp_path / "zzz-installed-python"
    for path in (venv, base):
        path.write_bytes(b"fixture")
    monkeypatch.setattr(manager, "_interpreter_candidates", lambda token: [([str(venv)], "PATH"), ([str(base)], "host-base")])
    monkeypatch.setattr(manager, "_probe", lambda command, token=None: {
        "executable": command[0], "version": [3, 12, 10], "bits": 64,
        "prefix": str(tmp_path / "venv") if command[0] == str(venv) else str(tmp_path / "installed"),
        "base_prefix": str(tmp_path / "installed")})
    records = manager.discover_interpreters()
    assert records[0]["path"] == str(base) and records[0]["recommended"] is True
    assert records[1]["path"] == str(venv) and records[1]["recommended"] is False


@pytest.mark.parametrize("version,bits", [([3, 11, 9], 64), ([3, 12, 1], 32)])
def test_selected_interpreter_probe_rejects_incompatible_metadata(manager, monkeypatch, version, bits):
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: json.dumps({
        "executable": str(manager.source_python), "version": version, "bits": bits, "implementation": "CPython"}))
    with pytest.raises(RuntimeSetupError, match="64-bit CPython 3.12"):
        manager.check_interpreter(manager.source_python)
    with pytest.raises(RuntimeSetupError, match="found CPython " + r"\.".join(map(str, version)) + " \\(" + str(bits) + "-bit\\)"):
        manager.check_interpreter(manager.source_python)


@pytest.mark.skipif(os.name != "nt", reason="Readonly Windows PEP514 registry")
def test_registered_discovery_reads_known_keys_no_registry_writes(manager, monkeypatch):
    from types import SimpleNamespace
    opened = []
    class Key:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def open_key(hive, path, unused, access):
        opened.append((hive, path, access))
        return Key(path)
    def query(key, name):
        if name == "ExecutablePath":
            if "3.12-32" in key.path:
                return "relative.exe", 1
            raise FileNotFoundError()
        return str(manager.source_python.parent), 1
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
        KEY_WOW64_64KEY=256, KEY_WOW64_32KEY=512, KEY_READ=16,
        REG_SZ=1, REG_EXPAND_SZ=2, OpenKey=open_key, QueryValueEx=query)
    monkeypatch.setitem(sys.modules, "winreg", registry)
    records = manager._registered_python_candidates()
    assert len(opened) == 12 and records
    assert all(path.startswith("Software\\Python\\PythonCore\\3.12") for _, path, _ in opened)
    assert all(access & registry.KEY_READ for _, _, access in opened)
    assert {source for _, source in records} == {"registry-user", "registry-machine"}
    assert all(Path(command[0]).is_absolute() for command, _ in records)


def test_actual_selected_python_probe_has_structured_compatible_info(tmp_path):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("Requires actual CPython3.12")
    package = tmp_path / "package"
    package.mkdir()
    manager = RuntimeManager(package, tmp_path / "cache")
    before = dict(os.environ)
    info = manager.check_interpreter(sys.executable)
    assert info["version"][:2] == [3, 12] and info["bits"] == 64
    assert Path(info["executable"]).is_file() and info["implementation"] == "CPython"
    assert dict(os.environ) == before and not manager.cache_root.exists()


def test_actual_oversized_unterminated_output_is_bounded_and_reaped(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    manager = RuntimeManager(package, tmp_path / "cache")
    output = manager._run([sys.executable, "-I", "-c", "import sys; sys.stdout.write('x'*(3*1024*1024))"], timeout=10)
    assert 0 < len(output) <= 200 * 2049


def test_parent_exit_does_not_leave_inherited_stdout_child_running(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    manager = RuntimeManager(package, tmp_path / "cache")
    # Use the base interpreter, not a Windows venv redirector, and explicitly
    # prove the parent exited before exercising the inherited-pipe deadline.
    # A 0.3s overall timeout can instead hit interpreter startup under suite load.
    ready = tmp_path / "child-ready"
    launch = tmp_path / "launch-child"
    child_script = ("import os,sys,time; from pathlib import Path; "
                    "Path(sys.argv[1]).write_text(str(os.getpid())); "
                    "print('child ready '+str(os.getpid()),flush=True); time.sleep(10)")
    script = """import subprocess,sys,time
from pathlib import Path
print('parent ready',flush=True)
while not Path(sys.argv[1]).exists(): time.sleep(.005)
subprocess.Popen([sys.executable,'-I','-c',sys.argv[3],sys.argv[2]])
while not Path(sys.argv[2]).exists(): time.sleep(.005)
print('parent exited',flush=True)
"""
    messages = []
    child_handle = None
    kernel = None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
    def observe(percent, message):
        nonlocal child_handle
        messages.append(message)
        if message == "parent ready":
            # _run has already assigned its own job/group before this callback;
            # only now may the fixture create the inherited-stdout descendant.
            launch.touch()
        elif message.startswith("child ready ") and kernel is not None:
            child_handle = kernel.OpenProcess(0x100000, False, int(message.split()[-1]))
            assert child_handle, "Hold the actual child's generation, not just its PID"
    original_terminate = manager._terminate
    parent_exited = []
    def checked_terminate(process, job=None):
        parent_exited.append(process.poll() is not None)
        return original_terminate(process, job)
    manager._terminate = checked_terminate
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeSetupError, match="pipe did not close"):
            manager._run([sys._base_executable, "-I", "-c", script,
                          str(launch), str(ready), child_script], progress=observe, timeout=2)
        assert time.monotonic() - started < 5
        assert "parent exited" in messages and parent_exited == [True]
        assert any(message.startswith("child ready ") for message in messages)
        if kernel is not None:
            assert kernel.WaitForSingleObject(child_handle, 1000) == 0
        else:
            child_pid = int(ready.read_text())
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                # A reaped job must not leave a running child. Linux PID 1 can
                # retain an already-dead orphan zombie in container test runners.
                status = Path(f"/proc/{child_pid}/stat")
                if status.parent.is_dir():
                    try:
                        if status.read_text().split(") ", 1)[1].startswith("Z "):
                            break
                    except FileNotFoundError:
                        break  # Reaped between existence check and /proc read.
                time.sleep(.01)
            else:
                pytest.fail("Inherited-stdout child survived owned group cleanup")
    finally:
        if child_handle is not None:
            kernel.CloseHandle(child_handle)


def test_hash_lock_continuations_multiple_wheels_and_comments(manager):
    text = ("# hash checked wheel alternatives\n"
            "tiny-package==1.0 \\\n"
            "    --hash=sha256:" + "A" * 64 + " \\\n"
            "    --hash=sha256:" + "b" * 64 + " # same version, other platform\n")
    path = manager.package_root / "requirements-engine.lock"
    path.write_text(text, encoding="utf-8", newline="")
    result = manager._requirements()
    assert result["pins"] == {"tiny-package": "1.0"}
    assert result["wheel_hashes"] == {"tiny-package": ["a" * 64, "b" * 64]}
    assert result["files"]["requirements-engine.lock"] == text.encode()


@pytest.mark.parametrize("requirement", [
    "numpy==1.0", "numpy==1.0 --hash=md5:" + "a" * 32,
    "numpy==1.0 --hash=sha256:" + "a" * 63,
    "numpy==1.0 --hash=sha256:" + "g" * 64,
    pinned("numpy", "1.0").strip() + " --no-binary=:all:",
    pinned("numpy", "1.0").strip() + " --index-url https://untrusted.invalid",
    "numpy==1.0 \\\n",
])
def test_unhashed_or_untrusted_hash_lock_cannot_start_installer(manager, requirement):
    (manager.package_root / "requirements-engine.lock").write_text(requirement, encoding="utf-8")
    with pytest.raises(RuntimeSetupError):
        manager.setup(manager.source_python)
    assert not manager.calls
    assert not manager.env_root.exists()


def build_test_wheel(directory):
    """Build a tiny pure wheel using stdlib; no source builder or network needed."""
    files = {
        "tiny_package/__init__.py": b"VALUE = 42\n",
        "tiny_package-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: tiny-package\nVersion: 1.0\n",
        "tiny_package-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: pypoprf-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    records = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        records.append(f"{name},sha256={digest},{len(data)}")
    records.append("tiny_package-1.0.dist-info/RECORD,,")
    files["tiny_package-1.0.dist-info/RECORD"] = ("\n".join(records) + "\n").encode()
    path = directory / "tiny_package-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_actual_wheel_hash_validation_rejects_tampered_upgrade_without_activation(tmp_path, monkeypatch):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("Isolated engine integration requires Python 3.12")
    package = tmp_path / "package"
    wheels = tmp_path / "wheels"
    package.mkdir()
    wheels.mkdir()
    wheel = build_test_wheel(wheels)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = package / "requirements-engine.lock"
    lock.write_text(pinned("tiny-package", "1.0", digest), encoding="utf-8")
    manager = RuntimeManager(package, tmp_path / "cache")
    original = manager._run
    commands = []
    def offline_run(command, *args, **kwargs):
        command = list(command)
        if "install" in command:
            assert "--require-hashes" in command
            index = command.index("--index-url")
            command[index:index + 2] = ["--no-index", "--find-links", str(wheels)]
            commands.append(command)
        return original(command, *args, **kwargs)
    monkeypatch.setattr(manager, "_run", offline_run)
    previous = manager.setup(sys.executable)
    pointer = manager.active_path.read_bytes()
    assert manager.runtime_ready()
    # Still syntactically valid SHA256, but it cannot authenticate the wheel.
    lock.write_text(pinned("tiny-package", "1.0", "0" * 64), encoding="utf-8")
    with pytest.raises(RuntimeSetupError, match="HASHES|hashes"):
        manager.setup(sys.executable)
    assert manager.active_path.read_bytes() == pointer
    assert previous.exists()
    assert len(list(manager.env_root.iterdir())) == 1
    assert len(commands) == 2


def test_unhashed_direct_summary_is_checked_without_becoming_pip_input(manager):
    lock = manager.package_root / "requirements-engine.lock"
    lock.write_text(pinned("tiny-package", "1.0"), encoding="utf-8")
    summary = manager.package_root / "requirements.txt"
    summary.write_text("tiny-package==1.0\n", encoding="utf-8")
    data = manager._requirements()
    assert "requirements.txt" in data["files"]
    assert data["wheel_hashes"] == {"tiny-package": ["a" * 64]}
    manager.setup(manager.source_python)
    command = next(call for call in manager.calls if "install" in call)
    assert Path(command[-1]).name == "requirements-engine.lock"
    summary.write_text("tiny-package==2.0\n", encoding="utf-8")
    with pytest.raises(RuntimeSetupError, match="contradicts"):
        manager._requirements()


def test_production_lock_is_hashed_and_direct_summary_consistent():
    package = Path(__file__).resolve().parents[2]
    manager = RuntimeManager(package, package.parent / "unused-runtime-cache-for-read-test")
    requirements = manager._requirements()
    assert requirements["pins"]
    assert all(requirements["wheel_hashes"].values())
    assert "requirements-engine.lock" in requirements["files"]
    assert "requirements.txt" in requirements["files"]


def rollback_pair(manager):
    summary = manager.package_root / "requirements.txt"
    previous_bytes = summary.read_bytes()
    first = manager.setup(manager.source_python)
    summary.write_text(pinned("tiny-package", "1.1"), encoding="utf-8")
    second = manager.setup(manager.source_python)
    summary.write_bytes(previous_bytes)
    return first, second


def test_offline_a_b_a_reactivates_existing_engine_without_rebuild(manager):
    first, second = rollback_pair(manager)
    previous_pointer = manager.active_path.read_bytes()
    assert not manager.runtime_ready()
    assert manager.active_path.read_bytes() == previous_pointer
    before = len(manager.calls)
    restored = manager.setup(manager.package_root / "no-source-python-needed")
    assert restored == first != second
    assert not any("install" in call or "venv" in call for call in manager.calls[before:])
    assert sum("install" in call for call in manager.calls) == 2
    assert len(list(manager.env_root.iterdir())) == 2
    assert manager.get_python() == first


def test_cancel_reactivation_preserves_active_pointer_and_both_complete_engines(manager):
    first, second = rollback_pair(manager)
    previous_pointer = manager.active_path.read_bytes()
    token = CancellationToken()
    def cancel_before_switch(percent, message):
        if percent == 95:
            token.cancel()
    with pytest.raises(CancelledError):
        manager.setup(manager.source_python, progress=cancel_before_switch, cancellation_token=token)
    assert manager.active_path.read_bytes() == previous_pointer
    assert first.exists() and second.exists()
    assert sum("install" in call for call in manager.calls) == 2


@pytest.mark.parametrize("corruption", ["hash_policy", "owner", "pip_health", "marker_json"])
def test_invalid_preserved_engine_is_skipped_and_never_deleted(manager, monkeypatch, corruption):
    first, second = rollback_pair(manager)
    previous = first.parent.parent
    if corruption == "hash_policy":
        marker_path = previous / "READY.json"
        marker = json.loads(marker_path.read_text())
        marker["install_policy"] = "version-only"
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    elif corruption == "owner":
        (previous / "OWNER.json").write_text('{"id":"not-owned"}', encoding="utf-8")
    elif corruption == "marker_json":
        (previous / "READY.json").write_text('[]', encoding="utf-8")
    else:
        original = manager._health
        def damaged_health(environment, *args):
            if environment == previous:
                raise RuntimeNotReady("Native libraries damaged")
            return original(environment, *args)
        monkeypatch.setattr(manager, "_health", damaged_health)
    restored = manager.setup(manager.source_python)
    assert restored not in {first, second}
    assert first.exists() and second.exists()
    assert sum("install" in call for call in manager.calls) == 3
    assert len(list(manager.env_root.iterdir())) == 3


def test_cached_ready_symlink_outside_environment_is_not_read_or_reused(manager, monkeypatch, tmp_path):
    first, second = rollback_pair(manager)
    marker = first.parent.parent / "READY.json"
    outside = tmp_path / "external-ready.json"
    outside.write_bytes(marker.read_bytes())
    marker.unlink()
    try:
        marker.symlink_to(outside)
    except OSError:
        pytest.skip("This platform/user cannot create symbolic links")
    original = Path.open
    def prohibit_outside_read(self, *args, **kwargs):
        if self == outside or self == marker:
            pytest.fail("Setup must reject external READY links before opening them")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", prohibit_outside_read)
    restored = manager.setup(manager.source_python)
    assert restored not in {first, second}
    assert first.exists() and second.exists()


def test_cached_environment_directory_symlink_is_never_reused(manager, tmp_path):
    first, second = rollback_pair(manager)
    previous = first.parent.parent
    outside = tmp_path / "foreign-engine"
    # Move only this fixture-owned environment to construct a redirected cache.
    previous.rename(outside)
    try:
        previous.symlink_to(outside, target_is_directory=True)
    except OSError:
        outside.rename(previous)
        pytest.skip("This platform/user cannot create symbolic links")
    restored = manager.setup(manager.source_python)
    assert restored not in {first, second}
    assert (outside / "READY.json").exists()
    assert second.exists()


def test_requirements_change_during_reactivation_preserves_pointer(manager):
    first, second = rollback_pair(manager)
    previous_pointer = manager.active_path.read_bytes()
    def mutate_before_switch(percent, message):
        if percent == 95:
            (manager.package_root / "requirements.txt").write_text(pinned("tiny-package", "1.2"), encoding="utf-8")
    with pytest.raises(RuntimeSetupError, match="changed during engine reactivation"):
        manager.setup(manager.source_python, progress=mutate_before_switch)
    assert manager.active_path.read_bytes() == previous_pointer
    assert first.exists() and second.exists()
    assert sum("install" in call for call in manager.calls) == 2


def test_all_managed_python_commands_force_utf8_even_under_isolated_mode(manager):
    manager.setup(manager.source_python)
    manager.get_python()
    assert manager.calls
    for command in manager.calls:
        assert command[1:4] == ["-I", "-X", "utf8"]


@pytest.mark.skipif(os.name != "nt", reason="Windows atomic replacement sharing semantics")
def test_pointer_atomic_replace_retries_transient_denial_and_honors_cancellation(manager, monkeypatch):
    manager.cache_root.mkdir(parents=True)
    path = manager.active_path
    path.write_bytes(b"previous pointer")
    original = os.replace
    attempts = []
    def transient(source, target):
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError(errno.EACCES, "temporary sharing violation")
        return original(source, target)
    monkeypatch.setattr(os, "replace", transient)
    manager._write_json(path, {"complete": True})
    assert len(attempts) == 3
    assert json.loads(path.read_text()) == {"complete": True}
    before = path.read_bytes()
    token = CancellationToken()
    def cancel_during_retry(source, target):
        token.cancel()
        raise PermissionError(errno.EACCES, "temporary sharing violation")
    monkeypatch.setattr(os, "replace", cancel_during_retry)
    with pytest.raises(CancelledError):
        manager._write_json(path, {"cancelled": True}, token)
    assert path.read_bytes() == before
    assert not list(manager.cache_root.glob(".active.json-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows atomic replacement sharing semantics")
def test_permanent_pointer_denial_has_bounded_retry_and_preserves_completed_environments(manager, monkeypatch):
    first, second = rollback_pair(manager)
    pointer = manager.active_path.read_bytes()
    markers = {(python.parent.parent / "READY.json"): (python.parent.parent / "READY.json").read_bytes()
               for python in (first, second)}
    original = os.replace
    attempts = []
    def deny_pointer(source, target):
        if Path(target) == manager.active_path:
            attempts.append(target)
            raise PermissionError(errno.EACCES, "permanent access denial")
        return original(source, target)
    monkeypatch.setattr(os, "replace", deny_pointer)
    started = time.monotonic()
    with pytest.raises(PermissionError, match="permanent"):
        manager.setup(manager.source_python)
    assert time.monotonic() - started < 1
    assert len(attempts) == 6
    assert manager.active_path.read_bytes() == pointer
    assert all(path.read_bytes() == before for path, before in markers.items())
    assert len(list(manager.env_root.iterdir())) == 2
    assert not list(manager.cache_root.glob(".active.json-*.tmp"))
