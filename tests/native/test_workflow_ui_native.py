"""Native readiness, plain task status and persisted result selection contracts."""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="Workflow presentation needs native Qt/QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              initialize, prepare_inputs, capture_state)


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows redirected cache junction")
def test_redirected_cache_is_canonical_before_freezing_jobs(native_package, tmp_path):
    import importlib
    import subprocess
    from qgis.PyQt import sip
    from .test_qgis_native import PreparedRuntime, wait_until
    actual = tmp_path / "actual-cache"
    actual.mkdir()
    (actual / "canary").write_bytes(b"existing cache content")
    alias = tmp_path / "cache-alias"
    assert actual.is_relative_to(tmp_path) and alias.is_relative_to(tmp_path)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(actual)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    package, _ = native_package
    dialog_type = importlib.import_module(package + ".gui.dialogs.main_dialog").PyPopRFDialog
    dialog = dialog_type(runtime_manager=PreparedRuntime(package), cache_root=alias)
    try:
        wait_until(lambda: not dialog.runtime_controller.is_running)
        assert dialog.job_cache == actual / "pypoprf" / "jobs"
        assert not any(path.is_junction() for path in (dialog.job_cache, *dialog.job_cache.parents))
        assert (actual / "canary").read_bytes() == b"existing cache content"
    finally:
        dialog.dispose_when_idle()
        wait_until(lambda: sip.isdeleted(dialog))


def test_readiness_navigation_tracks_active_project_not_folder_selection(native_dialog, tmp_path):
    dialog = native_dialog
    assert dialog.engineReadyButton.accessibleName() == "Engine: ready"
    assert dialog.mainProgressBar.isHidden()  # Explicit idle visibility, not parent visibility.
    assert not dialog.mainStartButton.isEnabled()
    assert all(not icon.isNull() for icon in dialog._readiness_icons.values())
    initialize(dialog, tmp_path / "ready-project")
    assert dialog.projectReadyButton.accessibleName() == "Project: ready"
    assert dialog.zoneGridReadyButton.accessibleName() == "Zone grid: needed"
    assert "Run still checks" in dialog.zoneGridReadyButton.toolTip()
    dialog.zoneGridReadyButton.click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_inputs
    dialog.engineReadyButton.click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_main
    dialog.workingDirEdit.setFilePath(str(tmp_path / "unopened-project"))
    assert dialog.projectReadyButton.accessibleName() == "Project: needed"
    assert not dialog.mainStartButton.isEnabled()


def test_documentation_workflow_uses_real_synthetic_inputs(native_dialog, tmp_path):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path / "demonstration")
    assert dialog.mainStartButton.isEnabled()
    assert all("ready" in button.accessibleName() for button in dialog.readiness_buttons.values())
    assert dialog.mainProgressBar.isHidden()
    capture_state(dialog, "documentation-workflow", tab=1)


@pytest.mark.parametrize("alias_kind", ["directory", "hardlink"])
def test_logger_switch_rechecks_redirected_output_without_closing_healthy_log(native_package, tmp_path, alias_kind):
    import importlib
    from qgis.PyQt import QtWidgets
    alias, _ = native_package
    console_type = importlib.import_module(alias + ".gui.widgets.console_handler").ConsoleHandler
    project, protected = tmp_path / "external-project", tmp_path / "fake-installed-plugin"
    project.mkdir()
    protected.mkdir()
    (protected / "canary").write_bytes(b"preserve protected folder")
    window = QtWidgets.QWidget()
    console = console_type(window, {"plugin_root": protected})
    try:
        console.update_logging_settings("INFO", True, work_dir=project, filename="healthy.log")
        old_handler = console.logger.file_handler
        redirected = tmp_path / "redirected-project"
        redirected.mkdir()
        old_output = redirected / "output"
        if alias_kind == "hardlink":
            old_output.mkdir()
            os.link(protected / "canary", old_output / "must-not-create.log")
        elif os.name == "nt":
            import subprocess
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(old_output), str(protected)],
                                    capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stderr
        else:
            old_output.symlink_to(protected, target_is_directory=True)
        with pytest.raises(ValueError):
            console.update_logging_settings("INFO", True, work_dir=redirected, filename="must-not-create.log")
        assert console.logger.file_handler is old_handler and not old_handler.stream.closed
        assert {p.name for p in protected.iterdir()} == {"canary"}
        assert (protected / "canary").read_bytes() == b"preserve protected folder"
    finally:
        console.logger.close()
        window.deleteLater()


def test_status_is_plain_bounded_and_failure_survives_readiness_refresh(native_dialog, tmp_path):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    dialog.set_task_status("Fitting <model> & checking 人口", 42)
    assert dialog.mainProgressBar.value() == 42 and dialog.mainProgressBar.format() == "%p%"
    assert not dialog.mainProgressBar.isHidden()
    assert dialog.statusLabel.textFormat() == Qt.TextFormat.PlainText
    error = "ValueError: census <id> is missing & unsupported 人口"
    dialog._tools_result({"success": False, "message": "Traceback\nframe one\nframe two\n" + error})
    assert error in dialog.statusLabel.text()
    dialog._refresh_readiness()
    assert error in dialog.statusLabel.text()
    dialog._processing_completed()
    assert dialog.mainProgressBar.isHidden()
    assert error in dialog.statusLabel.text()
    dialog._runtime_changed({"python": dialog.runtime_controller.python, "candidates": [], "error": error})
    assert "previous engine remains available" in dialog.statusLabel.text()
    assert error in dialog.statusLabel.text() and dialog.mainStartButton.isEnabled()
    dialog.set_task_status("<tag>" + "X" * 6000 + "\n" * 10)
    assert len(dialog.statusLabel.text()) <= 1000
    dialog.statusDetailsButton.click()
    assert dialog.mainTabWidget.currentWidget() is dialog.tab_details
    dialog.resize(720, 520)
    dialog.show()
    QApplication.processEvents()
    assert dialog.rect().contains(dialog.mainStartButton.mapTo(dialog, QPoint(0, 0)))
    capture_state(dialog, "workflow-long-error", tab=4)


def saved_run(root, name, status):
    directory = root / name
    directory.mkdir(parents=True)
    output = directory / "population.tif"
    outputs = []
    if status == "complete":
        output.write_bytes(b"synthetic saved-history fixture, not loaded as raster")
        outputs = [output.name]
    (directory / "manifest.json").write_text(json.dumps({"schema_version": 1, "status": status,
                                                       "outputs": outputs}), encoding="utf-8")
    return directory


def test_history_preserves_selected_path_and_explicit_success_not_newest_failure(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "history-project")
    config = dialog.config_manager.get_config()
    runs = Path(dialog.config_manager.working_dir) / config["output_dir"] / "runs"
    first = saved_run(runs, "20261013T120000Z-aaaaaaaa", "complete")
    newest = saved_run(runs, "20261013T130000Z-bbbbbbbb", "complete")
    failed = saved_run(runs, "20261013T140000Z-cccccccc", "failed")
    dialog.refresh_results()
    assert dialog._selected_run() == newest
    selected = dialog.resultsTree.selectedItems()[0]
    assert selected.text(0) != newest.name and newest.name in selected.toolTip(0)
    dialog.refresh_results(select=first)
    assert dialog._selected_run() == first
    dialog.refresh_results()
    assert dialog._selected_run() == first
    for index in range(dialog.resultsTree.topLevelItemCount()):
        item = dialog.resultsTree.topLevelItem(index)
        if Path(item.data(0, Qt.ItemDataRole.UserRole)) == failed:
            dialog.resultsTree.setCurrentItem(item)
            break
    assert dialog._selected_run() == failed
    assert not dialog.addRunLayersButton.isEnabled() and not dialog.summarizePopulationButton.isEnabled()
    dialog.refresh_results()
    assert dialog._selected_run() == failed  # A deliberate diagnostic selection is preserved.
    dialog.refresh_results(select=newest)
    assert dialog._selected_run() == newest
