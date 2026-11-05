"""Real Qt visual acceptance of the separately prepared Engine-page frontend.

The production package comes from PYPOPRF_TEST_PLUGIN_ROOT. Runtime fixtures
exercise owned workers without pip, browser actions, or host numerical imports.
"""
import importlib
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

pytest.importorskip("qgis.core", reason="Frontend acceptance requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, PreparedRuntime,
                              wait_until, prepare_inputs)


def capture(dialog, name):
    path = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if path:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(directory / (name + ".png")))


def dark_palette(dialog):
    palette = QPalette(dialog.palette())
    for role, color in ((QPalette.ColorRole.Window, "#20242a"),
                        (QPalette.ColorRole.Base, "#181c22"),
                        (QPalette.ColorRole.WindowText, "#f4f6f8"),
                        (QPalette.ColorRole.Text, "#f4f6f8"),
                        (QPalette.ColorRole.Button, "#303640"),
                        (QPalette.ColorRole.ButtonText, "#f4f6f8"),
                        (QPalette.ColorRole.Highlight, "#4f91d1")):
        palette.setColor(role, QColor(color))
    dialog.setPalette(palette)


def dispose(dialog):
    if not sip.isdeleted(dialog):
        dialog.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(dialog))


def make_dialog(native_package, tmp_path, state):
    alias, _ = native_package
    runtime = importlib.import_module(alias + ".services.runtime_manager")
    dialog_type = importlib.import_module(alias + ".gui.dialogs.main_dialog").PyPopRFDialog

    class ControlledRuntime(PreparedRuntime):
        PYTHON_VERSION = (3, 12)

        def __init__(self):
            super().__init__(alias)
            self.entered = Event()

        def get_python(self, cancellation_token=None):
            cancellation_token.check()
            if state == "checking":
                self.entered.set()
                cancellation_token.event.wait(10)
                cancellation_token.check()
            if state in {"ready", "repair_failed"}:
                return self.path
            raise runtime.RuntimeNotReady("The isolated engine has not been prepared")

        def discover_interpreters(self, cancellation_token=None):
            cancellation_token.check()
            if state == "no_python":
                return []
            return [{"path": str(self.path), "version": "3.12.10", "bits": 64,
                     "source": "verified", "recommended": True, "embedded": False}]

        def setup(self, python, progress=None, cancellation_token=None):
            self.setup_calls += 1
            cancellation_token.check()
            if state == "installing":
                progress(25, "Downloading a verified rasterio wheel")
                self.entered.set()
                cancellation_token.event.wait(10)
                cancellation_token.check()
            raise runtime.RuntimeSetupError("Hash-locked package verification failed; retry the engine setup")

    manager = ControlledRuntime()
    dialog = dialog_type(runtime_manager=manager, cache_root=tmp_path / "cache")
    if state == "checking":
        wait_until(manager.entered.is_set)
    else:
        wait_until(lambda: not dialog.is_busy)
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    dialog.show()
    QApplication.processEvents()
    if state in {"repair_failed", "installing", "failed"}:
        if state == "repair_failed":
            dialog.engineAdvancedToggle.setChecked(True)
        dialog._setup_runtime()
        wait_until(manager.entered.is_set if state == "installing" else lambda: not dialog.is_busy)
    return dialog, manager


@pytest.mark.parametrize("state", ["checking", "no_python", "selected", "installing",
                                   "ready", "repair_failed", "failed"])
@pytest.mark.parametrize("width,height,dark", [(720, 520, False), (920, 720, False), (720, 520, True)])
def test_real_engine_state_matrix(native_package, tmp_path, state, width, height, dark):
    dialog, manager = make_dialog(native_package, tmp_path, state)
    try:
        dialog.resize(width, height)
        if dark:
            dark_palette(dialog)
        QApplication.processEvents()
        assert dialog.runtime_presenter.state == state
        assert dialog.width() == width and dialog.height() == height
        assert dialog.mainTabWidget.currentWidget() is dialog.tab_engine
        assert dialog.engineScrollArea.horizontalScrollBar().maximum() == 0
        assert dialog.runtimeStatusLabel.textFormat() == Qt.TextFormat.PlainText
        if dark:
            style = importlib.import_module(native_package[0] + ".gui.widgets.visual_style")
            background = dialog.runtimeGroup.palette().color(QPalette.ColorRole.Window)
            for label in (dialog.engineStateTitle, dialog.runtimeStatusLabel, dialog.runtimeErrorLabel):
                if label.isVisible():
                    assert style.contrast(label.palette().color(QPalette.ColorRole.WindowText), background) >= 4.5
        assert dialog.rect().contains(dialog.mainStartButton.mapTo(dialog, QPoint(0, 0)))
        assert dialog.rect().contains(dialog.mainStartButton.mapTo(dialog, dialog.mainStartButton.rect().bottomRight()))
        assert not dialog.mainStartButton.isEnabled()
        for label in (dialog.engineIntroLabel, dialog.engineStateTitle, dialog.runtimeStatusLabel,
                      dialog.runtimeHelpLabel, dialog.engineSummaryLabel, dialog.runtimeErrorLabel):
            if label.isVisible():
                assert label.height() >= label.heightForWidth(label.width())
        if state in {"ready", "repair_failed"}:
            assert Path(dialog.runtime_controller.python) == manager.path
            if state == "ready":
                assert dialog.pythonChoiceGroup.isHidden()
                assert not dialog.engineAdvancedToggle.isChecked()
                assert not dialog.setupRuntimeButton.isVisible()
            assert dialog.engineNextButton.isVisible()
        else:
            assert not dialog.runtime_controller.python
        if state in {"repair_failed", "failed"}:
            assert dialog.runtimeErrorLabel.isVisible()
            assert "verification failed" in dialog.runtimeErrorLabel.text()
        if state == "no_python":
            assert dialog.downloadPythonButton.isVisible() and dialog.refreshPythonButton.isVisible()
            assert not dialog.setupRuntimeButton.isVisible()
        if state == "selected":
            assert dialog.setupRuntimeButton.isVisible() and dialog.setupRuntimeButton.isEnabled()
            assert not dialog.downloadPythonButton.isVisible()
        if state in {"checking", "installing"}:
            assert dialog.is_busy and dialog.runtimeProgressBar.maximum() == 0
        if state == "installing":
            assert dialog.cancelSetupButton.isVisible() and dialog.cancelSetupButton.isEnabled()
            assert "rasterio" in dialog.runtimeStatusLabel.text()
            dialog.engineScrollArea.ensureWidgetVisible(dialog.cancelSetupButton)
            QApplication.processEvents()
            center = dialog.cancelSetupButton.mapTo(dialog.engineScrollArea.viewport(), dialog.cancelSetupButton.rect().center())
            assert dialog.engineScrollArea.viewport().rect().contains(center)
        capture(dialog, f"engine-{state}-{width}-{'dark' if dark else 'light'}")
        if state == "ready" and width == 920:
            dialog.home_panel.requestedEngine.emit()
            assert dialog.mainTabWidget.currentWidget() is dialog.tab_engine
            dialog.home_panel.requestedProject.emit()
            assert dialog.mainTabWidget.currentWidget() is dialog.tab_main
            assert not dialog.runtimeGroup.isVisible()
            capture(dialog, "project-ready-no-engine-form")
            dialog.mainTabWidget.setCurrentWidget(dialog.tab_home)
            capture(dialog, "home-ready-footer")
    finally:
        dispose(dialog)


def test_ready_footer_run_and_failed_repair_keeps_real_engine(native_package, tmp_path):
    dialog, manager = make_dialog(native_package, tmp_path, "ready")
    try:
        prepare_inputs(dialog, tmp_path / "external-project")
        dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
        dialog.engineAdvancedToggle.setChecked(True)
        dialog._setup_runtime()
        wait_until(lambda: not dialog.is_busy)
        assert Path(dialog.runtime_controller.python) == manager.path
        assert dialog.mainStartButton.isEnabled()
        assert "previous engine remains available" in dialog.statusLabel.text()
        for tab in (dialog.tab_home, dialog.tab_main, dialog.tab_engine, dialog.tab_inputs,
                    dialog.tab_settings, dialog.tab_results, dialog.tab_details):
            dialog.mainTabWidget.setCurrentWidget(tab)
            QApplication.processEvents()
            assert dialog.mainStartButton.isVisible() and dialog.mainStartButton.isEnabled()
            assert dialog.readinessRowLabel.isVisible()
            assert dialog.mainStartButton.mapTo(dialog, QPoint(0, 0)).y() > dialog.mainTabWidget.geometry().bottom()
        dialog.engineReadyButton.click()
        assert dialog.mainTabWidget.currentWidget() is dialog.tab_engine
        capture(dialog, "engine-failed-repair-run-ready")
    finally:
        dispose(dialog)


def test_actual_high_dpi_engine_actions_are_reachable(native_package, tmp_path):
    alias, _ = native_package
    root = Path(sys.modules[alias].__path__[0])
    artifact = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR", str(tmp_path))
    script = r'''
import importlib, os, sys
from pathlib import Path
from types import ModuleType
if os.environ.get("PYPOPRF_TEST_DEPS"):
    sys.path.insert(0, os.environ["PYPOPRF_TEST_DEPS"])
from qgis.testing import start_app
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt import sip
from tests.native.test_qgis_native import PreparedRuntime, wait_until
app=start_app()
p=ModuleType("frontend_highdpi"); p.__path__=[sys.argv[1]]; sys.modules[p.__name__]=p
dialog=importlib.import_module(p.__name__+".gui.dialogs.main_dialog").PyPopRFDialog(
    runtime_manager=PreparedRuntime(p.__name__),cache_root=Path(sys.argv[2])/"cache")
try:
    wait_until(lambda:not dialog.is_busy)
    dialog.resize(720,520); dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    dialog.show(); QApplication.processEvents()
    assert dialog.devicePixelRatioF()>=1.4
    assert dialog.width()==720 and dialog.height()==520
    assert dialog.engineScrollArea.horizontalScrollBar().maximum()==0
    assert dialog.pythonChoiceGroup.isHidden()
    assert dialog.grab().save(str(Path(sys.argv[3])/"engine-ready-150dpi.png"))
    dialog.engineAdvancedToggle.setChecked(True); QApplication.processEvents()
    for button in (dialog.setupRuntimeButton,dialog.refreshPythonButton,dialog.manualPythonCheckBox):
        dialog.engineScrollArea.ensureWidgetVisible(button); QApplication.processEvents()
        point=button.mapTo(dialog.engineScrollArea.viewport(),button.rect().center())
        assert dialog.engineScrollArea.viewport().rect().contains(point)
    for label in (dialog.runtimeHelpLabel,dialog.engineSummaryLabel,dialog.pythonChoiceHint):
        assert label.height()>=label.heightForWidth(label.width())
    assert dialog.grab().save(str(Path(sys.argv[3])/"engine-manage-150dpi.png"))
finally:
    dialog.dispose_when_idle(); wait_until(lambda:sip.isdeleted(dialog))
'''
    env = dict(os.environ, QT_SCALE_FACTOR="1.5")
    result = subprocess.run([sys.executable, "-c", script, str(root), str(tmp_path), artifact],
                            env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
