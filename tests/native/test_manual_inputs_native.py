"""Genuine keyboard file edits: draft/commit and inactive-project boundaries."""
from pathlib import Path
import importlib
import threading
import time

import pytest

pytest.importorskip("qgis.core", reason="Manual input editing requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QToolButton
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              initialize, wait_until)

ROLES = ("mastergrid", "mask", "constrain", "census_data", "agesex_data")


def source_for(tmp_path, role, suffix=""):
    source = tmp_path / (role + suffix + (".csv" if role.endswith("data") else ".tif"))
    # Import validates CSV shape and file transactions without numerical parsing.
    # Numerical raster validity belongs to the separate engine preflight.
    source.write_bytes(b"id,pop,f0,m0\n1,12,6,6\n" if role.endswith("data") else b"fixture-raster-import-bytes")
    return source


def focus_edit(dialog, role):
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_inputs)
    dialog.show()
    QApplication.processEvents()
    edit = dialog.project_presenter.input_widgets[role].lineEdit()
    edit.setFocus()
    QApplication.processEvents()
    assert edit.hasFocus()
    return edit


@pytest.mark.parametrize("role", ROLES)
def test_keyboard_path_is_draft_until_focusout_and_commits_once(native_dialog, tmp_path, role):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    source = source_for(tmp_path, role)
    edit = focus_edit(dialog, role)
    completed = []
    dialog.import_controller.completed.connect(lambda: completed.append(True))
    before = Path(dialog.config_manager.config_path).read_bytes()
    QTest.keyClicks(edit, str(source))
    assert edit.text() == str(source) and edit.isModified()
    assert not dialog.is_busy
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    QApplication.processEvents()
    wait_until(lambda: not dialog.is_busy and dialog.config_manager.get_config()[role] == source.name)
    assert len(completed) == 1
    assert not edit.isModified()
    edit.editingFinished.emit()  # A second focus event must not re-import.
    QApplication.processEvents()
    assert not dialog.is_busy and len(completed) == 1
    assert dialog.project_presenter.input_widgets[role].filePath() == str(tmp_path / "project/data" / source.name)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("close_method", ["reject", "close"])
def test_close_discards_manual_draft_without_clearing_registered_input(native_dialog, tmp_path, role, close_method):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    widget = dialog.project_presenter.input_widgets[role]
    source = source_for(tmp_path, role)
    widget.setFilePath(str(source))
    wait_until(lambda: not dialog.is_busy)
    before = Path(dialog.config_manager.config_path).read_bytes()
    edit = focus_edit(dialog, role)
    edit.selectAll()
    QTest.keyClicks(edit, str(source_for(tmp_path, role, "_new")))
    assert edit.isModified() and not dialog.is_busy
    getattr(dialog, close_method)()
    QApplication.processEvents()
    assert not dialog.is_busy
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    assert widget.filePath() == str(tmp_path / "project/data" / source.name)
    dialog.show()
    QApplication.processEvents()
    assert not dialog.is_busy


@pytest.mark.parametrize("role", ROLES)
def test_deferred_clear_after_selecting_candidate_cannot_mutate_previous_project(native_dialog, tmp_path, role):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    widget = dialog.project_presenter.input_widgets[role]
    widget.setFilePath(str(source_for(tmp_path, role)))
    wait_until(lambda: not dialog.is_busy)
    path = Path(dialog.config_manager.config_path)
    before = path.read_bytes()
    QTimer.singleShot(0, lambda: widget.setFilePath(""))
    dialog.workingDirEdit.setFilePath(str(tmp_path / "candidate"))
    QApplication.processEvents()
    assert not dialog._project_ready and not dialog.is_busy
    assert path.read_bytes() == before
    assert not (tmp_path / "candidate").exists()


def test_manual_project_path_stays_candidate_until_explicit_create(native_dialog, tmp_path):
    dialog = native_dialog
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_main)
    dialog.show()
    QApplication.processEvents()
    edit = dialog.workingDirEdit.lineEdit()
    edit.setFocus()
    QApplication.processEvents()
    candidate = tmp_path / "manually_typed_project"
    QTest.keyClicks(edit, str(candidate))
    assert edit.text() == str(candidate)
    assert not candidate.exists() and not dialog._project_ready
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert not candidate.exists() and not dialog._project_ready
    dialog.initProjectButton.click()
    assert dialog._project_ready and (candidate / "config.yaml").is_file()


def test_unload_while_manual_draft_is_focused_never_starts_import(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    before = Path(dialog.config_manager.config_path).read_bytes()
    config = Path(dialog.config_manager.config_path)
    edit = focus_edit(dialog, "census_data")
    QTest.keyClicks(edit, str(source_for(tmp_path, "census_data")))
    controller = dialog.import_controller
    dialog.dispose_when_idle()
    wait_until(lambda: sip.isdeleted(dialog))
    assert controller.worker is None and config.read_bytes() == before


def test_escape_discards_focused_draft_before_hide(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    path = Path(dialog.config_manager.config_path)
    before = path.read_bytes()
    edit = focus_edit(dialog, "census_data")
    QTest.keyClicks(edit, str(source_for(tmp_path, "census_data")))
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not dialog.isVisible() and not dialog.is_busy
    assert path.read_bytes() == before
    assert dialog.populationCensusFileWidget.filePath() == ""


def test_direct_qobject_delete_with_dirty_draft_does_not_import_or_touch_deleted_children(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    path = Path(dialog.config_manager.config_path)
    before = path.read_bytes()
    edit = focus_edit(dialog, "census_data")
    QTest.keyClicks(edit, str(source_for(tmp_path, "census_data")))
    controller = dialog.import_controller
    dialog.deleteLater()
    wait_until(lambda: sip.isdeleted(dialog))
    assert controller.worker is None and path.read_bytes() == before


def test_real_filter_clear_button_clears_registered_input(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    widget = dialog.populationCensusFileWidget
    source = source_for(tmp_path, "census_data")
    widget.setFilePath(str(source))
    wait_until(lambda: not dialog.is_busy)
    edit = focus_edit(dialog, "census_data")
    clear_buttons = [button for button in edit.findChildren(QToolButton) if button.isVisible()]
    assert len(clear_buttons) == 1, [(b.objectName(), b.toolTip()) for b in clear_buttons]
    QTest.mouseClick(clear_buttons[0], Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    if edit.isModified():
        QTest.keyClick(edit, Qt.Key.Key_Tab)
        QApplication.processEvents()
    assert not dialog.is_busy
    assert dialog.config_manager.get_config()["census_data"] is None
    assert widget.filePath() == "" and (tmp_path / "project/data" / source.name).read_bytes() == source.read_bytes()


def test_committed_invalid_manual_path_restores_prior_canonical_input(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    source = source_for(tmp_path, "census_data")
    widget = dialog.populationCensusFileWidget
    widget.setFilePath(str(source))
    wait_until(lambda: not dialog.is_busy)
    before = Path(dialog.config_manager.config_path).read_bytes()
    edit = focus_edit(dialog, "census_data")
    edit.selectAll()
    QTest.keyClicks(edit, str(tmp_path / "missing.csv"))
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    QApplication.processEvents()
    wait_until(lambda: not dialog.is_busy)
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    assert widget.filePath() == str(tmp_path / "project/data" / source.name)
    assert "could not be completed" in dialog.statusLabel.text().casefold()


def ready_project(dialog, tmp_path, ready=True):
    project = tmp_path / "project"
    initialize(dialog, project)
    for role, name in (("census_data", "old.csv"), ("mastergrid", "zones.tif"), ("cov", "cov.tif")):
        (project / "data" / name).write_bytes(b"id,pop\n1,12\n" if role == "census_data" else b"transactional-input-fixture")
    dialog.config_manager.update_many({"mastergrid": "zones.tif", "census_data": "old.csv",
                                      "covariates": {"cov": "cov.tif"} if ready else {}})
    dialog._loading_project = True
    dialog._load_project_inputs()
    dialog._loading_project = False
    dialog._refresh_readiness()
    assert dialog.mainStartButton.isEnabled() == ready
    return project


@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("size", [4096, 6 * 1024 * 1024])
@pytest.mark.parametrize("action", ["mouse", "held-mouse", "return", "enter"])
def test_confirming_draft_never_reinterprets_same_action_as_cancel_or_old_analysis(native_dialog, tmp_path, monkeypatch, ready, size, action):
    dialog = native_dialog
    project = ready_project(dialog, tmp_path, ready)
    source = tmp_path / "new.csv"
    source.write_bytes(b"id,pop\n" + b"1,99\n" * (size // 5))
    imports, cancelled, attempts, results = [], [], [], []
    start, stop = dialog.import_controller.start, dialog.import_controller.stop
    def record_start(*args, **kwargs):
        imports.append(args[2])
        return start(*args, **kwargs)
    def record_stop(*args, **kwargs):
        cancelled.append(True)
        return stop(*args, **kwargs)
    monkeypatch.setattr(dialog.import_controller, "start", record_start)
    monkeypatch.setattr(dialog.import_controller, "stop", record_stop)
    monkeypatch.setattr(dialog.process_executor, "start_analysis", lambda: attempts.append(True))
    dialog.import_controller.imported.connect(results.append)
    edit = focus_edit(dialog, "census_data")
    edit.selectAll()
    QTest.keyClicks(edit, str(source))
    assert edit.isModified() and not dialog.is_busy
    if action == "mouse":
        QTest.mouseClick(dialog.mainStartButton, Qt.MouseButton.LeftButton)
    elif action == "held-mouse":
        QTest.mousePress(dialog.mainStartButton, Qt.MouseButton.LeftButton)
        QApplication.processEvents()  # Real user holds press across event-loop turns.
        QTest.qWait(25)
        assert not imports and edit.isModified()
        QTest.mouseRelease(dialog.mainStartButton, Qt.MouseButton.LeftButton)
    else:
        QTest.keyClick(edit, Qt.Key.Key_Return if action == "return" else Qt.Key.Key_Enter)
    QApplication.processEvents()
    if not ready and action in {"mouse", "held-mouse"}:
        assert not imports and not results and edit.isModified()
        assert dialog.config_manager.get_config()["census_data"] == "old.csv"
    else:
        wait_until(lambda: not dialog.is_busy and dialog.config_manager.get_config()["census_data"] == source.name)
        assert imports == [[str(source)]] and len(results) == 1 and not results[0]["cancelled"]
        assert (project / "data" / source.name).read_bytes() == source.read_bytes()
        assert dialog.populationCensusFileWidget.filePath() == str(project / "data" / source.name)
        # The import is committed, but analysis is never silently auto-started.
        if ready:
            QTest.mouseClick(dialog.mainStartButton, Qt.MouseButton.LeftButton)
            assert attempts == [True]
            attempts.clear()
    assert not cancelled and not attempts
    assert (project / "data/old.csv").read_bytes() == b"id,pop\n1,12\n"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_input_enter_commits_each_owned_role_once_without_default_action(native_dialog, tmp_path, monkeypatch, role, key):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    source = source_for(tmp_path, role)
    attempts, results = [], []
    monkeypatch.setattr(dialog.process_executor, "start_analysis", lambda: attempts.append(True))
    dialog.import_controller.imported.connect(results.append)
    edit = focus_edit(dialog, role)
    QTest.keyClicks(edit, str(source))
    QTest.keyClick(edit, key)
    QApplication.processEvents()
    wait_until(lambda: not dialog.is_busy and dialog.config_manager.get_config()[role] == source.name)
    assert len(results) == 1 and not results[0]["cancelled"] and not attempts


@pytest.mark.parametrize("action", ["return", "enter", "shortcut"])
def test_keyboard_run_outside_input_edits_stays_available(native_dialog, tmp_path, monkeypatch, action):
    dialog = native_dialog
    ready_project(dialog, tmp_path)
    attempts = []
    monkeypatch.setattr(dialog.process_executor, "start_analysis", lambda: attempts.append(True))
    dialog.show()
    dialog.mainStartButton.setFocus()
    QApplication.processEvents()
    assert dialog.mainStartButton.hasFocus()
    assert dialog.mainStartButton.focusPolicy() == Qt.FocusPolicy.TabFocus
    if action == "shortcut":
        QTest.keyClick(dialog, Qt.Key.Key_R, Qt.KeyboardModifier.AltModifier)
    else:
        QTest.keyClick(dialog.mainStartButton, Qt.Key.Key_Return if action == "return" else Qt.Key.Key_Enter)
    QApplication.processEvents()
    wait_until(lambda: attempts == [True])  # Qt shortcut uses animateClick's delay.


@pytest.mark.parametrize("action", ["mouse", "return"])
def test_later_explicit_cancel_still_stops_owned_import(native_dialog, native_package, tmp_path, monkeypatch, action):
    dialog = native_dialog
    ready_project(dialog, tmp_path)
    source = source_for(tmp_path, "census_data", "_later")
    module = importlib.import_module(native_package[0] + ".services.file_handlers")
    original = module.FileHandler.copy_to_data_dir
    entered, release = threading.Event(), threading.Event()
    def held_copy(self, *args, **kwargs):
        entered.set()
        while not release.is_set():
            kwargs["cancellation_token"].check()
            time.sleep(0.005)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(module.FileHandler, "copy_to_data_dir", held_copy)
    edit = focus_edit(dialog, "census_data")
    edit.selectAll()
    QTest.keyClicks(edit, str(source))
    QTest.keyClick(edit, Qt.Key.Key_Return)
    wait_until(entered.is_set)
    try:
        assert dialog.is_busy and dialog.mainStartButton.text() == "Cancel import"
        if action == "mouse":
            QTest.mouseClick(dialog.mainStartButton, Qt.MouseButton.LeftButton)
        else:
            dialog.mainStartButton.setFocus()
            QTest.keyClick(dialog.mainStartButton, Qt.Key.Key_Return)
        wait_until(lambda: not dialog.is_busy)
        assert dialog.config_manager.get_config()["census_data"] == "old.csv"
        assert "cancelled" in dialog.statusLabel.text().casefold()
    finally:
        release.set()
        wait_until(lambda: not dialog.is_busy)


def test_run_remains_reachable_by_native_tab_navigation(native_dialog, tmp_path):
    dialog = native_dialog
    ready_project(dialog, tmp_path)
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_home)
    dialog.show()
    dialog.mainTabWidget.setFocus()
    QApplication.processEvents()
    for _ in range(80):
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        QApplication.processEvents()
        if dialog.mainStartButton.hasFocus():
            break
    assert dialog.mainStartButton.hasFocus()
