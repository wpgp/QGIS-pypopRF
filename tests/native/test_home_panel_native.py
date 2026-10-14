"""Actual Qt Home/About components with explicit temporary preference storage."""
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("qgis.core", reason="Home/About acceptance requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QSettings, Qt, QEvent, QCoreApplication
from qgis.PyQt.QtGui import QPalette, QColor
from qgis.PyQt.QtWidgets import QApplication, QWidget, QVBoxLayout
from qgis.PyQt.QtTest import QSignalSpy, QTest
from qgis.core import QgsSettings
from .test_qgis_native import native_package as native_package


@pytest.fixture
def components(native_package, tmp_path):
    alias, _ = native_package
    helper = importlib.import_module(alias + ".services.plugin_info")
    home = importlib.import_module(alias + ".gui.widgets.home_panel")
    about = importlib.import_module(alias + ".gui.dialogs.about_dialog")
    info = helper.load_plugin_info(Path(__file__).resolve().parents[2])
    settings_path = tmp_path / "home-panel.ini"
    settings = QgsSettings(str(settings_path), QSettings.Format.IniFormat)
    assert Path(settings.fileName()).resolve() == settings_path.resolve()
    parent = QWidget()
    parent.resize(720, 520)
    layout = QVBoxLayout(parent)
    panel = home.HomePanel(info, parent, settings=settings)
    layout.addWidget(panel)
    yield helper, home, about, info, settings, parent, panel
    if not sip.isdeleted(parent):
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def capture(widget, name):
    path = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if path:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(directory / name))


def test_home_steps_have_no_engine_gate_or_automatic_action(components):
    _, _, _, _, _, parent, panel = components
    signals = {key: QSignalSpy(getattr(panel, "requested" + key))
               for key in ("Engine", "Project", "Inputs", "Review", "About")}
    parent.show()
    panel.refresh({"inputs_ready": True})
    QApplication.processEvents()
    assert not panel.state["inputs"]
    assert panel.step_buttons["project"].isEnabled()
    assert not panel.step_buttons["inputs"].isEnabled()
    assert all(not spy for spy in signals.values())
    QTest.mouseClick(panel.step_buttons["project"], Qt.MouseButton.LeftButton)
    assert len(signals["Project"]) == 1
    panel.refresh({"project_ready": True, "inputs_ready": True})
    assert panel.step_buttons["inputs"].isEnabled() and panel.step_buttons["review"].isEnabled()
    assert not panel.state["review"] and "engine setup" in panel.step_labels["review"].text()
    panel.refresh({"engine_ready": True, "project_ready": True, "inputs_ready": True})
    assert panel.state["review"]
    panel.refresh({"engine_ready": True, "project_ready": True, "inputs_ready": True, "busy": True})
    assert all(not button.isEnabled() for button in panel.step_buttons.values())
    assert panel.about_button.isEnabled()
    assert len(signals["Engine"]) == 0 and len(signals["Review"]) == 0


def test_home_guidance_preference_does_not_persist_readiness(components):
    _, home, _, info, settings, parent, panel = components
    panel.refresh({"engine_ready": True, "project_ready": True, "inputs_ready": True})
    panel.guidance_toggle.setChecked(False)
    settings.sync()
    assert settings.allKeys() == [home.HomePanel.GUIDANCE_KEY]
    another = home.HomePanel(info, parent, settings=settings)
    assert not another.guidance_toggle.isChecked()
    assert another.state == {"engine": False, "project": False, "inputs": False, "review": False, "busy": False}


@pytest.mark.parametrize("state,name", [({}, "home-start.png"),
    ({"project_ready": True}, "home-project-without-engine.png"),
    ({"engine_ready": True}, "home-engine-ready.png"),
    ({"engine_ready": True, "project_ready": True}, "home-inputs-needed.png"),
    ({"engine_ready": True, "project_ready": True, "inputs_ready": True}, "home-review-ready.png")])
@pytest.mark.parametrize("width", [720, 920])
def test_home_small_dark_palette_renders_nonoverlapping_live_steps(components, state, name, width):
    _, _, _, _, _, parent, panel = components
    palette = QPalette(parent.palette())
    palette.setColor(QPalette.ColorRole.Window, QColor("#20242a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f6f8"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#303640"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f4f6f8"))
    parent.setPalette(palette)
    parent.resize(width, 520 if width == 720 else 720)
    panel.refresh(dict(state, status="Literal <b>state</b>\n" + "diagnostic " * 500))
    parent.show()
    QApplication.processEvents()
    assert parent.width() == width and parent.height() == (520 if width == 720 else 720)
    assert panel.status_label.textFormat() == Qt.TextFormat.PlainText
    assert "<b>state</b>" in panel.status_label.text() and len(panel.status_label.text()) <= 1000
    assert panel.scroll.horizontalScrollBar().maximum() == 0
    for label in (panel.guidance, panel.description_label, panel.next_label, panel.scope_label):
        assert label.height() >= label.heightForWidth(label.width())
    for key in panel.step_titles:
        title, status, button = panel.step_titles[key], panel.step_labels[key], panel.step_buttons[key]
        assert title.geometry().right() < status.geometry().left()
        assert status.geometry().right() < button.geometry().left()
        assert not title.geometry().intersects(status.geometry())
        assert not status.geometry().intersects(button.geometry())
    assert not parent.grab().isNull()
    capture(parent, f"{Path(name).stem}-{width}.png")


def test_about_is_nonmodal_parent_owned_and_safe_links_are_explicit(components, monkeypatch):
    _, _, about, info, _, parent, _ = components
    opened = []
    monkeypatch.setattr(about.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    dialog = about.AboutDialog(info, parent)
    dialog.show()
    QApplication.processEvents()
    assert not dialog.isModal() and not opened
    assert info.version in dialog.identity_label.text()
    assert info.author in dialog.author_label.text()
    assert "MIT" in dialog.license_label.text() and "GPL" in dialog.license_label.text()
    assert dialog.citation.toPlainText() == info.citation
    assert not dialog._open_web("file:///private") and not dialog._open_web("javascript:alert(1)")
    assert not opened
    QTest.mouseClick(dialog.link_buttons[0], Qt.MouseButton.LeftButton)
    assert opened == [info.links[0].url]
    capture(dialog, "about-citation.png")
    dialog.close()
    assert not sip.isdeleted(dialog)
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(dialog)


def test_home_high_dpi_720_window_keeps_actions_reachable(native_package, tmp_path):
    alias, _ = native_package
    root = Path(sys.modules[alias].__path__[0])
    screenshot = tmp_path / "home-high-dpi.png"
    script = r'''
import importlib, sys
from pathlib import Path
from types import ModuleType
from qgis.testing import start_app
from qgis.PyQt.QtCore import QSettings, QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QApplication
from qgis.core import QgsSettings
app=start_app()
package=ModuleType("home_hidpi_plugin"); package.__path__=[sys.argv[1]]
sys.modules[package.__name__]=package
info=importlib.import_module(package.__name__+".services.plugin_info").load_plugin_info(sys.argv[1])
home=importlib.import_module(package.__name__+".gui.widgets.home_panel")
settings=QgsSettings(sys.argv[2],QSettings.Format.IniFormat)
assert Path(settings.fileName()).resolve()==Path(sys.argv[2]).resolve()
parent=QWidget(); parent.resize(720,520); layout=QVBoxLayout(parent)
panel=home.HomePanel(info,parent,settings); layout.addWidget(panel)
panel.refresh({'engine_ready':True,'project_ready':True,'inputs_ready':True})
parent.show(); QApplication.processEvents()
assert parent.devicePixelRatioF()>=1.4
assert parent.width()==720 and parent.height()==520
assert panel.scroll.horizontalScrollBar().maximum()==0
for label in (panel.guidance, panel.description_label, panel.next_label, panel.scope_label):
    assert label.height()>=label.heightForWidth(label.width())
for button in panel.step_buttons.values():
    panel.scroll.ensureWidgetVisible(button)
    QApplication.processEvents()
    point=button.mapTo(panel.scroll.viewport(),button.rect().center())
    assert panel.scroll.viewport().rect().contains(point)
assert parent.grab().save(sys.argv[3])
parent.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
'''
    environment = dict(os.environ, QT_SCALE_FACTOR="1.5")
    result = subprocess.run([sys.executable, "-c", script, str(root), str(tmp_path / "hidpi.ini"),
                             str(screenshot)], env=environment, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert screenshot.is_file()
    artifact = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if artifact:
        import shutil
        shutil.copy2(screenshot, Path(artifact) / "home-high-dpi.png")
