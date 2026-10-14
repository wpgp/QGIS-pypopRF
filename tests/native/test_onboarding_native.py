"""Integrated first-use journey and recovery on genuine Qt/QGIS."""
import importlib
from threading import Event

import pytest

pytest.importorskip("qgis.core", reason="Onboarding requires genuine QGIS")
pytestmark = pytest.mark.qgis
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt import sip
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              PreparedRuntime, wait_until, initialize, capture_state)


def test_home_brand_navigation_and_nonmodal_about(native_dialog):
    dialog = native_dialog
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_home
    assert not dialog.home_panel.logo_label.pixmap().isNull()
    assert "ZIP" in dialog.home_panel.guidance.text()
    dialog.home_panel.step_buttons["project"].click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_main
    dialog.aboutButton.click()
    QApplication.processEvents()
    assert dialog._about_window.isVisible() and not dialog._about_window.isModal()
    dialog._about_window.close()
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_home)
    capture_state(dialog, "onboarding-home", tab=-1)


def test_no_engine_project_allowed_and_setup_error_visible_persistent(native_package, tmp_path):
    alias, _ = native_package
    runtime = importlib.import_module(alias + ".services.runtime_manager")
    dialog_type = importlib.import_module(alias + ".gui.dialogs.main_dialog").PyPopRFDialog

    class MissingRuntime(PreparedRuntime):
        def get_python(self, cancellation_token=None):
            raise runtime.RuntimeNotReady("Engine is not installed")

        def setup(self, python, progress=None, cancellation_token=None):
            raise runtime.RuntimeSetupError("The engine requires installed 64-bit CPython 3.12; found CPython 3.13, 64-bit")

    dialog = dialog_type(runtime_manager=MissingRuntime(alias), cache_root=tmp_path / "cache")
    try:
        wait_until(lambda: not dialog.is_busy)
        assert not dialog.runtime_controller.python
        assert dialog.pythonComboBox.count() >= 1
        dialog.manualPythonCheckBox.setChecked(True)
        dialog.pythonPathEdit.setText("unsupported-selected-python")
        dialog._setup_runtime()
        wait_until(lambda: not dialog.is_busy)
        for label in (dialog.runtimeErrorLabel, dialog.runtimeStatusLabel, dialog.statusLabel):
            assert "3.13" in label.text() and "3.12" in label.text()
        assert not dialog.runtimeErrorLabel.isHidden()
        saved_log = dialog.console_handler.console_text.toPlainText()
        assert "3.13" in saved_log
        initialize(dialog, tmp_path / "project")
        assert dialog._project_ready and not dialog.runtime_controller.python
        assert "3.13" in dialog.console_handler.console_text.toPlainText()
        assert not dialog.mainStartButton.isEnabled()
        assert dialog.home_panel.state["project"] and not dialog.home_panel.state["engine"]
        dialog.resize(720, 520)
        capture_state(dialog, "onboarding-setup-error", tab=0)
    finally:
        dialog.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(dialog))


def test_engine_download_progress_is_indeterminate_and_activity_bounded(native_dialog, monkeypatch):
    dialog = native_dialog
    clock = importlib.import_module(dialog.activity.__module__).time
    ticks = [10.0]
    monkeypatch.setattr(clock, "monotonic", lambda: ticks[0])
    dialog.begin_task("Setting up engine")
    dialog._runtime_progress(25, "Downloading rasterio wheel")
    assert dialog.runtimeProgressBar.maximum() == 0
    assert "rasterio" in dialog.runtimeStatusLabel.text()
    ticks[0] = 75.0
    dialog.activity._refresh()
    assert "00:01:05" in dialog.activity.text()
    for i in range(100):
        dialog.activity.record(f"package message {i}")
    assert dialog.activity.history.topLevelItemCount() == 80
    dialog._runtime_progress(85, "Checking exact versions")
    assert dialog.runtimeProgressBar.maximum() == 100
    dialog._processing_completed()
    assert not dialog.activity.timer.isActive()
    elapsed = dialog.activity.elapsed()
    ticks[0] = 1000.0
    assert dialog.activity.elapsed() == elapsed


def test_input_errors_are_plain_and_can_be_cleared(native_dialog):
    dialog = native_dialog
    dialog.set_input_error("agesex_data", "File <census.csv> exists; use existing or import a copy")
    assert "<census.csv>" in dialog._input_errors["agesex_data"].text()
    assert not dialog._input_errors["agesex_data"].isHidden()
    dialog.set_input_error("agesex_data", "")
    assert dialog._input_errors["agesex_data"].isHidden()


def test_disposal_does_not_probe_focused_manual_python(native_dialog, monkeypatch):
    dialog = native_dialog
    calls = []
    monkeypatch.setattr(dialog.runtime_controller, "inspect", lambda path: calls.append(path) or False)
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_main)
    dialog.manualPythonCheckBox.setChecked(True)
    dialog.show()
    dialog.pythonPathEdit.setText("unfinished user selection")
    dialog.pythonPathEdit.setFocus()
    QApplication.processEvents()
    dialog.dispose_when_idle()
    wait_until(lambda: sip.isdeleted(dialog))
    assert calls == []


@pytest.mark.parametrize("invalidated", [False, True])
def test_cancel_discovery_preserves_only_engine_not_known_invalid(native_package, tmp_path, invalidated):
    alias, _ = native_package
    runtime = importlib.import_module(alias + ".services.runtime_manager")
    dialog_type = importlib.import_module(alias + ".gui.dialogs.main_dialog").PyPopRFDialog

    class ControlledHealth(PreparedRuntime):
        refresh = False

        def __init__(self, alias):
            super().__init__(alias)
            self.entered = Event()

        def block(self, token):
            self.entered.set()
            token.event.wait(5)
            token.check()

        def get_python(self, cancellation_token=None):
            if self.refresh:
                if invalidated:
                    raise runtime.RuntimeNotReady("The prior engine failed verification")
                self.block(cancellation_token)
            return self.path

        def detect_python_candidates(self, cancellation_token=None):
            self.block(cancellation_token)
            return []

    manager = ControlledHealth(alias)
    dialog = dialog_type(runtime_manager=manager, cache_root=tmp_path / "cache")
    try:
        wait_until(lambda: not dialog.is_busy)
        previous = dialog.runtime_controller.python
        manager.refresh = True
        dialog.runtime_presenter.discover()
        wait_until(manager.entered.is_set)
        dialog.cancelSetupButton.click()
        wait_until(lambda: not dialog.is_busy)
        assert dialog.runtime_controller.python == (None if invalidated else previous)
        assert "cancelled" in dialog.runtimeStatusLabel.text().lower()
        assert dialog.home_panel.state["engine"] is (not invalidated)
    finally:
        dialog.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(dialog))
