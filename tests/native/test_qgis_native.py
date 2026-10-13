"""Actual QGIS/Qt UI, managed-child and lifecycle acceptance."""
import builtins
import importlib
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("qgis.core", reason="Native QGIS acceptance requires QGIS")
pytestmark = pytest.mark.qgis

from qgis.testing import start_app
from qgis.PyQt.QtCore import QEventLoop, QTimer, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QPalette, QColor, QFontDatabase


def wait_until(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    loop, timer = QEventLoop(), QTimer()
    timer.setInterval(10)
    def poll():
        if predicate() or time.monotonic() >= deadline:
            loop.quit()
    timer.timeout.connect(poll)
    timer.start()
    if not predicate():
        loop.exec()
    timer.stop()
    assert predicate(), "Native operation did not finish before its deadline"


def capture_state(dialog, name, tab=0):
    directory = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        dialog.mainTabWidget.setCurrentIndex(tab)
        dialog.show()
        QApplication.processEvents()
        assert dialog.grab().save(str(target / f"{name}.png"))


@pytest.fixture(scope="module")
def native_package():
    if os.name == "nt":
        # Extracted portable Qt5 offscreen builds otherwise render blank text.
        # Test infrastructure only: never override the user's production fonts.
        os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"))
    app = start_app()
    try:
        families = QFontDatabase.families()  # Qt6 static API
    except TypeError:
        families = QFontDatabase().families()  # Qt5 instance API
    assert families, "The native font backend has no renderable font families"
    alias = "native_pypoprf_acceptance"
    package = ModuleType(alias)
    package.__path__ = [os.environ.get("PYPOPRF_TEST_PLUGIN_ROOT", str(Path(__file__).resolve().parents[2]))]
    sys.modules[alias] = package
    yield alias, app
    for name in list(sys.modules):
        if name == alias or name.startswith(alias + "."):
            sys.modules.pop(name, None)


class PreparedRuntime:
    """Inject an existing disposable-container engine; never install on the host."""
    def __init__(self, alias):
        manager = importlib.import_module(alias + ".services.runtime_manager").RuntimeManager
        self.child_environment = manager.child_environment
        self.path = Path(os.environ.get("PYPOPRF_TEST_ENGINE", sys.executable))
        self.setup_calls = 0

    def runtime_ready(self):
        return True

    def get_python(self, cancellation_token=None):
        if cancellation_token:
            cancellation_token.check()
        return self.path

    def detect_python_candidates(self, cancellation_token=None):
        return [self.path]

    def setup(self, python, progress=None, cancellation_token=None):
        self.setup_calls += 1
        cancellation_token.check()
        progress(100, "Engine ready")
        return self.path


@pytest.fixture
def native_dialog(native_package, tmp_path):
    alias, _ = native_package
    module = importlib.import_module(alias + ".gui.dialogs.main_dialog")
    dialog = module.PyPopRFDialog(runtime_manager=PreparedRuntime(alias), cache_root=tmp_path / "cache")
    wait_until(lambda: not dialog.runtime_controller.is_running)
    assert dialog.runtime_controller.python
    yield dialog
    if sip.isdeleted(dialog):
        return
    if dialog.is_busy:
        dialog.cancel_all()
        wait_until(lambda: not dialog.is_busy)
    dialog.logger.close()
    dialog.deleteLater()
    QApplication.processEvents()


def initialize(dialog, root):
    dialog.workingDirEdit.setFilePath(str(root))
    dialog.init_project()
    assert dialog.config_manager.working_dir == str(root.resolve())
    assert Path(dialog.config_manager.config_path).is_file()


def prepare_inputs(dialog, root, trees=8):
    project = root / "project"
    initialize(dialog, project)
    source = root / "inputs"
    source.mkdir()
    script = '''
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
source = Path(sys.argv[1])
zones = np.repeat(np.arange(1, 9, dtype="int32"), 4).reshape(4, 8)
for name, values in (("zones", zones), ("covariate", zones.astype("float32"))):
    with rasterio.open(source / f"{name}.tif", "w", driver="GTiff", width=8, height=4,
                       count=1, dtype=values.dtype, crs="EPSG:3857",
                       transform=from_origin(0, 100, 10, 10)) as out:
        out.write(values, 1)
pd.DataFrame({"id": range(1, 9), "pop": [40 * n for n in range(1, 9)]}).to_csv(
    source / "census.csv", index=False)
'''
    engine_python(dialog, script, str(source))
    for widget, path in ((dialog.mastergridFileWidget, source / "zones.tif"),
                         (dialog.populationCensusFileWidget, source / "census.csv")):
        widget.setFilePath(str(path))
        assert dialog.import_controller.is_running
        wait_until(lambda: not dialog.import_controller.is_running)
        assert widget.filePath() == str(project / "data" / path.name)
    dialog._begin_import([str(source / "covariate.tif")], "covariate")
    wait_until(lambda: not dialog.import_controller.is_running)
    dialog.config_manager.update_many({"n_estimators": trees, "cv_folds": 3,
                                      "cv_strategy": "shuffled_zone"})
    dialog.addToQgisCheckBox.setChecked(False)
    return project, source


def engine_python(dialog, script, *args):
    python = dialog.runtime_controller.python
    result = subprocess.run([python, "-c", script, *args], text=True, capture_output=True,
        env=dialog.runtime_controller.manager.child_environment(python), timeout=30, check=True)
    return result.stdout


def test_native_activation_avoids_all_numerical_imports(native_package, tmp_path, monkeypatch):
    alias, _ = native_package
    original = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name.split(".")[0] in {"numpy", "pandas", "rasterio", "sklearn", "geopandas", "joblib"}:
            raise AssertionError(f"GUI attempted numerical import: {name}")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    from importlib.util import spec_from_file_location, module_from_spec
    root = Path(sys.modules[alias].__path__[0])
    spec = spec_from_file_location(alias, root / "__init__.py", submodule_search_locations=[str(root)])
    package = module_from_spec(spec)
    sys.modules[alias] = package
    spec.loader.exec_module(package)
    plugin = package.classFactory(SimpleNamespace())
    dialog_type = importlib.import_module(alias + ".gui.dialogs.main_dialog").PyPopRFDialog
    dialog = dialog_type(runtime_manager=PreparedRuntime(alias), cache_root=tmp_path / "cache")
    wait_until(lambda: not dialog.is_busy)
    plugin.dlg = dialog
    plugin.unload()
    assert plugin.dlg is None
    assert not any(name.startswith(alias + ".core.pypoprf") for name in sys.modules)


def test_native_create_open_preserves_config_logs_and_flags(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    assert dialog.project_presenter.view is dialog
    assert dialog.results_presenter.view is dialog
    assert dialog.preparation_presenter.view is dialog
    assert dialog.project_presenter.input_widgets["mastergrid"] is dialog.mastergridFileWidget
    assert (dialog.plugin_root / "gui" / "forms" / "main_dialog.ui").is_file()
    assert not hasattr(dialog.file_handler, "open_folder")
    initialize(dialog, tmp_path / "project")
    desktop = importlib.import_module(dialog.project_presenter.__module__.rsplit(".", 2)[0] + ".desktop")
    opened = []
    monkeypatch.setattr(desktop.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    dialog.open_project_folder()
    assert [url.toLocalFile() for url in opened] == [str((tmp_path / "project").resolve())]
    dialog.enableParallelCheckBox.setChecked(False)
    dialog.enableBlockProcessingCheckBox.setChecked(False)
    dialog.logsColumnEdit.setText("native.log")
    dialog.settings_handler._pending_log_filename = "native.log"
    dialog.settings_handler._apply_log_filename_update(dialog)
    dialog.settings_handler.save_settings(dialog)
    config = Path(dialog.config_manager.config_path)
    before = config.read_bytes()
    log = config.parent / "output" / "native.log"
    dialog.logger.info("preserved-native-log-marker")
    dialog.init_project()
    assert config.read_bytes() == before
    assert not dialog.enableParallelCheckBox.isChecked()
    assert not dialog.enableBlockProcessingCheckBox.isChecked()
    assert dialog.logsColumnEdit.text() == "native.log"
    assert "preserved-native-log-marker" in log.read_text()
    assert dialog.initProjectButton.text() == "Open project"
    capture_state(dialog, "project-open")


def test_native_qprocess_actual_engine_sanitizes_environment_and_conserves(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    project, _ = prepare_inputs(dialog, tmp_path / "проект_人口")
    for variable in ("PYTHONHOME", "PYTHONPATH", "GDAL_DATA", "PROJ_LIB", "QT_PLUGIN_PATH"):
        monkeypatch.setenv(variable, "/does/not/exist/poison")
    controller = dialog.process_executor
    owned_at_result = []
    original = controller._event_line
    def event_line(line):
        original(line)
        if controller._result:
            owned_at_result.append(controller.is_running)
    monkeypatch.setattr(controller, "_event_line", event_line)
    controller.start_analysis()
    assert controller.is_running
    wait_until(lambda: not controller.is_running)
    manifest = json.loads((controller.last_run_dir / "manifest.json").read_text())
    assert manifest["status"] == "complete", controller._stderr
    assert owned_at_result and all(owned_at_result)
    assert controller.last_result_paths
    assert dialog.mainStartButton.text() == "Run analysis"
    assert dialog.mastergridFileWidget.isEnabled()
    script = '''
import json, sys
import rasterio
with rasterio.open(sys.argv[1]) as src:
    zones = src.read(1)
with rasterio.open(sys.argv[2]) as src:
    actual = src.read(1, masked=True)
print(json.dumps([float(actual[zones == i].sum()) for i in range(1, 9)]))
'''
    sums = json.loads(engine_python(dialog, script, str(project / "data" / "zones.tif"),
                                   str(controller.last_result_paths[0])))
    assert sums == pytest.approx([zone * 40 for zone in range(1, 9)])
    assert os.environ["PYTHONHOME"] == "/does/not/exist/poison"
    assert dialog.resultsTree.topLevelItemCount() == 1
    capture_state(dialog, "analysis-complete", tab=3)
    capture_state(dialog, "input-data", tab=1)


def test_native_invalid_preflight_creates_no_run(native_dialog, tmp_path):
    dialog = native_dialog
    project = tmp_path / "project"
    initialize(dialog, project)
    # Incomplete data are refused by the external engine before output allocation.
    dialog.process_executor.start_analysis()
    assert dialog.process_executor.is_running
    wait_until(lambda: not dialog.process_executor.is_running)
    assert not (project / "output" / "runs").exists()
    assert not dialog.process_executor.last_result_paths


def test_native_close_cooperatively_cancels_actual_engine(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path, trees=300)
    controller = dialog.process_executor
    original = controller.update_progress
    closed = []
    def progress(value, message):
        original(value, message)
        if value >= 40 and not closed:
            closed.append(True)
            dialog.close()
            assert controller.is_running and dialog._close_pending
    monkeypatch.setattr(controller, "update_progress", progress)
    dialog.show()
    controller.start_analysis()
    wait_until(lambda: not controller.is_running)
    assert closed
    assert not dialog.isVisible()
    assert not controller.last_result_paths
    manifest = controller.last_run_dir / "manifest.json"
    assert json.loads(manifest.read_text())["status"] == "cancelled"


def test_native_setup_owned_thread_runs_once(native_dialog):
    dialog = native_dialog
    manager = dialog.runtime_controller.manager
    dialog.pythonPathEdit.setText(str(manager.path))
    dialog._setup_runtime()
    assert dialog.runtime_controller.is_running
    dialog._setup_runtime()
    wait_until(lambda: not dialog.runtime_controller.is_running)
    assert manager.setup_calls == 1
    assert dialog.runtimeStatusLabel.text() == "Analysis engine ready"


def test_native_import_collision_restores_canonical_input(native_dialog, tmp_path):
    dialog = native_dialog
    project, _ = prepare_inputs(dialog, tmp_path)
    original = project / "data" / "zones.tif"
    before = original.read_bytes()
    other = tmp_path / "other"
    other.mkdir()
    (other / "zones.tif").write_bytes(b"different input")
    dialog.mastergridFileWidget.setFilePath(str(other / "zones.tif"))
    wait_until(lambda: not dialog.import_controller.is_running)
    assert dialog.mastergridFileWidget.filePath() == str(original)
    assert original.read_bytes() == before


def test_native_external_gdal_mask_import_preserves_active_input(native_dialog, tmp_path):
    dialog = native_dialog
    project, source = prepare_inputs(dialog, tmp_path)
    script = '''
import sys
import numpy as np
import rasterio
from rasterio.transform import from_origin
path = sys.argv[1]
with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
    with rasterio.open(path, "w", driver="GTiff", width=8, height=4, count=1,
                       dtype="int32", crs="EPSG:3857",
                       transform=from_origin(0, 100, 10, 10)) as out:
        out.write(np.ones((4, 8), dtype="int32"), 1)
        mask = np.full((4, 8), 255, dtype="uint8")
        mask[0, 0] = 0
        out.write_mask(mask)
with rasterio.open(path) as src:
    assert src.read_masks(1)[0, 0] == 0
    assert path + ".msk" in src.files
'''
    candidate = source / "externally-masked.tif"
    engine_python(dialog, script, str(candidate))
    assert Path(str(candidate) + ".msk").is_file()
    original = project / "data" / "zones.tif"
    config = Path(dialog.config_manager.config_path)
    before_input, before_config = original.read_bytes(), config.read_bytes()
    dialog.mastergridFileWidget.setFilePath(str(candidate))
    assert dialog.import_controller.is_running
    wait_until(lambda: not dialog.import_controller.is_running)
    assert dialog.mastergridFileWidget.filePath() == str(original)
    assert original.read_bytes() == before_input
    assert config.read_bytes() == before_config
    assert not (project / "data" / candidate.name).exists()
    assert "external mask or metadata" in dialog.console_handler.console_text.toPlainText()


def test_native_completed_history_loads_real_qgis_raster_provider(native_dialog, tmp_path):
    from qgis.core import QgsProject, QgsRasterLayer
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    controller = dialog.process_executor
    controller.start_analysis()
    wait_until(lambda: not controller.is_running)
    loaded = []
    class NativeIface:
        def addRasterLayer(self, path, name):
            layer = QgsRasterLayer(path, name)
            assert layer.isValid()
            QgsProject.instance().addMapLayer(layer)
            loaded.append(layer.id())
            return layer
    dialog.iface = NativeIface()
    item = dialog.resultsTree.topLevelItem(0)
    assert item is not None
    dialog.resultsTree.setCurrentItem(item)
    assert dialog.addRunLayersButton.isEnabled()
    try:
        dialog._add_selected_run()
        assert len(loaded) == 1
        assert loaded[0] in QgsProject.instance().mapLayers()
    finally:
        QgsProject.instance().removeMapLayers(loaded)


def test_native_dark_palette_and_keyboard_access(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    original = QApplication.palette()
    dark = QPalette(original)
    role = QPalette.ColorRole
    for entry, color in ((role.Window, "#25272a"), (role.Base, "#1c1e21"),
                         (role.AlternateBase, "#303236"), (role.Button, "#34373b"),
                         (role.WindowText, "#f0f1f2"), (role.Text, "#f0f1f2"),
                         (role.ButtonText, "#f0f1f2"), (role.Highlight, "#537ab6"),
                         (role.HighlightedText, "#ffffff")):
        dark.setColor(entry, QColor(color))
    try:
        QApplication.setPalette(dark)
        dialog.show()
        dialog.mainTabWidget.setCurrentIndex(2)
        dialog.idColumnEdit.setFocus()
        QApplication.processEvents()
        assert dialog.idColumnEdit.hasFocus()
        QTest.keyClick(dialog.idColumnEdit, Qt.Key.Key_Tab)
        assert dialog.popColumnEdit.hasFocus()
        assert dialog.mainStartButton.shortcut().toString() == "Alt+R"
        assert dialog.console_handler.console_text.palette().color(role.Base) == QColor("#1c1e21")
        assert dialog.mainStartButton.minimumWidth() >= 130
        capture_state(dialog, "dark-settings", tab=2)
        dialog.logger.info("Plain text <tag> is displayed without rich-text interpretation.")
        assert "<tag>" in dialog.console_handler.console_text.toPlainText()
        capture_state(dialog, "dark-details", tab=4)
    finally:
        QApplication.setPalette(original)


def test_native_high_dpi_cold_host_render(native_package, native_dialog, tmp_path):
    alias, _ = native_package
    root = Path(sys.modules[alias].__path__[0])
    target = Path(os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR", str(tmp_path)))
    target.mkdir(parents=True, exist_ok=True)
    script = '''
import importlib, sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from qgis.testing import start_app
from qgis.PyQt.QtCore import QEventLoop, QTimer, QPoint
from qgis.PyQt.QtWidgets import QApplication
app = start_app()
package = ModuleType("high_dpi_plugin")
package.__path__ = [sys.argv[1]]
sys.modules[package.__name__] = package
manager_type = importlib.import_module("high_dpi_plugin.services.runtime_manager").RuntimeManager
manager = SimpleNamespace(get_python=lambda cancellation_token=None: Path(sys.argv[2]),
                          child_environment=manager_type.child_environment)
dialog_type = importlib.import_module("high_dpi_plugin.gui.dialogs.main_dialog").PyPopRFDialog
dialog = dialog_type(runtime_manager=manager, cache_root=Path(sys.argv[3]) / "cache")
loop = QEventLoop()
dialog.runtime_controller.completed.connect(loop.quit)
QTimer.singleShot(3000, loop.quit)
loop.exec()
assert not dialog.is_busy
dialog.resize(920, 720)
dialog.show()
dialog.mainTabWidget.setCurrentIndex(2)
QApplication.processEvents()
assert dialog.devicePixelRatioF() >= 1.4
position = dialog.mainStartButton.mapTo(dialog, QPoint(0, 0))
assert dialog.rect().contains(position)
assert dialog.grab().save(str(Path(sys.argv[3]) / "high-dpi-settings.png"))
dialog.logger.close()
dialog.close()
'''
    environment = dict(os.environ, QT_SCALE_FACTOR="1.5")
    subprocess.run([sys.executable, "-c", script, str(root), native_dialog.runtime_controller.python,
                    str(target)], env=environment, capture_output=True, text=True, timeout=30, check=True)


def test_native_unload_retains_owned_process_until_ended(native_dialog, native_package, tmp_path):
    alias, _ = native_package
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path, trees=300)
    plugin = importlib.import_module(alias + ".qgis_pypoprf").PyPopRF(SimpleNamespace())
    plugin.dlg = dialog
    dialog.process_executor.start_analysis()
    assert dialog.process_executor.is_running
    plugin.unload()
    assert plugin.dlg is dialog
    wait_until(lambda: plugin.dlg is None)
    assert not dialog.process_executor.is_running
