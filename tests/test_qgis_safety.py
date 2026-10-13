"""Run production adapter methods with bounded Qt doubles; native QA is separate."""
import importlib
import errno
import json
import logging
import os
import subprocess
import sys
from enum import IntFlag
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


class Signal:
    def __init__(self, *args):
        self.calls = []
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        self.calls.append(args)
        for callback in self.callbacks:
            if isinstance(callback, Signal):
                callback.emit(*args)
            else:
                callback(*args)


class SignalDescriptor:
    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, Signal())


class QObject:
    def __init__(self, parent=None):
        self.parent = parent

    def deleteLater(self):
        self.deleted = True


class Thread(QObject):
    finished = SignalDescriptor()

    def start(self):
        self.started = True

    def requestInterruption(self):
        self.interrupted = True


class ProcessEnvironment:
    def __init__(self):
        self.values = {}

    def insert(self, key, value):
        self.values[key] = value


class Process(QObject):
    ExitStatus = SimpleNamespace(NormalExit=0, CrashExit=1)
    ProcessError = SimpleNamespace(FailedToStart=0)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.readyReadStandardOutput = Signal()
        self.readyReadStandardError = Signal()
        self.finished, self.errorOccurred = Signal(), Signal()
        self.started = Signal()
        self.killed = False
    def setWorkingDirectory(self, value):
        self.cwd = value
    def setProgram(self, value):
        self.program = value
    def setArguments(self, value):
        self.arguments = value
    def setProcessEnvironment(self, value):
        self.environment = value
    def start(self):
        self.was_started = True
        self.started.emit()
    def processId(self):
        return 424242
    def readAllStandardOutput(self):
        return b""
    def readAllStandardError(self):
        return b""
    def kill(self):
        self.killed = True
    def errorString(self):
        return "The managed engine executable could not be started"


class Flag(IntFlag):
    ItemIsEditable = 2


class Item:
    def __init__(self, text):
        self.value, self.meta, self._flags = text, {}, Flag.ItemIsEditable

    def text(self):
        return self.value

    def setData(self, role, value):
        self.meta[role] = value

    def data(self, role):
        return self.meta[role]

    def flags(self):
        return self._flags

    def setFlags(self, flags):
        self._flags = flags

    def setTextAlignment(self, alignment):
        pass


class Button:
    def __init__(self, text):
        self.clicked = Signal()

    def setToolTip(self, text):
        pass


class ExitGuard:
    def __init__(self):
        self.reaped, self.error, self.closed = True, False, False
        self.pid = None
    def begin(self, pid):
        self.pid = pid
    def exited(self):
        if self.error:
            raise RuntimeError("indeterminate process exit")
        return self.reaped
    def close(self):
        self.closed = True


@pytest.fixture
def adapter(monkeypatch):
    # Loading a package under an alias avoids executing plugin classFactory.
    alias = "qgis_adapter_under_test"
    package = ModuleType(alias)
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, alias, package)
    guards = ModuleType(alias + ".q_models.process_exit_guard")
    guards.ProcessExitGuard = ExitGuard
    monkeypatch.setitem(sys.modules, guards.__name__, guards)
    qtcore = ModuleType("qgis.PyQt.QtCore")
    qtcore.QObject, qtcore.QThread = QObject, Thread
    qtcore.QProcess, qtcore.QProcessEnvironment = Process, ProcessEnvironment
    qtcore.QTimer = SimpleNamespace(singleShot=lambda *args: None)
    qtcore.pyqtSignal = lambda *args: SignalDescriptor()
    qtcore.QSignalBlocker = lambda widget: object()
    qtcore.Qt = SimpleNamespace(ItemDataRole=SimpleNamespace(UserRole=256), ItemFlag=Flag,
                               AlignmentFlag=SimpleNamespace(AlignRight=1, AlignVCenter=2),
                               Key=SimpleNamespace(Key_Delete=16777223))
    qtwidgets = ModuleType("qgis.PyQt.QtWidgets")
    qtwidgets.QTableWidgetItem, qtwidgets.QTableWidget = Item, object
    qtwidgets.QPushButton = Button
    qtwidgets.QHeaderView = SimpleNamespace(ResizeMode=SimpleNamespace(ResizeToContents=1, Stretch=2))
    pyqt = ModuleType("qgis.PyQt")
    pyqt.QtCore, pyqt.QtWidgets = qtcore, qtwidgets
    for key, value in {"qgis": ModuleType("qgis"), "qgis.PyQt": pyqt,
                       "qgis.PyQt.QtCore": qtcore, "qgis.PyQt.QtWidgets": qtwidgets}.items():
        monkeypatch.setitem(sys.modules, key, value)
    modules_before = set(sys.modules)

    def load(name):
        return importlib.import_module(f"{alias}.q_models.{name}")

    yield load
    # Imported alias submodules must not contaminate tests using real core/QGIS.
    for key in set(sys.modules) - modules_before:
        if key.startswith(alias + "."):
            sys.modules.pop(key, None)


def test_open_existing_project_preserves_config_and_logs(adapter, tmp_path):
    module = adapter("config_manager")
    manager = module.ConfigManager(logging.getLogger("test"))
    manager.create_initial_config(tmp_path)
    log = tmp_path / "output" / "logs_pypoprf.log"
    log.parent.mkdir()
    log.write_text("previous diagnosis")
    config = (tmp_path / "config.yaml").read_bytes()
    with pytest.raises(module.ConfigError, match="already exists"):
        manager.create_initial_config(tmp_path)
    manager.open_project(tmp_path)
    assert (tmp_path / "config.yaml").read_bytes() == config
    assert log.read_text() == "previous diagnosis"


def test_atomic_config_failure_preserves_previous_bytes(adapter, tmp_path, monkeypatch):
    module = adapter("config_manager")
    manager = module.ConfigManager(logging.getLogger("test"))
    manager.create_initial_config(tmp_path)
    before = Path(manager.config_path).read_bytes()
    monkeypatch.setattr(module.yaml, "safe_dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        manager.update_config("max_workers", 3)
    assert Path(manager.config_path).read_bytes() == before
    assert not list(tmp_path.glob(".config-*.tmp"))


def test_failed_project_create_publishes_no_partial_config(adapter, tmp_path, monkeypatch):
    module = adapter("config_manager")
    manager = module.ConfigManager(logging.getLogger("test"))
    def partial_dump(config, stream, **kwargs):
        stream.write("broken:")
        raise OSError("disk full")
    monkeypatch.setattr(module.yaml, "safe_dump", partial_dump)
    with pytest.raises(OSError, match="disk full"):
        manager.create_initial_config(tmp_path / "new")
    assert not (tmp_path / "new" / "config.yaml").exists()
    assert manager.config_path is None
    assert not list((tmp_path / "new").iterdir())


def test_config_mutations_refuse_concurrent_session_lock_without_lost_update(adapter, tmp_path):
    module = adapter("config_manager")
    first = module.ConfigManager(logging.getLogger("test"))
    second = module.ConfigManager(logging.getLogger("test"))
    first.create_initial_config(tmp_path)
    second.open_project(tmp_path)
    first.update_config("max_workers", 3)
    before = Path(first.config_path).read_bytes()
    with first._mutation_lock():
        with pytest.raises(module.ConfigError, match="Another session"):
            second.update_config("log_scale", False)
    assert Path(first.config_path).read_bytes() == before
    second.update_config("log_scale", False)
    assert first.get_config()["max_workers"] == 3
    assert first.get_config()["log_scale"] is False


@pytest.mark.parametrize("name", ["../config.yaml", "../a.log", "a/b.log", "a\\b.log",
                                  "C:a.log", "config.yaml", "", " x.log", "a\n.log", "CON.log"])
def test_log_filename_rejects_unsafe_paths(adapter, name):
    module = adapter("config_manager")
    with pytest.raises(module.ConfigError):
        module.validate_log_filename(name)


def test_import_existing_and_same_file_are_safe(adapter, tmp_path):
    module = adapter("file_handlers")
    handler = module.FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    handler.set_working_dir(handler.working_dir)
    source = tmp_path / "zones.tif"
    source.write_bytes(b"original")
    assert handler.copy_to_data_dir(str(source), "mastergrid") == "zones.tif"
    target = Path(handler.working_dir) / "data" / "zones.tif"
    Path(str(target) + ".msk").write_bytes(b"canonical sidecar remains in place")
    assert handler.copy_to_data_dir(str(target), "mastergrid") == "zones.tif"
    source.write_bytes(b"new-input")
    with pytest.raises(module.FileHandlerError, match="overwrite"):
        handler.copy_to_data_dir(str(source), "mastergrid")
    assert target.read_bytes() == b"original"


def test_external_same_inode_with_different_sidecar_is_not_canonical_reuse(adapter, tmp_path):
    files = adapter("file_handlers")
    configs = adapter("config_manager")
    project = tmp_path / "project"
    manager = configs.ConfigManager(logging.getLogger("test"))
    manager.create_initial_config(project)
    target = project / "data" / "zones.tif"
    target.write_bytes(b"canonical raster bytes")
    manager.update_config("mastergrid", target.name)
    before_config = Path(manager.config_path).read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = outside / target.name
    os.link(target, alias)
    sidecar = Path(str(alias) + ".msk")
    sidecar.write_bytes(b"different outside validity mask")
    assert alias.samefile(target) and alias.parent.resolve() != target.parent.resolve()
    handler = files.FileHandler(str(project), logging.getLogger("test"))
    with pytest.raises(files.FileHandlerError, match="overwrite"):
        handler.copy_to_data_dir(str(alias), "mastergrid")
    assert target.read_bytes() == b"canonical raster bytes"
    assert sidecar.read_bytes() == b"different outside validity mask"
    assert not Path(str(target) + ".msk").exists()
    assert Path(manager.config_path).read_bytes() == before_config
    assert manager.get_config()["mastergrid"] == target.name


@pytest.mark.parametrize("suffix", [".msk", ".aux.xml"])
def test_sidecar_appearing_during_copy_refuses_publish_without_partial_input(adapter, tmp_path, suffix):
    module = adapter("file_handlers")
    source = tmp_path / "source.tif"
    original = b"complete source raster" * 100000
    source.write_bytes(original)
    before_stat = source.stat()
    sidecar = Path(str(source) + suffix)
    handler = module.FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    def create_sidecar(percent, name):
        sidecar.write_bytes(b"new external GDAL resource")
    with pytest.raises(module.FileHandlerError, match="external mask or metadata"):
        handler.copy_to_data_dir(str(source), "mastergrid", progress=create_sidecar)
    assert source.read_bytes() == original
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (before_stat.st_size, before_stat.st_mtime_ns)
    assert sidecar.read_bytes() == b"new external GDAL resource"
    assert not list((tmp_path / "project" / "data").iterdir())


def test_failed_import_does_not_publish_partial_input(adapter, tmp_path, monkeypatch):
    module = adapter("file_handlers")
    handler = module.FileHandler(str(tmp_path), logging.getLogger("test"))
    source = tmp_path / "source.tif"
    source.write_bytes(b"complete-input")

    def partial_copy(source, target):
        Path(target).write_bytes(b"incomplete")
        raise OSError("disk full")

    monkeypatch.setattr(module.shutil, "copy2", partial_copy)
    with pytest.raises(module.FileHandlerError, match="disk full"):
        handler.copy_to_data_dir(str(source), "mastergrid")
    assert not list((tmp_path / "data").iterdir())
    assert source.read_bytes() == b"complete-input"


@pytest.mark.parametrize("bad", [{"block_size": [512]}, {"census_pop_column": None},
                                  {"max_workers": False}, {"by_block": "false"}])
def test_open_malformed_settings_leaves_active_project_unchanged(adapter, tmp_path, bad):
    module = adapter("config_manager")
    manager = module.ConfigManager(logging.getLogger("test"))
    active = tmp_path / "active"
    manager.create_initial_config(active)
    other = tmp_path / "other"
    other.mkdir()
    config = dict(module.DEFAULT_CONFIG, **bad)
    (other / "config.yaml").write_text(module.yaml.safe_dump(config))
    with pytest.raises(module.ConfigError):
        manager.open_project(other)
    assert manager.working_dir == str(active.resolve())


class Table:
    def __init__(self):
        self.rows = []

    def rowCount(self):
        return len(self.rows)

    def insertRow(self, index):
        self.rows.insert(index, {})

    def setItem(self, row, column, item):
        self.rows[row][column] = item

    def item(self, row, column):
        return self.rows[row][column]

    def setCellWidget(self, row, column, widget):
        self.rows[row][column] = widget

    def removeRow(self, row):
        self.rows.pop(row)


def test_delete_button_resolves_stable_key_after_shift(adapter, tmp_path):
    module = adapter("covariate_table")
    table = Table()
    removed = []
    config = SimpleNamespace(clear_config_value=removed.append, update_config=lambda *a: None)
    handler = module.CovariateTableHandler.__new__(module.CovariateTableHandler)
    handler.table, handler.config_manager, handler.logger = table, config, logging.getLogger("test")
    for name in ["a", "b", "c"]:
        handler._add_covariate_row(f"{name}.tif", tmp_path)
    button_c = table.rows[2][3]
    assert not table.item(0, 0).flags() & Flag.ItemIsEditable
    handler.remove_covariate(0)
    button_c.clicked.emit(False)
    assert removed == ["covariate_a", "covariate_c"]
    assert table.item(0, 0).text() == "b"


def controller_for(adapter, tmp_path):
    module = adapter("process_executor")
    config_module = adapter("config_manager")
    project = tmp_path / "project"
    manager = config_module.ConfigManager(logging.getLogger("test"))
    manager.create_initial_config(project)
    dialog = SimpleNamespace(
        is_busy=False,
        config_manager=manager,
        settings_handler=SimpleNamespace(validate_settings=lambda d: True, collect_settings=lambda d: {}),
        runtime_controller=SimpleNamespace(python=str(tmp_path / "python"),
            manager=SimpleNamespace(child_environment=lambda p: {"PATH": "isolated"})),
        job_cache=tmp_path / "cache", plugin_root=ROOT,
        console_handler=SimpleNamespace(clear=lambda: None),
        mainProgressBar=SimpleNamespace(setValue=lambda x: None, setFormat=lambda x: None),
        mainStartButton=SimpleNamespace(setEnabled=lambda x: None, setText=lambda x: None),
        addToQgisCheckBox=SimpleNamespace(isChecked=lambda: False),
        refresh_results=lambda: None)
    controller = module.ProcessExecutor(dialog, logging.getLogger("test"))
    controller._set_ui_enabled = lambda enabled: None
    return module, controller


def complete_run(controller):
    root = controller._expected_run
    root.mkdir(parents=True)
    (root / "prediction.tif").write_bytes(b"weights")
    (root / "population.tif").write_bytes(b"population")
    manifest = {"status": "complete", "config": str(controller._config_file),
                "outputs": ["prediction.tif", "population.tif"]}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return {"event": "result", "status": "complete", "run_dir": str(root),
            "outputs": manifest["outputs"]}


def test_qprocess_start_has_no_numerical_preflight_or_project_mutation(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    before = Path(controller.dialog.config_manager.config_path).read_bytes()
    controller.start_analysis()
    assert controller.is_running
    process = controller.process
    assert process.program.endswith("python")
    assert process.environment.values == {"PATH": "isolated"}
    assert process.cwd == str(ROOT)
    assert process.arguments[:4] == ["-X", "utf8", "-m", "core.pypoprf"]
    assert not controller._expected_run.exists()
    assert Path(controller.dialog.config_manager.config_path).read_bytes() == before
    controller._finished(1, Process.ExitStatus.NormalExit)


def test_success_requires_exit_event_manifest_and_native_finished(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    event = complete_run(controller)
    payload = json.dumps(event).encode() + b"\n"
    controller._consume_stdout(payload[:7])
    controller._consume_stdout(payload[7:])
    assert controller.is_running and not controller.last_result_paths
    process = controller.process
    controller._finished(0, Process.ExitStatus.NormalExit)
    assert not controller.is_running
    assert controller.last_result_paths == [controller.last_run_dir / "population.tif"]
    assert process.deleted
    assert not list(controller.dialog.job_cache.iterdir())


def test_interface_refresh_failure_cannot_suppress_terminal_signal(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    event = complete_run(controller)
    controller._consume_stdout(json.dumps(event).encode() + b"\n")
    controller.dialog.refresh_results = lambda: (_ for _ in ()).throw(FileNotFoundError("config was removed"))
    finished = []
    controller.completed.connect(lambda: finished.append(True))
    controller._finished(0, Process.ExitStatus.NormalExit)
    assert not controller.is_running and finished == [True]
    assert controller.last_result_paths


@pytest.mark.parametrize("fault", ["nonzero", "missing_event", "missing_file", "escaped_path"])
def test_incomplete_or_inconsistent_outputs_never_become_success(adapter, tmp_path, fault):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    event = complete_run(controller)
    if fault == "missing_file":
        (controller._expected_run / "population.tif").unlink()
    if fault == "escaped_path":
        event["outputs"] = ["../outside.tif"]
        (controller._expected_run / "manifest.json").write_text(json.dumps(
            {"status": "complete", "outputs": event["outputs"]}))
    if fault != "missing_event":
        controller._consume_stdout(json.dumps(event).encode() + b"\n")
    controller._finished(1 if fault == "nonzero" else 0, Process.ExitStatus.NormalExit)
    assert not controller.last_result_paths
    assert not controller.is_running


def test_cancel_marker_never_waits_and_never_kills_later_job(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    first = controller.process
    controller.stop_analysis()
    assert controller._cancel_file.is_file()
    assert controller.process is first
    assert not first.killed
    controller._finished(2, Process.ExitStatus.NormalExit)
    controller.start_analysis()
    second = controller.process
    controller._force_stop(first)
    assert controller.process is second and not second.killed
    first.finished.emit(0, Process.ExitStatus.NormalExit)
    first.errorOccurred.emit(Process.ProcessError.FailedToStart)
    first.readyReadStandardOutput.emit()
    first.readyReadStandardError.emit()
    assert controller.process is second
    controller._finished(1, Process.ExitStatus.NormalExit)


@pytest.mark.parametrize("manifest", [[], None, {"status": None}, {"status": []},
                                      {"status": "complete", "outputs": "map.tif"}])
def test_manifest_loader_rejects_corrupt_json_types(adapter, tmp_path, manifest):
    module = adapter("result_manifest")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.read_manifest(path)


@pytest.mark.parametrize("suffix", [".msk", ".aux.xml"])
def test_import_sidecar_raster_is_refused_without_losing_validity(adapter, tmp_path, suffix):
    module = adapter("file_handlers")
    source = tmp_path / "source.tif"
    source.write_bytes(b"raster")
    Path(str(source) + suffix).write_bytes(b"mask or georeferencing")
    handler = module.FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    handler.set_working_dir(handler.working_dir)
    with pytest.raises(module.FileHandlerError, match="external mask or metadata"):
        handler.copy_to_data_dir(str(source), "mastergrid")
    assert not list((Path(handler.working_dir) / "data").iterdir())


def test_cancel_even_after_engine_result_does_not_publish_complete(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    event = complete_run(controller)
    controller._consume_stdout(json.dumps(event).encode() + b"\n")
    controller.stop_analysis()
    controller._finished(0, Process.ExitStatus.NormalExit)
    assert not controller.last_result_paths
    manifest = json.loads((controller.last_run_dir / "manifest.json").read_text())
    assert manifest["status"] == "cancelled"


def test_stdout_chunk_parser_bounds_malformed_events(adapter, tmp_path):
    module, controller = controller_for(adapter, tmp_path)
    controller._consume_stdout(b"X" * (module.ProcessExecutor.MAX_EVENT + 1))
    assert len(controller._stdout) <= module.ProcessExecutor.MAX_EVENT
    controller._consume_stdout(b"not json\n")
    controller._consume_stdout(b'{"event":"progress","percent":999,"message":"bad"}\n')
    assert controller._result is None


@pytest.mark.parametrize("contents", ["[]", "null", "broken json"])
def test_malformed_final_manifest_never_retains_process_ownership(adapter, tmp_path, contents):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    event = complete_run(controller)
    path = controller._expected_run / "manifest.json"
    path.write_text(contents)
    controller._consume_stdout(json.dumps(event).encode() + b"\n")
    controller._finished(0, Process.ExitStatus.NormalExit)
    assert not controller.is_running
    assert not controller.last_result_paths
    assert json.loads(path.read_text())["status"] == "failed"


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("event_present", [False, True])
def test_existing_run_collision_preserves_every_previous_byte(
        adapter, tmp_path, monkeypatch, cancelled, event_present):
    module, controller = controller_for(adapter, tmp_path)
    monkeypatch.setattr(module, "datetime", SimpleNamespace(
        now=lambda *args: SimpleNamespace(strftime=lambda pattern: "previous")))
    monkeypatch.setattr(module, "uuid4", lambda: SimpleNamespace(hex="12345678"))
    root = tmp_path / "project" / "output" / "runs" / "previous-12345678"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"status": "complete",
        "config": "previous/snapshot.yaml", "outputs": ["population.tif"]}))
    (root / "population.tif").write_bytes(b"previous validated result\x00\xff")
    scratch = root / "grids-previous"
    scratch.mkdir()
    (scratch / "preserve.tif").write_bytes(b"previous source bytes")
    before = {str(path.relative_to(root)): path.read_bytes()
              for path in root.rglob("*") if path.is_file()}
    controller.start_analysis()
    assert controller._expected_run == root
    if event_present:
        controller._consume_stdout(json.dumps({"event": "result", "status": "failed",
            "run_dir": None, "message": "Output directory already exists"}).encode() + b"\n")
    if cancelled:
        controller.stop_analysis()
    controller._finished(1, Process.ExitStatus.NormalExit)
    assert not controller.is_running and not controller.last_result_paths
    after = {str(path.relative_to(root)): path.read_bytes()
             for path in root.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("proof", ["config", "event"])
def test_forced_owned_run_cleans_only_its_scratch_after_child_ended(adapter, tmp_path, proof):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    root = controller._expected_run
    root.mkdir(parents=True)
    manifest = {"status": "running", "outputs": []}
    if proof == "config":
        manifest["config"] = str(controller._config_file)
    else:
        controller._consume_stdout(json.dumps({"event": "result", "status": "cancelled",
            "run_dir": str(root)}).encode() + b"\n")
    (root / "manifest.json").write_text(json.dumps(manifest))
    scratch = root / "grids-owned"
    scratch.mkdir()
    (scratch / "masked.tif").write_bytes(b"temporary grid")
    (root / "population.tif").write_bytes(b"permanent artifact")
    unrelated = root / "keep-this"
    unrelated.mkdir()
    (unrelated / "input.bin").write_bytes(b"permanent input")
    controller.stop_analysis()
    controller._force_stop(controller.process)
    assert controller.process.killed and scratch.is_dir()
    controller._finished(-1, Process.ExitStatus.CrashExit)
    assert not controller.is_running and not scratch.exists()
    assert (root / "population.tif").read_bytes() == b"permanent artifact"
    assert (unrelated / "input.bin").read_bytes() == b"permanent input"
    assert json.loads((root / "manifest.json").read_text())["status"] == "cancelled"


@pytest.mark.parametrize("contents", ["[]", "no manifest"])
def test_unknown_forced_run_is_not_claimed_or_cleaned(adapter, tmp_path, contents):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    root = controller._expected_run
    root.mkdir(parents=True)
    if contents == "[]":
        (root / "manifest.json").write_text(contents)
    scratch = root / "grids-unknown"
    scratch.mkdir()
    (scratch / "source.tif").write_bytes(b"unknown ownership")
    controller.stop_analysis()
    controller._finished(-1, Process.ExitStatus.CrashExit)
    assert not controller.is_running
    assert (scratch / "source.tif").read_bytes() == b"unknown ownership"
    path = root / "manifest.json"
    assert path.read_text() == "[]" if contents == "[]" else not path.exists()


@pytest.mark.parametrize("target_kind", ["config", "terminal"])
@pytest.mark.parametrize("permanent", [False, True])
def test_gui_atomic_publication_retries_sharing_and_preserves_old_on_permanent_error(
        adapter, tmp_path, monkeypatch, target_kind, permanent):
    module, controller = controller_for(adapter, tmp_path)
    manager = controller.dialog.config_manager
    if target_kind == "terminal":
        controller.start_analysis()
        complete_run(controller)
        path = controller._expected_run / "manifest.json"
    else:
        path = Path(manager.config_path)
    before = path.read_bytes()
    helper = importlib.import_module(module.__package__.rsplit(".", 1)[0] + ".atomic_files")
    original, attempts = os.replace, []
    def sharing(source, target):
        attempts.append(source)
        assert path.read_bytes() == before
        if permanent or len(attempts) < 3:
            raise PermissionError(errno.EACCES, "temporary Windows reader sharing")
        original(source, target)
    monkeypatch.setattr(helper, "_IS_WINDOWS", True)
    monkeypatch.setattr(helper.time, "sleep", lambda delay: None)
    monkeypatch.setattr(os, "replace", sharing)
    if target_kind == "config":
        if permanent:
            with pytest.raises(PermissionError):
                manager.update_config("max_workers", 3)
        else:
            manager.update_config("max_workers", 3)
            assert manager.get_config()["max_workers"] == 3
    else:
        controller.stop_analysis()
        controller._finished(-1, Process.ExitStatus.CrashExit)
        assert not controller.is_running
        if not permanent:
            assert json.loads(path.read_text())["status"] == "cancelled"
    assert len(attempts) == (6 if permanent else 3)
    if permanent:
        assert path.read_bytes() == before
    assert not list(path.parent.glob(".gui-terminal-*.tmp"))
    assert not list(path.parent.glob(".config-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Real Windows junctions require Windows")
@pytest.mark.parametrize("redirect", ["run", "ancestor", "scratch", "nested"])
def test_windows_junction_redirect_never_modifies_outside_data(adapter, tmp_path, redirect):
    module, controller = controller_for(adapter, tmp_path)
    controller.start_analysis()
    root = controller._expected_run
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_manifest = outside / "manifest.json"
    outside_manifest.write_text(json.dumps({"status": "complete", "config": str(controller._config_file),
                                          "outputs": ["population.tif"]}))
    (outside / "population.tif").write_bytes(b"outside trusted map")
    outside_scratch = outside / "grids-preserve"
    outside_scratch.mkdir()
    (outside_scratch / "source.tif").write_bytes(b"outside source bytes")
    before = {str(p.relative_to(outside)): p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    if redirect == "run":
        root.parent.mkdir(parents=True)
        link, target = root, outside
    elif redirect == "ancestor":
        root.parent.parent.mkdir(parents=True)
        target = tmp_path / "outside-runs"
        target.mkdir()
        child = target / root.name
        child.mkdir()
        (child / "manifest.json").write_bytes(outside_manifest.read_bytes())
        (child / "population.tif").write_bytes(b"outside child map")
        link = root.parent
    else:
        root.mkdir(parents=True)
        (root / "manifest.json").write_text(json.dumps({"status": "running", "outputs": [],
                                                       "config": str(controller._config_file)}))
        link, target = root / "grids-link", outside
        if redirect == "nested":
            link.mkdir()
            link = link / "nested-junction"
    assert link.absolute().is_relative_to(tmp_path.resolve())
    assert target.resolve().is_relative_to(tmp_path.resolve())
    subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                   text=True, capture_output=True, check=True)
    try:
        assert link.is_junction() and not link.is_symlink()
        controller._consume_stdout(json.dumps({"event": "result", "status": "complete",
            "run_dir": str(root), "outputs": ["population.tif"]}).encode() + b"\n")
        if redirect in {"run", "ancestor"}:
            controller._finished(0, Process.ExitStatus.NormalExit)
            assert not controller.last_result_paths
        else:
            controller.stop_analysis()
            controller._finished(-1, Process.ExitStatus.CrashExit)
            assert link.is_junction()
        assert not controller.is_running
        after = {str(p.relative_to(outside)): p.read_bytes() for p in outside.rglob("*") if p.is_file()}
        assert after == before
        if redirect == "ancestor":
            assert (child / "manifest.json").read_bytes() == before["manifest.json"]
            assert (child / "population.tif").read_bytes() == b"outside child map"
    finally:
        # Remove only this exact junction, not its target, before pytest cleanup.
        assert link.is_junction() and link.resolve() == target.resolve()
        link.rmdir()


@pytest.mark.parametrize("parallel,expected", [(False, 1), (True, 4)])
@pytest.mark.parametrize("by_block", [False, True])
def test_settings_collect_roundtrips_flags_and_log_name(adapter, parallel, expected, by_block):
    module = adapter("settings_handler")
    text = lambda value: SimpleNamespace(text=lambda: value, currentText=lambda: value)
    checked = lambda value: SimpleNamespace(isChecked=lambda: value)
    dialog = SimpleNamespace(logsColumnEdit=text("custom.log"), comboBox=text("DEBUG"),
        blockSizeComboBox=text("256,512"), cpuCoresComboBox=text("4"),
        enableParallelCheckBox=checked(parallel), enableBlockProcessingCheckBox=checked(by_block),
        popColumnEdit=text("people"), idColumnEdit=text("zone"), logScaleCheckBox=checked(False),
        selectionThresholdLimit=SimpleNamespace(value=lambda: 0.03))
    handler = module.SettingsHandler(None, logging.getLogger("test"))
    saved = handler.collect_settings(dialog)
    assert saved["logging"] == {"level": "DEBUG", "file": "custom.log"}
    assert saved["max_workers"] == expected
    assert saved["by_block"] is by_block
    assert saved["block_size"] == [256, 512]


def test_chunked_import_cancellation_publishes_nothing(adapter, tmp_path):
    module = adapter("file_handlers")
    runtime = adapter("runtime_controller")
    token = runtime.SetupToken()
    source = tmp_path / "large.tif"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    handler = module.FileHandler(str(tmp_path), logging.getLogger("test"))
    def cancel(percent, name):
        token.cancel()
    with pytest.raises(module.FileHandlerError, match="cancelled"):
        handler.copy_to_data_dir(str(source), "covariate", cancellation_token=token, progress=cancel)
    assert not list((tmp_path / "data").iterdir())


def test_runtime_controller_does_health_checks_only_on_owned_worker(adapter):
    module = adapter("runtime_controller")
    calls = []
    manager = SimpleNamespace(
        get_python=lambda cancellation_token=None: calls.append("health") or Path("isolated-python"),
        detect_python_candidates=lambda cancellation_token=None: [])
    controller = module.RuntimeController(manager)
    controller.check()
    assert calls == [] and controller.is_running
    controller.check()
    worker = controller.worker
    worker.run()
    worker.finished.emit()
    assert calls == ["health"]
    assert controller.python == "isolated-python"
    assert not controller.is_running


def tools_for(adapter, tmp_path):
    _, analysis = controller_for(adapter, tmp_path)
    module = adapter("tools_controller")
    return module, module.ToolsController(analysis.dialog, logging.getLogger("test"))


def publish_tool_result(controller, ready=True):
    root = controller._output
    root.mkdir(parents=True)
    report = {"schema_version": 1, "status": "complete", "operation": controller._operation,
              "request_id": controller._request_id, "ready": ready, "errors": [], "warnings": []}
    event = {"event": "result", "status": "complete", "output_dir": str(root),
             "request_id": controller._request_id, "report_path": str(root / "report.json")}
    if controller._operation == "prepare":
        config = root / "config.yaml"
        config.write_text("validated: true")
        report["config_path"] = event["config_path"] = str(config)
    (root / "report.json").write_text(json.dumps(report))
    return report, event


@pytest.mark.parametrize("ready", [True, False])
def test_tools_inspection_transfers_verified_report_before_owned_cache_cleanup(adapter, tmp_path, ready):
    module, tools = tools_for(adapter, tmp_path)
    received, completed = [], []
    tools.resultReady.connect(received.append)
    tools.completed.connect(lambda: completed.append(not tools.is_running))
    assert tools.start({"operation": "inspect"})
    owned = tools.process
    request = json.loads(Path(owned.arguments[5]).read_text())
    assert request["request_id"] == tools._request_id and len(tools._request_id) == 32
    assert owned.environment.values == {"PATH": "isolated"}
    report, event = publish_tool_result(tools, ready)
    report_path = tools._output / "report.json"
    data = json.dumps(event).encode() + b"\n"
    tools._consume(data[:7])
    tools._consume(data[7:])
    assert tools.is_running and not received
    tools._finished(0, Process.ExitStatus.NormalExit, owned)
    assert received[0]["success"] and received[0]["report"] == report
    assert completed == [True] and owned.deleted
    assert not report_path.exists()


@pytest.mark.parametrize("fault", ["event_nonce", "report_nonce", "operation", "malformed", "outside",
                                  "unexpected_name", "nonzero", "missing_event", "inconsistent_config", "not_ready", "nonfinite"])
def test_tool_result_rejects_wrong_owner_or_unvalidated_prepared_project(adapter, tmp_path, fault):
    module, tools = tools_for(adapter, tmp_path)
    results = []
    tools.resultReady.connect(results.append)
    assert tools.start({"operation": "prepare", "output_dir": str(tmp_path / "prepared")})
    report, event = publish_tool_result(tools)
    path = tools._output / "report.json"
    if fault == "event_nonce":
        event["request_id"] = "0" * 32
    elif fault == "report_nonce":
        report["request_id"] = "0" * 32
    elif fault == "operation":
        report["operation"] = "inspect"
    elif fault == "malformed":
        report = []
    elif fault == "outside":
        outside = tmp_path / "report.json"
        outside.write_text(json.dumps(report))
        event["report_path"] = str(outside)
    elif fault == "unexpected_name":
        other = tools._output / "other.json"
        other.write_text(json.dumps(report))
        event["report_path"] = str(other)
    elif fault == "inconsistent_config":
        report["config_path"] = "different/config.yaml"
    elif fault == "not_ready":
        report["ready"] = False
    elif fault == "nonfinite":
        report["value"] = float("nan")
    path.write_text(json.dumps(report))
    if fault != "missing_event":
        tools._consume(json.dumps(event).encode() + b"\n")
    tools._finished(1 if fault == "nonzero" else 0, Process.ExitStatus.NormalExit, tools.process)
    assert not tools.is_running and not results[0]["success"]
    assert (tmp_path / "prepared" / "config.yaml").read_text() == "validated: true"


def test_tools_cancel_and_stale_callbacks_never_finish_or_kill_a_later_job(adapter, tmp_path):
    module, tools = tools_for(adapter, tmp_path)
    results = []
    tools.resultReady.connect(results.append)
    assert tools.start({"operation": "inspect"})
    first = tools.process
    _, event = publish_tool_result(tools)
    tools._consume(json.dumps(event).encode() + b"\n")
    tools.stop()
    assert tools._marker.is_file() and not first.killed
    tools._finished(0, Process.ExitStatus.NormalExit, first)
    assert results[0]["cancelled"] and not results[0]["success"]
    assert tools.start({"operation": "inspect"})
    second = tools.process
    first.finished.emit(0, Process.ExitStatus.NormalExit)
    first.errorOccurred.emit(Process.ProcessError.FailedToStart)
    first.readyReadStandardOutput.emit()
    first.readyReadStandardError.emit()
    tools._force_stop(first)
    assert tools.process is second and not second.killed
    tools._finished(1, Process.ExitStatus.NormalExit, second)


def test_tools_failed_start_and_existing_output_refusal_always_publish_completion(adapter, tmp_path):
    module, tools = tools_for(adapter, tmp_path)
    results, completions = [], []
    tools.resultReady.connect(results.append)
    tools.completed.connect(lambda: completions.append(not tools.is_running))
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "source.txt").write_bytes(b"preserve existing source")
    assert not tools.start({"operation": "prepare", "output_dir": str(existing)})
    assert (existing / "source.txt").read_bytes() == b"preserve existing source"
    assert results[-1]["success"] is False and completions == [True]
    assert tools.start({"operation": "inspect"})
    tools.process.errorOccurred.emit(Process.ProcessError.FailedToStart)
    assert not tools.is_running and completions == [True, True]
    assert not results[-1]["success"]


@pytest.mark.parametrize("bad", [
    {"selected_cells": True}, {"valid_cells": -1}, {"valid_cells": 3},
    {"sum_persons": float("inf")}, {"sum_persons": -1}, {"sum_persons": True},
    {"coverage_fraction": float("nan")}, {"coverage_fraction": 1.5}, {"coverage_fraction": 0.2},
    {"complete_coverage": "true"}, {"complete_coverage": True}, {"aoi_extends_outside_raster": 1},
    {"display_persons": 6}, {"display_persons": True}, {"units": "density"}, {"inclusion": "all_touched"},
    {"valid_cells": 0, "coverage_fraction": 0}, {"sum_persons": 10 ** 1000},
])
def test_population_summary_rejects_malformed_or_false_coverage_declarations(adapter, bad):
    module = adapter("tools_controller")
    summary = {"selected_cells": 2, "valid_cells": 1, "sum_persons": 4.6,
        "display_persons": 5, "coverage_fraction": 0.5, "complete_coverage": False,
        "aoi_extends_outside_raster": False, "units": "persons_per_pixel", "inclusion": "cell_center"}
    summary.update(bad)
    with pytest.raises(ValueError):
        module.validate_population_summary(summary)


def test_population_summary_zero_selected_is_not_evidence_of_complete_zero_population(adapter):
    module = adapter("tools_controller")
    summary = {"selected_cells": 0, "valid_cells": 0, "sum_persons": 0, "display_persons": 0,
        "coverage_fraction": None, "complete_coverage": False, "aoi_extends_outside_raster": True,
        "units": "persons_per_pixel", "inclusion": "cell_center"}
    assert module.validate_population_summary(summary) == summary


@pytest.mark.parametrize("kind", ["analysis", "tools"])
@pytest.mark.parametrize("query_error", [False, True])
def test_native_qt_finished_keeps_owner_and_files_until_actual_engine_exit_is_verified(
        adapter, tmp_path, kind, query_error):
    if kind == "analysis":
        module, controller = controller_for(adapter, tmp_path)
        controller.start_analysis()
        complete_run(controller)
        controller.stop_analysis()
    else:
        module, controller = tools_for(adapter, tmp_path)
        assert controller.start({"operation": "inspect"})
        publish_tool_result(controller)
        controller.stop()
    guard, owned = controller._exit_guard, controller.process
    assert guard.pid == owned.processId()
    marker = controller._cancel_file if kind == "analysis" else controller._marker
    job = Path(controller._job.name)
    before = {str(path.relative_to(job)): path.read_bytes() for path in job.rglob("*") if path.is_file()}
    completed = []
    controller.completed.connect(lambda: completed.append(True))
    guard.reaped, guard.error = False, query_error
    controller._finished(-1, Process.ExitStatus.CrashExit, owned)
    assert controller.is_running and controller.process is owned
    assert marker.is_file() and not guard.closed and not completed
    assert {str(path.relative_to(job)): path.read_bytes() for path in job.rglob("*") if path.is_file()} == before
    guard.reaped, guard.error = True, False
    controller._finished(-1, Process.ExitStatus.CrashExit, owned)
    assert not controller.is_running and completed == [True]
    assert guard.closed and not job.exists()
