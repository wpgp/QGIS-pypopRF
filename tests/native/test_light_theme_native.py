"""Plugin-local white theme under hostile host palettes/styles on genuine Qt."""
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("qgis.core", reason="Light-theme acceptance requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QToolTip
from .test_qgis_native import native_package as native_package, PreparedRuntime, wait_until, initialize

WHITE = "#ffffff"
TEXT = "#0f172a"
BLUE = "#1d4ed8"
MUTED = "#475569"
DISABLED = "#64748b"
HOST_QSS = """
QWidget { background-color: #111827; color: #fde68a; }
QPushButton { background-color: #7c2d12; color: #fef3c7; }
QLineEdit, QComboBox, QSpinBox, QTableWidget { background-color: #301934; color: #ff00cc;
    selection-background-color: #ff00ff; selection-color: #000000; }
QCheckBox::indicator { background-color: #7c2d12; border: 2px solid #ff00cc; }
QToolTip { background-color: #111827; color: #fde68a; }
"""


def host_palette(window="#111827", text="#fde68a"):
    palette = QPalette(QApplication.palette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role, color in ((QPalette.ColorRole.Window, window), (QPalette.ColorRole.Base, "#301934"),
                            (QPalette.ColorRole.Button, "#7c2d12"), (QPalette.ColorRole.WindowText, text),
                            (QPalette.ColorRole.Text, "#ff00cc"), (QPalette.ColorRole.ButtonText, text),
                            (QPalette.ColorRole.Highlight, "#ff00ff"),
                            (QPalette.ColorRole.HighlightedText, "#000000")):
            palette.setColor(group, role, QColor(color))
    return palette


def screenshot(widget, name):
    directory = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(path / (name + ".png")))


def color_pixels(widget, color):
    """Count genuinely painted pixels, not stylesheet/palette declarations."""
    image = widget.grab().toImage()
    return sum(image.pixelColor(x, y).name() == color
               for y in range(image.height()) for x in range(image.width()))


@pytest.fixture
def isolated_host(native_package):
    app = QApplication.instance()
    original_palette, original_style = QPalette(app.palette()), app.styleSheet()
    app.setPalette(host_palette())
    app.setStyleSheet(HOST_QSS)
    unrelated = QWidget()
    unrelated.resize(320, 100)
    layout = QVBoxLayout(unrelated)
    label = QLabel("Unrelated host widget", unrelated)
    layout.addWidget(label)
    unrelated.show()
    QApplication.processEvents()
    yield native_package, app, unrelated, label
    unrelated.close()
    unrelated.deleteLater()
    app.setStyleSheet(original_style)
    app.setPalette(original_palette)
    QApplication.processEvents()


@pytest.fixture
def windows(isolated_host, tmp_path):
    package, app, unrelated, host_label = isolated_host
    alias, _ = package
    dialog_type = importlib.import_module(alias + ".gui.dialogs.main_dialog").PyPopRFDialog
    main = dialog_type(runtime_manager=PreparedRuntime(alias), cache_root=tmp_path / "cache")
    wait_until(lambda: not main.is_busy)
    about = importlib.import_module(alias + ".gui.dialogs.about_dialog").AboutDialog(main.plugin_info, main)
    wizard = importlib.import_module(alias + ".gui.dialogs.preparation_dialog").PreparationWizard(main)
    summary = importlib.import_module(alias + ".gui.dialogs.population_summary_dialog").PopulationSummaryDialog(
        main, [tmp_path / "synthetic-map.tif"])
    conflict = importlib.import_module(alias + ".gui.dialogs.import_conflict_dialog").ImportConflictDialog(
        {"kind": "census_data", "filename": "census.csv", "reuse_allowed": False,
         "sidecar_compatible": True, "headers": ["id", "population"]}, main)
    result = {"main": main, "about": about, "preparation": wizard, "summary": summary, "conflict": conflict}
    yield package, app, unrelated, host_label, result
    for window in (conflict, summary, wizard, about):
        if not sip.isdeleted(window):
            window.close()
    if not sip.isdeleted(main):
        main.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(main))


def assert_light(window):
    palette = window.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == WHITE
    assert palette.color(QPalette.ColorRole.WindowText).name() == TEXT
    assert palette.color(QPalette.ColorRole.Highlight).name() == BLUE
    image = window.grab().toImage()
    assert not image.isNull()
    # The window's genuinely painted outer background must be white, not merely its palette.
    assert image.pixelColor(1, 1).name() == WHITE


def assert_host_unchanged(app, unrelated, host_label, saved):
    palette, stylesheet, widget_palette, text_color, tip_palette, image = saved
    assert app.palette() == palette and app.styleSheet() == stylesheet
    assert unrelated.palette() == widget_palette
    assert host_label.palette().color(QPalette.ColorRole.WindowText) == text_color
    assert QToolTip.palette() == tip_palette
    assert unrelated.grab().toImage() == image


def host_snapshot(app, unrelated, host_label):
    QApplication.processEvents()
    return (QPalette(app.palette()), app.styleSheet(), QPalette(unrelated.palette()),
            host_label.palette().color(QPalette.ColorRole.WindowText), QPalette(QToolTip.palette()),
            unrelated.grab().toImage())


def test_fixed_palette_api_and_no_application_changes(isolated_host):
    package, app, unrelated, label = isolated_host
    theme = importlib.import_module(package[0] + ".gui.widgets.light_theme")
    saved = host_snapshot(app, unrelated, label)
    palette = theme.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == WHITE
    assert palette.color(QPalette.ColorRole.Base).name() == WHITE
    assert palette.color(QPalette.ColorRole.WindowText).name() == TEXT
    assert palette.color(QPalette.ColorRole.Text).name() == TEXT
    assert palette.color(QPalette.ColorRole.Highlight).name() == BLUE
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == DISABLED
    local = QWidget()
    try:
        theme.apply_light_theme(local)
        local.resize(300, 100)
        local.show()
        QApplication.processEvents()
        assert_light(local)
        assert_host_unchanged(app, unrelated, label, saved)
    finally:
        local.close()
        local.deleteLater()


@pytest.mark.parametrize("size", [(720, 520), (920, 720)])
def test_all_plugin_dialogs_white_under_hostile_application_before_and_after_creation(windows, size):
    _, app, unrelated, host_label, dialogs = windows
    for changed in (False, True):
        if changed:
            app.setPalette(host_palette("#09090b", "#22d3ee"))
            app.setStyleSheet(HOST_QSS.replace("#111827", "#09090b").replace("#fde68a", "#22d3ee"))
            QApplication.processEvents()
        saved = host_snapshot(app, unrelated, host_label)
        for name, window in dialogs.items():
            target = (size[0], max(size[1], window.minimumHeight()))
            window.resize(*target)
            window.show()
            QApplication.processEvents()
            assert (window.width(), window.height()) == target
            assert_light(window)
            if name == "main":
                assert window.readinessRowLabel.width() >= window.readinessRowLabel.sizeHint().width()
                for button in window.readiness_buttons.values():
                    assert button.width() >= button.sizeHint().width()
            assert_host_unchanged(app, unrelated, host_label, saved)
            screenshot(window, f"light-{name}-{size[0]}-{'changed-host' if changed else 'initial-host'}")
            window.hide()


def test_fields_selection_popup_indicators_and_footer_are_plugin_local(windows, tmp_path):
    package, app, unrelated, host_label, dialogs = windows
    main, wizard = dialogs["main"], dialogs["preparation"]
    initialize(main, tmp_path / "external-theme-project")
    saved = host_snapshot(app, unrelated, host_label)
    main.resize(720, 520)
    main.show()
    main.mainTabWidget.setCurrentWidget(main.tab_engine)
    main.engineAdvancedToggle.setChecked(True)
    QApplication.processEvents()
    main.pythonComboBox.clear()
    main.pythonComboBox.addItems(["Fixture interpreter one", "Fixture interpreter two"])
    main.runtime_presenter.render()
    QApplication.processEvents()
    assert main.pythonComboBox.isVisible()
    main.pythonComboBox.showPopup()
    QApplication.processEvents()
    view = main.pythonComboBox.view()
    assert view.palette().color(QPalette.ColorRole.Base).name() == WHITE
    assert view.palette().color(QPalette.ColorRole.Text).name() == TEXT
    assert view.palette().color(QPalette.ColorRole.Highlight).name() == BLUE
    assert color_pixels(view, BLUE) > 30
    screenshot(view, "light-combo-popup")
    main.pythonComboBox.hidePopup()
    main.manualPythonCheckBox.setChecked(True)
    QApplication.processEvents()
    assert color_pixels(main.manualPythonCheckBox, BLUE) > 10
    screenshot(main.manualPythonCheckBox, "light-checked-indicator")
    main.mainTabWidget.setCurrentWidget(main.tab_settings)
    QApplication.processEvents()
    for field in main.tab_settings.findChildren(QWidget):
        if field.inherits("QSpinBox") or field.inherits("QDoubleSpinBox"):
            assert field.palette().color(QPalette.ColorRole.Base).name() == WHITE
            assert field.palette().color(QPalette.ColorRole.Text).name() == TEXT
    screenshot(main, "light-settings-spin-checks")
    main.activity.record("Fixture selected table row")
    main.mainTabWidget.setCurrentWidget(main.tab_details)
    main.activity.history.setCurrentItem(main.activity.history.topLevelItem(0))
    QApplication.processEvents()
    assert main.activity.history.palette().color(QPalette.ColorRole.Base).name() == WHITE
    assert main.activity.history.palette().color(QPalette.ColorRole.Highlight).name() == BLUE
    assert color_pixels(main.activity.history, BLUE) > 30
    screenshot(main, "light-table-selection")
    wizard.show()
    QApplication.processEvents()
    assert wizard.mode.palette().color(QPalette.ColorRole.Text).name() == TEXT
    assert dialogs["summary"].summary.palette().color(QPalette.ColorRole.Base).name() == WHITE
    assert dialogs["conflict"].filenameEdit.palette().color(QPalette.ColorRole.Text).name() == TEXT
    style = importlib.import_module(package[0] + ".gui.widgets.visual_style")
    assert style.contrast(QColor(TEXT), QColor(WHITE)) >= 7
    assert style.contrast(QColor(MUTED), QColor(WHITE)) >= 4.5
    main.set_task_status("Long fixed-light diagnostic <tag> " * 100)
    QApplication.processEvents()
    assert len(main.statusLabel.displayed_lines()) <= 3
    assert main.statusLabel.height() >= main.statusLabel.heightForWidth(main.statusLabel.width())
    assert main.rect().contains(main.mainStartButton.mapTo(main, main.mainStartButton.rect().bottomRight()))
    assert_host_unchanged(app, unrelated, host_label, saved)


def test_light_theme_150dpi_remains_scoped_under_host_styles(native_package, tmp_path):
    alias, _ = native_package
    root = Path(sys.modules[alias].__path__[0])
    destination = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR", str(tmp_path))
    script = r'''
import importlib, os, sys
from pathlib import Path
from types import ModuleType
if os.environ.get("PYPOPRF_TEST_DEPS"):
    sys.path.insert(0, os.environ["PYPOPRF_TEST_DEPS"])
from qgis.testing import start_app
from qgis.PyQt.QtWidgets import QApplication, QWidget
from qgis.PyQt.QtGui import QColor,QPalette
from qgis.PyQt import sip
from tests.native.test_qgis_native import PreparedRuntime,wait_until
app=start_app()
host=QPalette(app.palette()); host.setColor(QPalette.ColorRole.Window,QColor("#111827"))
host.setColor(QPalette.ColorRole.WindowText,QColor("#fde68a")); app.setPalette(host)
qss="QWidget {background-color:#111827;color:#fde68a;}"; app.setStyleSheet(qss)
before=QPalette(app.palette())
p=ModuleType("light_hidpi");p.__path__=[sys.argv[1]];sys.modules[p.__name__]=p
dialog=importlib.import_module(p.__name__+".gui.dialogs.main_dialog").PyPopRFDialog(
    runtime_manager=PreparedRuntime(p.__name__),cache_root=Path(sys.argv[2])/"cache")
try:
    wait_until(lambda:not dialog.is_busy)
    dialog.resize(720,520);dialog.mainTabWidget.setCurrentWidget(dialog.tab_engine)
    dialog.show();QApplication.processEvents()
    assert dialog.devicePixelRatioF()>=1.4
    assert dialog.width()==720 and dialog.height()==520
    assert dialog.palette().color(QPalette.ColorRole.Window).name()=="#ffffff"
    assert dialog.palette().color(QPalette.ColorRole.WindowText).name()=="#0f172a"
    assert dialog.engineScrollArea.horizontalScrollBar().maximum()==0
    dialog.set_task_status("Long diagnostic path "+"x"*4000);QApplication.processEvents()
    assert len(dialog.statusLabel.displayed_lines())<=3
    assert dialog.statusLabel.height()>=dialog.statusLabel.heightForWidth(dialog.statusLabel.width())
    assert app.palette()==before and app.styleSheet()==qss
    assert dialog.grab().save(str(Path(sys.argv[3])/"light-engine-150dpi.png"))
finally:
    dialog.dispose_when_idle();wait_until(lambda:sip.isdeleted(dialog))
'''
    result = subprocess.run([sys.executable, "-c", script, str(root), str(tmp_path), destination],
                            env=dict(os.environ, QT_SCALE_FACTOR="1.5"), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
