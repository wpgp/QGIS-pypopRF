"""Engine destination, stateful engine view, bottom readiness/Run footer on genuine Qt/QGIS."""
import importlib
import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("qgis.core", reason="Frontend acceptance requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPoint, QRect, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              PreparedRuntime, wait_until, initialize)


def capture_engine(dialog, name):
    """Engine-tab artifact; the shared capture_state helper predates the Engine tab."""
    directory = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        dialog.show()
        QApplication.processEvents()
        assert dialog.grab().save(str(target / f"{name}.png"))


def in_dialog(dialog, widget):
    return QRect(widget.mapTo(dialog, QPoint(0, 0)), widget.size())


def open_dialog(alias, manager, tmp_path):
    module = importlib.import_module(alias + ".gui.dialogs.main_dialog")
    return module.PyPopRFDialog(runtime_manager=manager, cache_root=tmp_path / "cache")


def dispose(dialog):
    if not sip.isdeleted(dialog):
        dialog.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(dialog))


def shown(dialog, widget):
    return widget.isVisibleTo(dialog)


def record(path):
    return {"path": str(path), "version": "3.12.10", "bits": 64, "source": "PATH",
            "recommended": True, "embedded": False}


def missing_engine(alias, interpreters):
    runtime = importlib.import_module(alias + ".services.runtime_manager")

    class MissingEngine(PreparedRuntime):
        def __init__(self, alias):
            super().__init__(alias)
            self.entered = Event()

        def get_python(self, cancellation_token=None):
            raise runtime.RuntimeNotReady("Engine is not installed")

        def discover_interpreters(self, cancellation_token=None):
            return [record(self.path)] if interpreters else []

        def setup(self, python, progress=None, cancellation_token=None):
            progress(10, "Creating a dedicated virtual environment")
            self.entered.set()
            cancellation_token.event.wait(10)
            cancellation_token.check()
            return self.path

    return MissingEngine(alias)


def scripted_engine(alias):
    """Engine whose health, listing and interpreter probes each test changes between operations."""
    runtime = importlib.import_module(alias + ".services.runtime_manager")

    class ScriptedEngine(PreparedRuntime):
        def __init__(self, alias):
            super().__init__(alias)
            self.healthy = False
            self.listed = []
            self.compatible = set()
            self.discovery = "complete"  # or "failed" / "blocked"
            self.entered = Event()

        def get_python(self, cancellation_token=None):
            if not self.healthy:
                raise runtime.RuntimeNotReady("Engine is not installed")
            return self.path

        def discover_interpreters(self, cancellation_token=None):
            if self.discovery == "failed":
                raise RuntimeError("Python registry could not be read")
            if self.discovery == "blocked":
                self.entered.set()
                cancellation_token.event.wait(10)
                cancellation_token.check()
            return [record(path) for path in self.listed]

        def check_interpreter(self, python, cancellation_token=None):
            if str(python) not in self.compatible:
                raise RuntimeError("not a 64-bit CPython 3.12")
            return record(python)

        def setup(self, python, progress=None, cancellation_token=None):
            path = super().setup(python, progress, cancellation_token)
            self.healthy = True
            return path

    return ScriptedEngine(alias)


def probe(dialog, path):
    """The steps of Browse… after the file dialog returns ``path``."""
    dialog.manualPythonCheckBox.setChecked(True)
    dialog.pythonPathEdit.setText(str(path))
    dialog.runtime_presenter.inspect(str(path))
    wait_until(lambda: not dialog.is_busy)


def test_fresh_discovery_and_manual_verification_helpers(native_package):
    alias, _ = native_package
    presenter = importlib.import_module(alias + ".gui.presenters.runtime_presenter")
    fresh = presenter.is_fresh_discovery
    listing = {"python": None, "interpreters": [], "candidates": [], "error": None, "cancelled": False}
    assert fresh("discover", listing) and fresh("check", listing)  # a no-engine check discovers
    assert fresh("discover", dict(listing, python="engine"))
    assert not fresh("check", dict(listing, python="engine"))  # healthy-engine check lists nothing
    assert not fresh("setup", listing)
    assert not fresh("discover", dict(listing, error="registry unreadable"))
    assert not fresh("discover", dict(listing, error="cancelled", cancelled=True))
    verified = presenter.manual_selection_verified
    assert verified(True, " C:/py/python.exe ", "C:/py/python.exe")
    assert not verified(False, "C:/py/python.exe", "C:/py/python.exe")  # manual mode left
    assert not verified(True, "C:/other/python.exe", "C:/py/python.exe")  # different path
    assert not verified(True, "C:/py/python.exe", None)  # typed, never probed
    assert not verified(True, "", None)


@pytest.mark.parametrize("manual", [False, True])
def test_refreshed_empty_discovery_drops_stale_discovered_choice(native_package, tmp_path, manual):
    alias, _ = native_package
    manager = scripted_engine(alias)
    manager.listed = [manager.path]
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        assert presenter.state == "selected" and dialog.pythonComboBox.count() == 1
        assert dialog.pythonPathEdit.text() == str(manager.path)
        typed = str(tmp_path / "typed" / "python.exe")
        if manual:
            dialog.manualPythonCheckBox.setChecked(True)
            dialog.pythonPathEdit.setText(typed)
        manager.listed = []  # uninstalled or upgraded meanwhile
        presenter.discover()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_controller.python is None
        assert dialog.pythonComboBox.count() == 0 and not shown(dialog, dialog.pythonComboBox)
        assert presenter.state == "no_python"
        assert dialog.engineStateTitle.text() == "No compatible Python found"
        assert shown(dialog, dialog.downloadPythonButton)
        if manual:
            # Explicit text stays, but an unprobed path is no selection.
            assert dialog.pythonPathEdit.text() == typed and shown(dialog, dialog.setupRuntimeButton)
        else:
            assert dialog.pythonPathEdit.text() == ""
            assert not shown(dialog, dialog.setupRuntimeButton)
        assert not dialog.mainStartButton.isEnabled() and not dialog.home_panel.state["engine"]
    finally:
        dispose(dialog)


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_unfinished_refresh_keeps_previous_choices(native_package, tmp_path, outcome):
    alias, _ = native_package
    manager = scripted_engine(alias)
    manager.listed = [manager.path]
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        assert presenter.state == "selected"
        manager.listed = []
        manager.discovery = "blocked" if outcome == "cancelled" else "failed"
        presenter.discover()
        if outcome == "cancelled":
            wait_until(manager.entered.is_set)
            dialog.cancelSetupButton.click()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_controller.python is None
        assert dialog.pythonComboBox.count() == 1 and dialog.pythonPathEdit.text() == str(manager.path)
        assert not shown(dialog, dialog.downloadPythonButton)
        if outcome == "cancelled":
            assert presenter.state == "selected"
            assert "cancelled" in dialog.runtimeStatusLabel.text().lower()
        else:
            assert presenter.state == "failed"
            assert "registry could not be read" in dialog.runtimeErrorLabel.text()
    finally:
        manager.discovery = "complete"
        dispose(dialog)


def test_setup_and_healthy_checks_never_clear_choices_and_cancel_keeps_engine(native_package, tmp_path):
    alias, _ = native_package
    manager = scripted_engine(alias)
    manager.listed = [manager.path]
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        manager.listed = []
        dialog._setup_runtime()  # a setup success lists no interpreters
        wait_until(lambda: not dialog.is_busy)
        assert presenter.state == "ready" and dialog.runtime_controller.python
        assert dialog.pythonComboBox.count() == 1
        dialog.runtime_controller.check()  # healthy-engine check performs no discovery
        wait_until(lambda: not dialog.is_busy)
        assert presenter.state == "ready" and dialog.pythonComboBox.count() == 1
        previous = dialog.runtime_controller.python
        manager.discovery = "blocked"
        presenter.discover()
        wait_until(manager.entered.is_set)
        dialog.cancelSetupButton.click()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_controller.python == previous
        assert presenter.state == "ready" and dialog.home_panel.state["engine"]
        assert dialog.pythonComboBox.count() == 1
        assert "cancelled" in dialog.runtimeStatusLabel.text().lower()
    finally:
        manager.discovery = "complete"
        dispose(dialog)


def test_verified_manual_python_after_empty_discovery_is_selected_until_changed(native_package, tmp_path):
    alias, _ = native_package
    manager = scripted_engine(alias)
    manager.compatible = {str(manager.path)}
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    other = tmp_path / "other" / "python.exe"
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        assert presenter.state == "no_python"
        dialog.manualPythonCheckBox.setChecked(True)
        dialog.pythonPathEdit.setText(str(manager.path))
        assert presenter.state == "no_python"  # nonempty text alone is not verification
        assert shown(dialog, dialog.downloadPythonButton)
        probe(dialog, manager.path)
        assert presenter.state == "selected"
        assert dialog.engineStateTitle.text() == "Engine not set up yet"
        assert dialog.pythonComboBox.count() == 0
        assert shown(dialog, dialog.setupRuntimeButton) and not shown(dialog, dialog.downloadPythonButton)
        assert not shown(dialog, dialog.runtimeErrorLabel)
        # Verifying a Python never makes the managed engine ready.
        assert dialog.runtime_controller.python is None and not dialog.home_panel.state["engine"]
        assert not dialog.mainStartButton.isEnabled()
        # A different path is unverified at once; returning to the old text needs a new probe.
        dialog.pythonPathEdit.setText(str(other))
        assert presenter.state == "no_python" and shown(dialog, dialog.downloadPythonButton)
        dialog.pythonPathEdit.setText(str(manager.path))
        assert presenter.state == "no_python"
        # A failed probe of the current path leaves it unverified, with the reason visible.
        probe(dialog, other)
        assert presenter.state == "no_python"
        assert shown(dialog, dialog.runtimeErrorLabel) and shown(dialog, dialog.downloadPythonButton)
        assert "cannot be used" in dialog.runtimeErrorLabel.text()
        probe(dialog, manager.path)
        assert presenter.state == "selected" and not shown(dialog, dialog.runtimeErrorLabel)
        dialog.manualPythonCheckBox.setChecked(False)  # leaving manual mode drops the selection
        assert presenter.state == "no_python"
    finally:
        dispose(dialog)


def test_manual_probe_with_healthy_engine_never_replaces_ready(native_package, tmp_path):
    alias, _ = native_package
    manager = scripted_engine(alias)
    manager.healthy = True
    manager.compatible = {str(manager.path)}
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        previous = dialog.runtime_controller.python
        assert presenter.state == "ready"
        dialog.engineAdvancedToggle.setChecked(True)
        probe(dialog, tmp_path / "other" / "python.exe")
        assert presenter.state == "ready" and dialog.runtime_controller.python == previous
        assert shown(dialog, dialog.runtimeErrorLabel) and shown(dialog, dialog.engineNextButton)
        assert "cannot be used" in dialog.runtimeErrorLabel.text()
        probe(dialog, manager.path)
        assert presenter.state == "ready" and not shown(dialog, dialog.runtimeErrorLabel)
        assert not shown(dialog, dialog.downloadPythonButton)  # verified route, not recovery
    finally:
        dispose(dialog)


def test_engine_has_its_own_destination_and_project_stays_separate(native_dialog):
    dialog = native_dialog
    tabs = dialog.mainTabWidget
    titles = [tabs.tabText(index) for index in range(tabs.count())]
    assert titles == ["Home", "Engine", "Project", "Input data", "Settings", "Results", "Details"]
    assert dialog.tab_engine is not dialog.tab_main
    assert dialog.tab_engine.isAncestorOf(dialog.runtimeGroup)
    assert dialog.tab_engine.isAncestorOf(dialog.pythonComboBox)
    assert not dialog.tab_main.isAncestorOf(dialog.setupRuntimeButton)
    assert dialog.tab_main.isAncestorOf(dialog.workingDirEdit)
    dialog.engineReadyButton.click()
    assert tabs.currentWidget() is dialog.tab_engine
    dialog.projectReadyButton.click()
    assert tabs.currentWidget() is dialog.tab_main
    dialog.home_panel.step_buttons["engine"].click()
    assert tabs.currentWidget() is dialog.tab_engine
    # Home's single next action follows live state: engine ready, no project yet.
    assert dialog.home_panel.next_button.text() == "Create / open project"
    dialog.home_panel.next_button.click()
    assert tabs.currentWidget() is dialog.tab_main


def test_ready_engine_shows_success_and_hides_routine_setup(native_dialog, tmp_path):
    dialog = native_dialog
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    assert dialog.runtime_presenter.state == "ready"
    assert dialog.engineStateTitle.text() == "Ready to calculate"
    assert dialog.runtimeStatusLabel.text() == "Analysis engine ready"
    assert str(dialog.runtime_controller.python)[-12:] in dialog.engineSummaryLabel.toolTip()
    assert shown(dialog, dialog.engineSummaryLabel) and shown(dialog, dialog.engineNextButton)
    for widget in (dialog.pythonChoiceGroup, dialog.downloadPythonButton, dialog.refreshPythonButton,
                   dialog.setupRuntimeButton, dialog.manualPythonCheckBox, dialog.runtimeErrorLabel,
                   dialog.runtimeProgressBar, dialog.cancelSetupButton):
        assert not shown(dialog, widget), widget.objectName()
    assert dialog.engineNextButton.text() == "Continue to Project"
    dialog.engineNextButton.click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_main
    initialize(dialog, tmp_path / "project")
    assert dialog.engineNextButton.text() == "Continue to Input data"
    # Maintenance is explicit and collapsed by default.
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    assert shown(dialog, dialog.engineAdvancedToggle) and not dialog.engineAdvancedToggle.isChecked()
    dialog.engineAdvancedToggle.setChecked(True)
    assert shown(dialog, dialog.pythonChoiceGroup) and shown(dialog, dialog.setupRuntimeButton)
    assert dialog.setupRuntimeButton.text() == "Repair / update engine"
    assert not shown(dialog, dialog.downloadPythonButton)  # no evidence that Python is missing
    dialog.engineAdvancedToggle.setChecked(False)
    assert not shown(dialog, dialog.pythonChoiceGroup)


def test_first_asynchronous_check_is_presented_as_checking_not_missing(native_package, tmp_path):
    alias, _ = native_package

    class SlowHealth(PreparedRuntime):
        def __init__(self, alias):
            super().__init__(alias)
            self.release = Event()

        def get_python(self, cancellation_token=None):
            self.release.wait(10)
            return super().get_python(cancellation_token)

    manager = SlowHealth(alias)
    dialog = open_dialog(alias, manager, tmp_path)
    try:
        assert dialog.runtime_controller.is_running
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        assert dialog.runtime_presenter.state == "checking"
        assert dialog.engineStateTitle.text().startswith("Checking")
        assert "No compatible" not in dialog.runtimeStatusLabel.text()
        assert not shown(dialog, dialog.downloadPythonButton)
        assert not shown(dialog, dialog.pythonChoiceGroup)
        assert dialog.home_panel.step_labels["engine"].text() == "Checking the engine…"
        assert "Set up the analysis engine" not in dialog.home_panel.next_label.text()
        assert "waits until the check finishes" in dialog.runtimeHelpLabel.text()
        assert not dialog.mainStartButton.isEnabled()
        manager.release.set()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_presenter.state == "ready"
        assert dialog.home_panel.state["engine"]
    finally:
        manager.release.set()
        dispose(dialog)


@pytest.mark.parametrize("interpreters", [False, True])
def test_missing_python_and_selected_python_are_distinct_states(native_package, tmp_path, interpreters):
    alias, _ = native_package
    dialog = open_dialog(alias, missing_engine(alias, interpreters), tmp_path)
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        assert not dialog.runtime_controller.python and not dialog.mainStartButton.isEnabled()
        assert shown(dialog, dialog.pythonChoiceGroup) and shown(dialog, dialog.refreshPythonButton)
        assert not shown(dialog, dialog.engineAdvancedToggle) and not shown(dialog, dialog.engineNextButton)
        if interpreters:
            assert dialog.runtime_presenter.state == "selected"
            assert dialog.engineStateTitle.text() == "Engine not set up yet"
            assert shown(dialog, dialog.pythonComboBox) and shown(dialog, dialog.setupRuntimeButton)
            assert dialog.setupRuntimeButton.text() == "Set up engine"
            assert not shown(dialog, dialog.downloadPythonButton)
        else:
            assert dialog.runtime_presenter.state == "no_python"
            assert dialog.engineStateTitle.text() == "No compatible Python found"
            assert shown(dialog, dialog.downloadPythonButton)
            assert not shown(dialog, dialog.setupRuntimeButton) and not shown(dialog, dialog.pythonComboBox)
            dialog.manualPythonCheckBox.setChecked(True)
            assert shown(dialog, dialog.pythonPathEdit) and shown(dialog, dialog.setupRuntimeButton)
        capture_engine(dialog, f"engine-{dialog.runtime_presenter.state}")
    finally:
        dispose(dialog)


def test_cancelled_setup_reports_genuine_stage_and_never_sets_readiness(native_package, tmp_path):
    alias, _ = native_package
    manager = missing_engine(alias, True)
    dialog = open_dialog(alias, manager, tmp_path)
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        dialog._setup_runtime()
        assert dialog.runtime_presenter.state == "installing"
        wait_until(lambda: "virtual environment" in dialog.runtimeStatusLabel.text())
        assert "virtual environment" in dialog.statusLabel.text()
        assert dialog.runtimeProgressBar.maximum() == 100 and dialog.runtimeProgressBar.value() == 10
        assert shown(dialog, dialog.cancelSetupButton) and shown(dialog, dialog.runtimeProgressBar)
        assert not shown(dialog, dialog.pythonChoiceGroup)
        assert not dialog.mainStartButton.isEnabled()
        dialog.cancelSetupButton.click()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_controller.python is None
        assert "cancelled" in dialog.runtimeStatusLabel.text().lower()
        assert dialog.runtime_presenter.state == "selected"
        assert dialog.engineStateTitle.text() != "Ready to calculate"
        assert not dialog.home_panel.state["engine"]
        assert dialog.engineReadyButton.accessibleName() == "Engine: needed"
    finally:
        dispose(dialog)


def test_failed_repair_keeps_engine_and_error_until_a_new_attempt_succeeds(native_dialog, monkeypatch):
    dialog = native_dialog
    manager = dialog.runtime_controller.manager
    previous = dialog.runtime_controller.python
    fail = [True]
    original = manager.setup

    def setup(python, progress=None, cancellation_token=None):
        if fail[0]:
            raise RuntimeError("wheel <verification> failed")
        return original(python, progress, cancellation_token)

    monkeypatch.setattr(manager, "setup", setup)
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    dialog.engineAdvancedToggle.setChecked(True)
    dialog._setup_runtime()
    wait_until(lambda: not dialog.is_busy)
    assert dialog.runtime_controller.python == previous
    assert dialog.runtime_presenter.state == "repair_failed"
    assert dialog.engineStateTitle.text().startswith("Repair failed")
    assert "wheel <verification> failed" in dialog.runtimeErrorLabel.text()
    assert shown(dialog, dialog.runtimeErrorLabel) and shown(dialog, dialog.engineNextButton)
    assert dialog.home_panel.state["engine"]
    # A later, successful discovery is not a successful repair: the failure stays.
    dialog.runtime_presenter.discover()
    wait_until(lambda: not dialog.is_busy)
    dialog._refresh_readiness()
    assert shown(dialog, dialog.runtimeErrorLabel)
    assert dialog.runtime_presenter.state == "repair_failed"
    capture_engine(dialog, "engine-repair-failed")
    fail[0] = False
    dialog._setup_runtime()
    wait_until(lambda: not dialog.is_busy)
    assert dialog.runtime_presenter.state == "ready"
    assert not shown(dialog, dialog.runtimeErrorLabel)
    assert dialog.engineStateTitle.text() == "Ready to calculate"


def test_run_action_style_mirrors_controller_state_without_enabling(native_dialog):
    dialog = native_dialog
    button = dialog.mainStartButton
    accent = dialog.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name()
    assert dialog._run_role == "run" and accent in button.styleSheet()
    assert button.font().bold() and button.minimumWidth() >= 130
    assert not button.isEnabled()  # no project: presentation must not authorize Run
    dialog._tools_busy_changed(True)
    assert button.text() == "Stop data tool" and dialog._run_role == "stop"
    stop_style = button.styleSheet()
    assert stop_style and accent not in stop_style.split("QPushButton:hover")[0]
    # Mirror the executor's stopping sequence: disabled text change, then status.
    button.setEnabled(False)
    button.setText("Stopping…")
    dialog.set_task_status("Stopping after the current operation…")
    assert dialog._run_role == "stopping" and "dashed" in button.styleSheet()
    assert not button.isEnabled()
    dialog._tools_busy_changed(False)
    assert button.text() == "Run analysis" and dialog._run_role == "run"
    assert not button.isEnabled()


@pytest.mark.parametrize("size", [(720, 520), (920, 720)])
def test_readiness_footer_sits_below_content_beside_run_and_fits(native_dialog, size):
    dialog = native_dialog
    dialog.resize(*size)
    dialog.show()
    dialog.set_task_status("A long diagnostic status " * 40)
    for tab in (dialog.tab_home, dialog.tab_engine, dialog.tab_main, dialog.tab_inputs,
                dialog.tab_settings, dialog.tab_results, dialog.tab_details):
        dialog.mainTabWidget.setCurrentWidget(tab)
        QApplication.processEvents()
        assert (dialog.width(), dialog.height()) == size
        tabs_bottom = dialog.mainTabWidget.geometry().bottom()
        chips = in_dialog(dialog, dialog.engineReadyButton)
        run = in_dialog(dialog, dialog.mainStartButton)
        # One checklist, below the working content and directly above the Run action.
        assert tabs_bottom < chips.top() and chips.bottom() < run.top()
        assert dialog.rect().contains(run)
        assert dialog.statusLabel.height() >= dialog.statusLabel.heightForWidth(dialog.statusLabel.width())
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    QApplication.processEvents()
    assert dialog.engineScrollArea.horizontalScrollBar().maximum() == 0
    for label in (dialog.engineIntroLabel, dialog.engineStateTitle, dialog.runtimeStatusLabel,
                  dialog.engineSummaryLabel, dialog.runtimeHelpLabel):
        assert label.sizePolicy().hasHeightForWidth()
        assert label.height() >= label.heightForWidth(label.width()), label.objectName()
    capture_engine(dialog, f"engine-ready-{size[0]}")


LONG_STATUS = {
    "repeated": "A long diagnostic status " * 40,
    "unbroken-path": "Could not read C:/" + "very_long_folder_name_without_spaces/" * 40 + "zones.tif",
    "multiline-html-like": ("Traceback <b>(most recent call last)</b>\n  File \"<stdin>\" & <i>frame</i>\n"
                            + "ValueError: census <id> is missing " * 40),
}


def assert_footer_fits(dialog, label=None):
    """Rendered lines of a fitted footer label fit its width, its allocation and the window."""
    label = label or dialog.statusLabel
    assert label.height() >= label.heightForWidth(label.width())
    lines = label.displayed_lines()
    assert 1 <= len(lines) <= label._max_lines
    room = label.contentsRect().width()
    assert all(label.fontMetrics().horizontalAdvance(line) <= room + 1 for line in lines), lines
    assert dialog.mainTabWidget.geometry().bottom() < in_dialog(dialog, dialog.engineReadyButton).top()
    assert dialog.rect().contains(in_dialog(dialog, dialog.mainStartButton))
    return lines


@pytest.mark.parametrize("kind", sorted(LONG_STATUS))
def test_long_status_fits_rendered_lines_and_keeps_full_message(native_package, native_dialog, kind):
    alias, _ = native_package
    status = importlib.import_module(alias + ".gui.widgets.workflow_status")
    dialog = native_dialog
    message = LONG_STATUS[kind]
    dialog.resize(720, 520)
    dialog.show()
    dialog.set_task_status(message)
    QApplication.processEvents()
    label = dialog.statusLabel
    expected = status.bounded_status(message)
    # The semantic message is unchanged; only the painted lines are fitted.
    assert label.text() == expected and label.textFormat() == Qt.TextFormat.PlainText
    assert label.toolTip() == status.plain_tooltip(expected)
    lines = assert_footer_fits(dialog)
    assert len(lines) == 3 and lines[-1].endswith("…")
    assert label.minimumSizeHint().width() < dialog.width() // 3
    if kind == "multiline-html-like":
        assert "&lt;b&gt;" in label.toolTip() and "<b>" in " ".join(lines)
    assert not dialog.grab().isNull()  # exercises the fitted paint path
    dialog.statusDetailsButton.click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_details


def test_status_presentation_recomputes_wide_narrow_wide(native_dialog):
    dialog = native_dialog
    dialog.set_task_status(LONG_STATUS["repeated"])
    message = dialog.statusLabel.text()
    dialog.resize(1180, 720)
    dialog.show()
    QApplication.processEvents()
    wide_width = dialog.statusLabel.width()
    wide = assert_footer_fits(dialog)
    dialog.resize(720, 520)
    QApplication.processEvents()
    assert dialog.statusLabel.width() < wide_width
    narrow = assert_footer_fits(dialog)
    assert len("".join(narrow)) < len("".join(wide))
    dialog.resize(1180, 720)
    QApplication.processEvents()
    # Fitting starts from the stored message again, never from the narrower output.
    assert dialog.statusLabel.text() == message
    assert assert_footer_fits(dialog) == wide


def test_larger_font_refits_status_and_keeps_run_inside(native_dialog):
    dialog = native_dialog
    dialog.resize(720, 520)
    dialog.show()
    dialog.set_task_status(LONG_STATUS["unbroken-path"])
    QApplication.processEvents()
    before = assert_footer_fits(dialog)
    font = dialog.statusLabel.font()
    font.setPointSizeF(font.pointSizeF() * 1.8)
    dialog.statusLabel.setFont(font)
    QApplication.processEvents()
    after = assert_footer_fits(dialog)
    assert len("".join(after)) < len("".join(before))
    assert not dialog.grab().isNull()


def test_long_task_stage_is_fitted_and_history_keeps_it(native_dialog):
    dialog = native_dialog
    dialog.resize(720, 520)
    dialog.show()
    stage = "Reading C:/data/" + "nested_folder_without_breaks/" * 20 + "covariate.tif"
    dialog.begin_task("Synthetic task")
    dialog.activity.record(stage)
    QApplication.processEvents()
    activity = dialog.activity
    try:
        assert stage[:180] in activity.text()
        assert_footer_fits(dialog, activity)
        history = activity.history
        assert history.topLevelItem(history.topLevelItemCount() - 1).text(1) == stage
        assert not dialog.grab().isNull()
    finally:
        activity.finish()


def test_high_dpi_long_status_fits_footer(native_package, native_dialog, tmp_path):
    alias, _ = native_package
    root = Path(sys.modules[alias].__path__[0])
    script = '''
import importlib, sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from qgis.testing import start_app
from qgis.PyQt.QtCore import QEventLoop, QTimer, QPoint, QRect
from qgis.PyQt.QtWidgets import QApplication
app = start_app()
package = ModuleType("dpi_status_plugin")
package.__path__ = [sys.argv[1]]
sys.modules[package.__name__] = package
manager_type = importlib.import_module("dpi_status_plugin.services.runtime_manager").RuntimeManager
manager = SimpleNamespace(get_python=lambda cancellation_token=None: Path(sys.argv[2]),
                          child_environment=manager_type.child_environment)
dialog_type = importlib.import_module("dpi_status_plugin.gui.dialogs.main_dialog").PyPopRFDialog
dialog = dialog_type(runtime_manager=manager, cache_root=Path(sys.argv[3]) / "cache")
loop = QEventLoop()
dialog.runtime_controller.completed.connect(loop.quit)
QTimer.singleShot(3000, loop.quit)
loop.exec()
assert not dialog.is_busy
dialog.resize(720, 520)
dialog.show()
dialog.set_task_status("Could not read C:/" + "very_long_folder_name_without_spaces/" * 40)
QApplication.processEvents()
label = dialog.statusLabel
assert dialog.devicePixelRatioF() >= 1.4
assert label.height() >= label.heightForWidth(label.width())
assert 1 <= len(label.displayed_lines()) <= 3
run = QRect(dialog.mainStartButton.mapTo(dialog, QPoint(0, 0)), dialog.mainStartButton.size())
assert dialog.rect().contains(run)
assert not dialog.grab().isNull()
dialog.logger.close()
dialog.close()
'''
    environment = dict(os.environ, QT_SCALE_FACTOR="1.5")
    result = subprocess.run([sys.executable, "-c", script, str(root), str(native_dialog.runtime_controller.python),
                             str(tmp_path)], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_palette_change_restyles_primary_action(native_dialog):
    dialog = native_dialog
    original = QApplication.palette()
    dark = QPalette(original)
    for role, color in ((QPalette.ColorRole.Window, "#25272a"), (QPalette.ColorRole.Button, "#34373b"),
                        (QPalette.ColorRole.WindowText, "#f0f1f2"), (QPalette.ColorRole.ButtonText, "#f0f1f2"),
                        (QPalette.ColorRole.Highlight, "#537ab6"), (QPalette.ColorRole.HighlightedText, "#ffffff")):
        dark.setColor(role, QColor(color))
    try:
        QApplication.setPalette(dark)
        dialog.show()
        QApplication.processEvents()
        assert "#537ab6" in dialog.mainStartButton.styleSheet()
        assert "#537ab6" in dialog.home_panel.next_button.styleSheet()
    finally:
        QApplication.setPalette(original)
        QApplication.processEvents()


def test_busy_engine_help_never_promises_project_operations(native_package):
    alias, _ = native_package
    presenter = importlib.import_module(alias + ".gui.presenters.runtime_presenter")
    for state in (presenter.ENGINE_CHECKING, presenter.ENGINE_INSTALLING):
        text = presenter.HELP[state].lower()
        # The unchanged project gate refuses create/open while the dialog is busy.
        assert "you can create" not in text and "projects stay usable" not in text
        assert "can still be inspected" in text and "creating or opening a project waits" in text


ACTIVE = QPalette.ColorGroup.Active
LIGHT = {"Window": "#efefef", "WindowText": "#1b1b1b", "Base": "#ffffff", "Text": "#1b1b1b",
         "Button": "#e1e1e1", "ButtonText": "#1b1b1b", "Highlight": "#2a62bc", "HighlightedText": "#ffffff"}
DARK = {"Window": "#202326", "WindowText": "#e8eaed", "Base": "#181a1d", "Text": "#e8eaed",
        "Button": "#2c3035", "ButtonText": "#e8eaed", "Highlight": "#3d6fb4", "HighlightedText": "#ffffff"}


def host_palette(colors):
    palette = QPalette(QApplication.palette())
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    return palette


def rendered(image, dialog, widget, x, y):
    """Pixel actually painted at widget coordinates (x, y) in a dialog grab."""
    ratio = image.devicePixelRatio()
    point = widget.mapTo(dialog, QPoint(x, y))
    return image.pixelColor(int(point.x() * ratio), int(point.y() * ratio))


def strongest_ink(image, dialog, widget, background, style, skip_left=0):
    """Highest contrast of any painted pixel inside ``widget`` against ``background``."""
    ratio = image.devicePixelRatio()
    rect = in_dialog(dialog, widget)
    left = max(0, int((rect.left() + skip_left) * ratio))
    right = min(image.width(), int((rect.right() + 1) * ratio))
    top, bottom = max(0, int(rect.top() * ratio)), min(image.height(), int((rect.bottom() + 1) * ratio))
    best = 1.0
    for y in range(top, bottom):
        for x in range(left, right):
            best = max(best, style.contrast(background, image.pixelColor(x, y)))
    return best


def assert_readable(image, dialog, label, background, style, skip_left=0):
    # Effective widget foreground (what QLabel paints with), not a helper's computed color.
    ink = label.palette().color(ACTIVE, label.foregroundRole())
    name = label.objectName() or label.text()[:30]
    assert shown(dialog, label) and label.text(), name
    assert style.contrast(ink, background) >= 4.5, (name, ink.name(), background.name())
    # The painted glyphs must stand out too; antialiasing keeps this below the palette ratio.
    assert strongest_ink(image, dialog, label, background, style, skip_left) >= 3.0, name
    return ink


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("state", ["ready", "repair_failed", "failed"])
def test_card_text_follows_host_window_palette(native_package, tmp_path, theme, state):
    alias, _ = native_package
    style = importlib.import_module(alias + ".gui.widgets.visual_style")
    manager = missing_engine(alias, True) if state == "failed" else PreparedRuntime(alias)
    dialog = open_dialog(alias, manager, tmp_path)
    presenter = dialog.runtime_presenter
    application_text = QApplication.palette().color(ACTIVE, QPalette.ColorRole.WindowText)
    try:
        wait_until(lambda: not dialog.is_busy)
        dialog.resize(920, 720)
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        dialog.show()
        QApplication.processEvents()  # polished under the application palette first, as in QGIS
        # The host (QGIS window) theme is set on the window only, never globally.
        dialog.setPalette(host_palette(DARK if theme == "dark" else LIGHT))
        if state != "ready":
            presenter.show_error("Engine setup failed: wheel verification failed for <package>", kind="setup")
            presenter.render()
        QApplication.processEvents()
        assert presenter.state == state
        assert QApplication.palette().color(ACTIVE, QPalette.ColorRole.WindowText) == application_text
        host = dialog.palette()
        text = host.color(ACTIVE, QPalette.ColorRole.WindowText)
        image = dialog.grab().toImage()

        card = dialog.runtimeGroup
        surface = rendered(image, dialog, card, card.width() - 20, card.height() - 5)
        expected = style.mix(host.color(ACTIVE, QPalette.ColorRole.Window),
                             host.color(ACTIVE, QPalette.ColorRole.Base), 0.5)
        assert style.contrast(surface, expected) < 1.1, (surface.name(), expected.name())
        labels = [dialog.engineStateTitle, dialog.runtimeStatusLabel]
        if state == "ready":
            labels.append(dialog.engineSummaryLabel)
        for label in labels:
            assert assert_readable(image, dialog, label, surface, style) == text, label.objectName()
            assert label.height() >= label.heightForWidth(label.width()), label.objectName()
        assert_readable(image, dialog, dialog.runtimeHelpLabel, surface, style)  # muted, still legible
        assert dialog.engineScrollArea.horizontalScrollBar().maximum() == 0

        error = dialog.runtimeErrorLabel
        if state == "ready":
            assert not shown(dialog, error)
        else:
            kind = "warning" if state == "repair_failed" else "critical"
            assert style.semantic(host, kind).name() in error.styleSheet()  # semantic edge kept
            box = rendered(image, dialog, error, error.width() - 8, 2)
            assert assert_readable(image, dialog, error, box, style, skip_left=4) == text
            assert error.height() >= error.heightForWidth(error.width())
        capture_engine(dialog, f"engine-contrast-{theme}-{state}")

        dialog.mainTabWidget.setCurrentWidget(dialog.tab_home)
        QApplication.processEvents()
        image = dialog.grab().toImage()
        home = dialog.home_panel
        surface = rendered(image, dialog, home.next_card, home.next_card.width() - 20,
                           home.next_card.height() - 5)
        assert assert_readable(image, dialog, home.next_label, surface, style) == text
        assert_readable(image, dialog, home.next_caption, surface, style)
    finally:
        dispose(dialog)


def test_disposal_with_focused_manual_python_on_engine_tab_never_probes(native_dialog, monkeypatch):
    dialog = native_dialog
    calls = []
    monkeypatch.setattr(dialog.runtime_controller, "inspect", lambda path: calls.append(path) or False)
    dialog.show()
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    dialog.engineAdvancedToggle.setChecked(True)
    dialog.manualPythonCheckBox.setChecked(True)
    assert shown(dialog, dialog.pythonPathEdit)
    dialog.pythonPathEdit.setText("unfinished user selection")
    dialog.pythonPathEdit.setFocus()
    QApplication.processEvents()
    dialog.dispose_when_idle()
    wait_until(lambda: sip.isdeleted(dialog))
    assert calls == []
