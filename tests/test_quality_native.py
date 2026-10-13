"""Genuine QGIS Qt5/Qt6 widget rendering, diagnostics and navigation signals."""
import importlib
import json
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

pytest.importorskip("qgis.core", reason="Native dashboard acceptance requires QGIS")
pytestmark = pytest.mark.qgis

from qgis.testing import start_app
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QSignalSpy, QTest
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication

from test_quality_report import fixture_run


@pytest.fixture(scope="module")
def quality_module():
    if os.name == "nt":
        os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"))
    app = start_app()
    alias = "native_quality_acceptance"
    package = ModuleType(alias)
    package.__path__ = [os.environ.get("PYPOPRF_TEST_PLUGIN_ROOT", str(Path(__file__).resolve().parents[1]))]
    sys.modules[alias] = package
    yield importlib.import_module(alias + ".q_models.quality_panel"), app
    for name in list(sys.modules):
        if name == alias or name.startswith(alias + "."):
            sys.modules.pop(name, None)


def test_native_quality_renders_oof_and_selected_zone_navigation(quality_module, tmp_path):
    module, _ = quality_module
    panel = module.QualityPanel()
    try:
        report = panel.load_run(fixture_run(tmp_path / "run"))
        panel.resize(1100, 850)
        panel.show()
        QApplication.processEvents()
        assert len(report.points) == panel.error_table.rowCount() == 4
        assert panel.feature_table.rowCount() == 2
        assert "training-mean baseline" in panel.metrics_label.text()
        assert "Engine-reported" in panel.conservation_label.text()
        assert not panel.grab().isNull()
        artifact_dir = os.environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
        if artifact_dir:
            destination = Path(artifact_dir)
            destination.mkdir(parents=True, exist_ok=True)
            assert panel.grab().save(str(destination / "quality-dashboard.png"))
        spy = QSignalSpy(panel.showZonesRequested)
        panel.error_table.selectRow(2)
        QTest.mouseClick(panel.show_zones_button, Qt.MouseButton.LeftButton)
        assert len(spy) == 1
        request = spy[0][0]
        assert request["zone_ids"] == [3]
        assert request["centroids"] == [{"zone_id": 3, "x": 30., "y": 60.}]
        assert request["crs"] == "EPSG:3857"
    finally:
        panel.close()
        panel.deleteLater()
        QApplication.processEvents()


def test_native_reload_invalid_or_empty_clears_stale_data_and_never_renders_html(quality_module, tmp_path):
    module, _ = quality_module
    panel = module.QualityPanel()
    try:
        run = fixture_run(tmp_path / "run", inventory=False)
        metrics_path = run / "cv_metrics.json"
        metrics = json.loads(metrics_path.read_text())
        metrics["scheme"] = "<b>literal strategy</b>"
        metrics["provenance"]["limitations"] = ["<img src='invalid'>literal limitation"]
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        panel.load_run(run)
        assert panel.status_label.textFormat() == Qt.TextFormat.PlainText
        assert "<b>literal strategy</b>" in panel.status_label.text()
        assert "<img" in panel.details.toPlainText()
        (run / "manifest.json").write_text("[]")
        panel.load_run(run)
        assert not panel.scatter.points and panel.error_table.rowCount() == panel.feature_table.rowCount() == 0
        assert not panel.show_zones_button.isEnabled()
        panel.load_run(None)
        assert panel.report.run_status == "not_selected"
        assert not panel.details.toPlainText()
    finally:
        panel.close()
        panel.deleteLater()
        QApplication.processEvents()


def test_native_failed_run_diagnostics_do_not_appear_as_verified_population(quality_module, tmp_path):
    module, _ = quality_module
    panel = module.QualityPanel()
    try:
        panel.load_run(fixture_run(tmp_path / "failed", status="failed"))
        assert panel.report.points
        assert "not established" in panel.conservation_label.text()
        assert "did not complete" in panel.details.toPlainText()
        # No centroid CRS is fabricated when geometry metadata is missing.
        path = tmp_path / "failed" / "cv_zone_geometry.csv"
        path.unlink()
        panel.load_run(tmp_path / "failed")
        spy = QSignalSpy(panel.showZonesRequested)
        panel._show_zones()
        assert spy[0][0]["zone_ids"] and spy[0][0]["centroids"] == []
        assert spy[0][0]["crs"] is None
    finally:
        panel.close()
        panel.deleteLater()
        QApplication.processEvents()


def test_native_scatter_large_values_compact_dark_palette_remains_renderable(quality_module):
    module, _ = quality_module
    point_type = importlib.import_module(module.__package__ + ".quality_report").ZonePoint
    chart = module.OOFScatter()
    try:
        palette = QPalette(chart.palette())
        palette.setColor(QPalette.ColorRole.Base, QColor("#20242a"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f4f6f8"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#52c7c0"))
        chart.setPalette(palette)
        chart.set_points(tuple(point_type(index, 1.79e308, 1.79e308, index % 2) for index in range(20000)))
        assert len(chart._plot_sample()) == chart.MAX_PLOT_POINTS
        assert chart._plot_sample()[0].zone_id == 0 and chart._plot_sample()[-1].zone_id == 19999
        chart.resize(550, 250)
        chart.show()
        QApplication.processEvents()
        assert not chart.grab().isNull()
        assert chart.palette().base().color().name() == "#20242a"
    finally:
        chart.close()
        chart.deleteLater()
        QApplication.processEvents()
