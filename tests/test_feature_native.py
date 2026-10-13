"""Actual QGIS preparation, tool ownership, layer UX and AOI acceptance."""
import importlib
import os
import warnings
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="Feature acceptance requires native QGIS")
pytestmark = pytest.mark.qgis

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer, QgsField
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QPoint, QRect, QProcess, QMetaType, QVariant
from test_qgis_native import (native_package as native_package, native_dialog as native_dialog, prepare_inputs,
                              engine_python, wait_until, capture_state)


def tool_request(project, source, operation="inspect"):
    return {"schema_version": 1, "operation": operation,
        "reference_raster": str(project / "data" / "zones.tif"),
        "zone_raster": str(project / "data" / "zones.tif"),
        "census": {"path": str(project / "data" / "census.csv"), "id_column": "id", "population_column": "pop"},
        "covariates": [{"name": "covariate", "path": str(project / "data" / "covariate.tif"),
                        "quantity": "continuous", "resampling": "bilinear"}], "tile_size": 16}


def polygon_file(dialog, path, xmax=80):
    script = '''
import sys
import geopandas as gpd
from shapely.geometry import box
gpd.GeoDataFrame({"zone": [1]}, geometry=[box(0, 80, float(sys.argv[2]), 100)], crs="EPSG:3857").to_file(
    sys.argv[1], driver="GeoJSON")
'''
    engine_python(dialog, script, str(path), str(xmax))
    return path


def finish_analysis(dialog):
    dialog.process_executor.start_analysis()
    wait_until(lambda: not dialog.process_executor.is_running)
    assert dialog.process_executor.last_result_paths, dialog.process_executor._stderr
    return dialog.process_executor.last_run_dir


def test_native_tools_inspect_and_wizard_prepare_require_explicit_open(native_dialog, tmp_path):
    dialog = native_dialog
    project, source = prepare_inputs(dialog, tmp_path)
    old_config = Path(dialog.config_manager.config_path)
    old_bytes = old_config.read_bytes()
    source_bytes = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    dialog._open_preparation()
    wizard = dialog._preparation_window
    wizard.outputEdit.setText(str(tmp_path / "standalone-prepared"))
    wizard.show()
    for _ in range(3):
        wizard.next()
    assert wizard.currentPage() is wizard.reviewPage
    wizard.inspect()
    assert dialog.tools_controller.is_running and dialog.is_busy
    wait_until(lambda: not dialog.tools_controller.is_running)
    assert wizard._ready, wizard.reportView.toPlainText()
    assert wizard.progress.value() == 100 and wizard.progress.format() == "Compatibility check complete"
    assert old_config.read_bytes() == old_bytes
    wizard.confirm.setChecked(True)
    finish = wizard.button(QtWidgets.QWizard.WizardButton.FinishButton)
    assert finish.isEnabled()
    finish.click()
    wait_until(lambda: not dialog.tools_controller.is_running)
    prepared = wizard._prepared_project
    assert prepared is not None, wizard.reportView.toPlainText()
    assert wizard.progress.value() == 100 and wizard.progress.format() == "Prepared project created"
    assert (prepared / "config.yaml").is_file()
    assert Path(dialog.config_manager.config_path) == old_config  # Prepare is not Open.
    assert old_config.read_bytes() == old_bytes
    assert {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()} == source_bytes
    capture_state(dialog, "feature-current-project-preserved", tab=1)
    QtWidgets.QApplication.processEvents()
    for control in (wizard.confirm, finish,
                    wizard.button(QtWidgets.QWizard.WizardButton.BackButton),
                    wizard.button(QtWidgets.QWizard.WizardButton.CancelButton)):
        assert control.isVisible()
        rectangle = QRect(control.mapTo(wizard, QPoint(0, 0)), control.size())
        assert wizard.rect().contains(rectangle), (control.text(), rectangle, wizard.rect())
    assert not wizard.reportDetails.isVisible() and "Reference grid:" in wizard.reportView.toPlainText()
    wizard.detailsToggle.click()
    QtWidgets.QApplication.processEvents()
    assert wizard.reportDetails.isVisible()
    for control in (wizard.confirm, finish, wizard.button(QtWidgets.QWizard.WizardButton.CancelButton)):
        assert wizard.rect().contains(QRect(control.mapTo(wizard, QPoint(0, 0)), control.size()))
    wizard.detailsToggle.click()
    directory = __import__("os").environ.get("PYPOPRF_QGIS_ARTIFACT_DIR")
    if directory:
        assert wizard.grab().save(str(Path(directory) / "preparation-reviewed.png"))
    # Retargeting after a successful preparation must not open the old directory
    # while the UI displays the new one. Both already-created projects survive.
    first_prepared = prepared
    first_config = (first_prepared / "config.yaml").read_bytes()
    replacement = tmp_path / "prepared-retargeted"
    wizard.outputEdit.setText(str(replacement))
    assert wizard._prepared_project is None
    assert "Create prepared" in finish.text()
    finish.click()
    wait_until(lambda: not dialog.tools_controller.is_running)
    prepared = wizard._prepared_project
    assert prepared == replacement.resolve(), wizard.reportView.toPlainText()
    assert (first_prepared / "config.yaml").read_bytes() == first_config
    assert Path(dialog.config_manager.config_path) == old_config
    finish.click()
    assert dialog._project_ready and Path(dialog.config_manager.working_dir) == prepared
    assert old_config.read_bytes() == old_bytes
    dialog.config_manager.update_many({"n_estimators": 8, "cv_folds": 3, "cv_strategy": "shuffled_zone"})
    finish_analysis(dialog)


def test_native_reviewed_source_change_requires_reinspection(native_dialog, tmp_path):
    dialog = native_dialog
    project, _ = prepare_inputs(dialog, tmp_path)
    original_config = Path(dialog.config_manager.config_path).read_bytes()
    dialog._open_preparation()
    wizard = dialog._preparation_window
    output = tmp_path / "refused-changed-input"
    wizard.outputEdit.setText(str(output))
    for _ in range(3):
        wizard.next()
    wizard.inspect()
    wait_until(lambda: not dialog.tools_controller.is_running)
    assert wizard._ready and wizard._expected_inputs
    census = project / "data" / "census.csv"
    census.write_text(census.read_text().replace("1,40", "1,41"))
    changed_bytes = census.read_bytes()
    wizard.confirm.setChecked(True)
    wizard.button(QtWidgets.QWizard.WizardButton.FinishButton).click()
    wait_until(lambda: not dialog.tools_controller.is_running)
    assert not wizard._ready and wizard._prepared_project is None
    assert wizard.progress.value() == 0 and "did not complete" in wizard.progress.format()
    assert "inspect again" in wizard.reportView.toPlainText().lower()
    assert not output.exists()
    assert census.read_bytes() == changed_bytes
    assert Path(dialog.config_manager.config_path).read_bytes() == original_config
    wizard.reject()


def test_native_wizard_headers_are_plain_text_and_constructor_failure_is_contained(
        native_dialog, native_package, tmp_path, monkeypatch):
    alias, _ = native_package
    dialog = native_dialog
    dialog._open_preparation()
    wizard = dialog._preparation_window
    csv = tmp_path / "literal.csv"
    csv.write_text("<b>id</b>,pop\n1,10\n")
    wizard.census.edit.setText(str(csv))
    from qgis.PyQt.QtCore import Qt
    assert wizard.columnMessage.textFormat() == Qt.TextFormat.PlainText
    assert "<b>id</b>" in wizard.columnMessage.text()
    wizard.reject()
    module = importlib.import_module(alias + ".qgis_pypoprf_dialog")
    def failure(dialog):
        raise OSError("injected constructor failure")
    monkeypatch.setattr(module, "PreparationWizard", failure)
    dialog._open_preparation()
    assert dialog._preparation_window is None and not dialog.is_busy
    assert "injected constructor failure" in dialog.console_handler.console_text.toPlainText()


def test_native_inspect_reports_unsafe_count_warp_without_current_project_changes(native_dialog, tmp_path):
    dialog = native_dialog
    project, source = prepare_inputs(dialog, tmp_path)
    candidate = source / "unaligned-count.tif"
    script = '''
import sys, numpy as np, rasterio
from rasterio.transform import from_origin
with rasterio.open(sys.argv[1], "w", driver="GTiff", width=4, height=2, count=1,
    dtype="float32", crs="EPSG:3857", transform=from_origin(0,100,20,20)) as out:
    out.write(np.ones((2,4),dtype="float32"),1)
'''
    engine_python(dialog, script, str(candidate))
    before = Path(dialog.config_manager.config_path).read_bytes()
    request = tool_request(project, source)
    request["covariates"][0].update(path=str(candidate), quantity="count", resampling="nearest")
    results = []
    dialog.tools_controller.resultReady.connect(results.append)
    assert dialog.tools_controller.start(request)
    wait_until(lambda: not dialog.tools_controller.is_running)
    assert results[-1]["success"] and results[-1]["report"]["ready"] is False
    assert any(item["code"] == "count_resampling" for item in results[-1]["report"]["errors"])
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    assert candidate.is_file()


def test_native_grouped_outputs_are_styled_deduplicated_and_quality_is_scrollable(native_dialog, tmp_path):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    project = QgsProject.instance()
    before_ids = set(project.mapLayers())
    added = []
    class NativeIface:
        def addRasterLayer(self, path, name):
            layer = QgsRasterLayer(path, name)
            assert layer.isValid()
            project.addMapLayer(layer)
            added.append(layer.id())
            return layer
    dialog.iface = NativeIface()
    dialog.process_executor.iface = dialog.iface
    dialog.addToQgisCheckBox.setChecked(True)
    try:
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always", DeprecationWarning)
            root = finish_analysis(dialog)
        assert not [warning for warning in emitted if issubclass(warning.category, DeprecationWarning)
                    and "layer_integration" in warning.filename]
        assert len(added) == 1
        layer = project.mapLayer(added[0])
        assert layer.customProperty("pypoprf/units") == "persons_per_pixel"
        assert layer.renderer().type() == "singlebandpseudocolor"
        assert "do not alter raster values" in layer.metadata().abstract()
        group = project.layerTreeRoot().findGroup("pypopRF")
        assert group and group.findLayer(layer.id())
        item = dialog.resultsTree.topLevelItem(0)
        dialog.resultsTree.setCurrentItem(item)
        dialog._add_selected_run()
        assert len(added) == 1
        repointed = Path(dialog.config_manager.working_dir) / "data" / "covariate.tif"
        layer.setDataSource(str(repointed), "User-repointed layer", "gdal")
        dialog._add_selected_run()
        assert len(added) == 2  # A stale property is not proof of the same source.
        assert Path(layer.source()).resolve() == repointed.resolve()
        assert dialog.quality_panel.report.run_dir == root.resolve()
        assert dialog.quality_panel.report.points
        assert any(isinstance(parent, QtWidgets.QScrollArea) for parent in
                   (dialog.quality_panel.parent(), dialog.quality_panel.parent().parent()))
        capture_state(dialog, "feature-quality-populated", tab=3)
    finally:
        project.removeMapLayers(list(set(project.mapLayers()) - before_ids))


def test_native_layer_sources_refuse_filtered_selected_and_editing_vectors(native_dialog, native_package, tmp_path, monkeypatch):
    alias, _ = native_package
    integration = importlib.import_module(alias + ".q_models.layer_integration")
    file = polygon_file(native_dialog, tmp_path / "aoi.geojson")
    layer = QgsVectorLayer(str(file), "AOI", "ogr")
    assert layer.isValid()
    assert integration.local_layer_source(layer, "vector")["path"] == str(file.resolve())
    feature = next(layer.getFeatures())
    layer.selectByIds([feature.id()])
    with pytest.raises(ValueError, match="selected"):
        integration.local_layer_source(layer, "vector")
    layer.removeSelection()
    assert layer.setSubsetString('"zone" = 1')
    with pytest.raises(ValueError, match="filtered"):
        integration.local_layer_source(layer, "vector")
    layer.setSubsetString("")
    assert layer.startEditing()
    with pytest.raises(ValueError, match="editing"):
        integration.local_layer_source(layer, "vector")
    layer.rollBack()
    memory = QgsVectorLayer("Polygon?crs=EPSG:3857", "Unsaved memory", "memory")
    with pytest.raises(ValueError, match="Export"):
        integration.local_layer_source(memory, "vector")
    # Identical layer names and source basenames must never select the first by
    # an ambiguous UI label when the user explicitly chooses another record.
    duplicate = QgsVectorLayer(str(file), layer.name(), "ogr")
    project = QgsProject.instance()
    project.addMapLayer(layer, False)
    project.addMapLayer(duplicate, False)
    records = integration.project_layer_sources("vector")
    labels = []
    def choose_second(parent, title, caption, items, *args):
        labels.extend(items)
        return items[1], True
    monkeypatch.setattr(integration.QInputDialog, "getItem", choose_second)
    try:
        chosen = integration.choose_project_layer(native_dialog, "vector")
        assert len(labels) == len(set(labels)) == 2
        assert chosen["id"] == records[1]["id"]
    finally:
        project.removeMapLayers([layer.id(), duplicate.id()])


def test_native_centroid_selection_updates_same_owned_layer_honestly(native_dialog, tmp_path):
    project = QgsProject.instance()
    before_ids = set(project.mapLayers())
    payload = {"run_dir": str(tmp_path / "run"), "crs": "EPSG:3857", "zone_ids": [1],
        "centroids": [{"zone_id": 1, "x": 10, "y": 90}, {"zone_id": 2, "x": 60, "y": 90}]}
    try:
        first = native_dialog.layer_integration.show_zone_centroids(payload)
        assert [int(feature["zone_id"]) for feature in first.getFeatures()] == [1]
        payload["zone_ids"] = [2]
        second = native_dialog.layer_integration.show_zone_centroids(payload)
        assert second.id() == first.id()
        assert [int(feature["zone_id"]) for feature in second.getFeatures()] == [2]
        assert "not predicted error locations" in second.metadata().abstract()
        assert "zone validation only" in second.name()
        try:
            string_type = QMetaType.Type.QString
        except AttributeError:
            string_type = QVariant.String
        assert second.dataProvider().addAttributes([QgsField("user_note", string_type)])
        second.updateFields()
        assert "user_note" in second.fields().names()
        third = native_dialog.layer_integration.show_zone_centroids(payload)
        assert third.id() != second.id() and "user_note" in second.fields().names()
        file = polygon_file(native_dialog, tmp_path / "tagged-user-aoi.geojson")
        foreign = QgsVectorLayer(str(file), "User's physical file with copied diagnostic tags", "ogr")
        foreign.setCustomProperty("pypoprf/run_dir", str(Path(payload["run_dir"]).resolve()))
        foreign.setCustomProperty("pypoprf/diagnostic", "zone_cv_centroids")
        project.addMapLayer(foreign, False)
        original_bytes = file.read_bytes()
        fresh_integration = native_dialog.layer_integration.__class__(native_dialog.logger)
        new_memory = fresh_integration.show_zone_centroids(payload)
        assert new_memory.providerType() == "memory" and new_memory.id() != foreign.id()
        assert foreign.featureCount() == 1 and file.read_bytes() == original_bytes
    finally:
        project.removeMapLayers(list(set(project.mapLayers()) - before_ids))


@pytest.mark.parametrize("xmax,partial", [(80, False), (160, True)])
def test_native_population_summary_declares_cell_centers_and_partial_coverage(native_dialog, tmp_path, xmax, partial):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    finish_analysis(dialog)
    dialog.resultsTree.setCurrentItem(dialog.resultsTree.topLevelItem(0))
    dialog._open_population_summary()
    window = dialog._summary_window
    aoi = polygon_file(dialog, tmp_path / "summary-area.geojson", xmax)
    window.aoi.edit.setText(str(aoi))
    if not partial:
        # Numeric OGR layerid must resolve to the selected table, never the
        # first GPKG table (which covers twice the area in this fixture).
        package = tmp_path / "two-areas.gpkg"
        script = '''
import sys, geopandas as gpd
from shapely.geometry import box
for name, geometry in (("first", box(0,60,80,100)), ("second",box(0,80,80,100))):
    gpd.GeoDataFrame({"zone":[1]},geometry=[geometry],crs="EPSG:3857").to_file(sys.argv[1],layer=name,driver="GPKG")
'''
        engine_python(dialog, script, str(package))
        selected = QgsVectorLayer(str(package) + "|layerid=1", "AOI renamed by user", "ogr")
        record = __import__(dialog.layer_integration.__class__.__module__, fromlist=["local_layer_source"]).local_layer_source(selected, "vector")
        assert record["layer"] == "second"
        window.aoi.edit.setText(record["path"])
        window.aoi.layer_name = record["layer"]
    window.start()
    assert dialog.is_busy and not window.calculate.isEnabled()
    wait_until(lambda: not dialog.tools_controller.is_running)
    text = window.summary.toPlainText()
    assert "400 persons" in text, text
    assert "cell centers inside or on" in text
    assert ("PARTIAL COVERAGE" in text) is partial
    assert window.progress.value() == 100 and "Summary complete" in window.progress.format()
    assert ("partial coverage" in window.progress.format()) is partial
    window.reject()


def test_native_summary_refuses_completed_map_changed_after_window_opened(native_dialog, tmp_path):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    finish_analysis(dialog)
    dialog.resultsTree.setCurrentItem(dialog.resultsTree.topLevelItem(0))
    dialog._open_population_summary()
    window = dialog._summary_window
    assert window._selected_hash()
    window.aoi.edit.setText(str(polygon_file(dialog, tmp_path / "aoi.geojson")))
    path = Path(window.population.currentData())
    engine_python(dialog, '''
import sys, rasterio
with rasterio.open(sys.argv[1],"r+") as out:
    values=out.read(1)
    values[0,0]+=1
    out.write(values,1)
''', str(path))
    window.start()
    wait_until(lambda: not dialog.tools_controller.is_running)
    text = window.summary.toPlainText().lower()
    assert "fingerprint" in text or "sha256" in text or "sha-256" in text or "completed run" in text, text
    assert "estimated population" not in text
    assert window.progress.value() == 0 and window.progress.format() == "Summary did not complete"
    window.reject()


def test_native_close_cancels_owned_tools_without_switching_or_destroying_sources(native_dialog, tmp_path):
    dialog = native_dialog
    project, source = prepare_inputs(dialog, tmp_path)
    before = Path(dialog.config_manager.config_path).read_bytes()
    output = tmp_path / "cancelled-project"
    request = tool_request(project, source, "prepare")
    request["output_dir"] = str(output)
    results = []
    dialog.tools_controller.resultReady.connect(results.append)
    dialog.show()
    assert dialog.tools_controller.start(request)
    owned = dialog.tools_controller.process
    dialog.close()
    assert dialog._close_pending and dialog.tools_controller.process is owned
    wait_until(lambda: not dialog.is_busy)
    assert results[-1]["cancelled"] and not results[-1]["success"]
    assert not dialog.isVisible()
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    assert not (output / "config.yaml").exists()
    assert not list(dialog.job_cache.iterdir())


@pytest.mark.parametrize("kind", ["analysis", "tools"])
def test_native_forced_stop_waits_for_actual_managed_interpreter_before_cleanup(
        native_dialog, native_package, tmp_path, monkeypatch, kind):
    alias, _ = native_package
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    name = "process_executor" if kind == "analysis" else "tools_controller"
    module = importlib.import_module(alias + ".q_models." + name)
    # A genuine managed interpreter deliberately ignores the marker. On Windows
    # its venv launcher and its base Python have different, separately held PIDs.
    script = '''
import json, os, sys, time
from pathlib import Path
kind, request = sys.argv[1:3]
if kind == "analysis":
    output = Path(sys.argv[3]); nonce = None
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps({"schema_version":1,"status":"running",
        "config":str(Path(request).resolve()),"outputs":[]}))
    scratch=output / "grids-ignored-marker"; scratch.mkdir()
    (scratch / "source.tif").write_bytes(b"owned scratch must remain until actual exit")
else:
    document=json.loads(Path(request).read_text()); nonce=document["request_id"]
    output=Path(document["output_dir"]); output.mkdir(parents=True)
    (output / "report.json").write_text(json.dumps({"status":"running"}))
print(json.dumps({"event":"progress","percent":10,"message":"base_pid="+str(os.getpid()),
                  "request_id":nonce}),flush=True)
while True:
    time.sleep(0.05)
'''
    class IgnoredMarkerProcess(QProcess):
        def setArguments(self, arguments):
            field = "--config" if kind == "analysis" else "--request"
            request = arguments[arguments.index(field) + 1]
            output = arguments[arguments.index("--output-dir") + 1] if kind == "analysis" else "unused"
            super().setArguments(["-X", "utf8", "-c", script, kind, request, output])
    monkeypatch.setattr(module, "QProcess", IgnoredMarkerProcess)
    controller = dialog.process_executor if kind == "analysis" else dialog.tools_controller
    pids = []
    def record_pid(percent, message):
        if message.startswith("base_pid="):
            pids.append(int(message.split("=", 1)[1]))
    if kind == "analysis":
        original = controller.update_progress
        def progress(percent, message):
            record_pid(percent, message)
            original(percent, message)
        monkeypatch.setattr(controller, "update_progress", progress)
        controller.start_analysis()
    else:
        controller.progress.connect(record_pid)
        assert controller.start({"operation": "inspect"})
    wait_until(lambda: bool(pids))
    owned, guard = controller.process, controller._exit_guard
    assert owned is not None and guard is not None
    guard.exited()  # Capture the now-started base interpreter before termination.
    held = guard._api.open(pids[0]) if os.name == "nt" else None
    if os.name == "nt":
        assert held is not None
    job = Path(controller._job.name)
    finished_observations, completion_observations = [], []
    def actual_dead():
        if held is not None:
            return guard._api.signaled(held)
        try:
            os.kill(pids[0], 0)  # Read-only liveness check, never a kill by PID.
            return False
        except ProcessLookupError:
            return True
    def qt_finished(code, status):
        if not actual_dead():
            assert controller.is_running and job.exists()
            finished_observations.append("child alive, cache retained")
    def completed():
        completion_observations.append((actual_dead(), job.exists()))
    owned.finished.connect(qt_finished)
    controller.completed.connect(completed)
    try:
        if kind == "analysis":
            controller.stop_analysis()
            controller._force_stop(owned)
        else:
            controller.stop()
            controller._force_stop(owned)
        wait_until(lambda: not controller.is_running)
        assert completion_observations == [(True, False)]
        if kind == "analysis":
            manifest = __import__("json").loads((controller.last_run_dir / "manifest.json").read_text())
            assert manifest["status"] == "cancelled"
            assert not (controller.last_run_dir / "grids-ignored-marker").exists()
    finally:
        if held is not None:
            guard._api.close(held)
