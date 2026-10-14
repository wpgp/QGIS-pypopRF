"""New project/preview/portable-integrity failure boundaries on real QGIS."""
import hashlib
import importlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="Additional adversarial UI cases require genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              initialize, wait_until, prepare_inputs)


def wizard_for(dialog, alias, tmp_path):
    module = importlib.import_module(alias + ".gui.dialogs.preparation_dialog")
    wizard = module.PreparationWizard(dialog)
    wizard.reference.edit.setText(str(tmp_path / "reference.tif"))
    wizard.census.edit.setText(str(tmp_path / "census.csv"))
    return wizard


@pytest.mark.parametrize("kind", ["census_data", "mastergrid", "covariate"])
def test_successful_project_switch_clears_only_previous_project_diagnostics(native_dialog, tmp_path, kind):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project-a")
    dialog.set_input_error(kind, "Specific error belonging to project A")
    label = dialog._input_errors[kind]
    before = Path(dialog.config_manager.config_path).read_bytes()
    dialog.init_project()  # Active re-selection is not a successful switch.
    assert label.text() == "Specific error belonging to project A"
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "config.yaml").write_text("logging: [broken\n", encoding="utf-8")
    dialog.workingDirEdit.setFilePath(str(broken))
    dialog.init_project()
    assert label.text() == "Specific error belonging to project A"
    initialize(dialog, tmp_path / "project-b")
    dialog.mainTabWidget.setCurrentWidget(dialog.tab_inputs)
    dialog.show()
    QApplication.processEvents()
    assert not label.text() and not label.isVisible()
    assert (tmp_path / "project-a/config.yaml").read_bytes() == before


def test_actual_failed_import_error_does_not_follow_next_project(native_dialog, tmp_path):
    initialize(native_dialog, tmp_path / "project-a")
    native_dialog.populationCensusFileWidget.setFilePath(str(tmp_path / "missing.csv"))
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog._input_errors["census_data"].text()
    initialize(native_dialog, tmp_path / "project-b")
    assert not native_dialog._input_errors["census_data"].text()


def test_real_controller_rejects_unavailable_engine_without_false_checking(native_dialog, native_package, tmp_path):
    dialog = native_dialog
    wizard = wizard_for(dialog, native_package[0], tmp_path)
    dialog.runtime_controller.python = None
    wizard.inspect()
    assert wizard._operation is None and not wizard._ready and not dialog.is_busy
    assert wizard._expected_inputs is None and wizard._checked is None
    assert wizard.progress.value() == 0 and "did not start" in wizard.progress.format()
    assert "Engine" in wizard.reportView.toPlainText()
    wizard.deleteLater()
    wait_until(lambda: sip.isdeleted(wizard))


def test_synchronous_snapshot_failure_keeps_precise_terminal_error(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    wizard = wizard_for(dialog, native_package[0], tmp_path)
    controller = importlib.import_module(native_package[0] + ".controllers.tools_controller")
    def unavailable(*args, **kwargs):
        raise OSError("Injected engine snapshot permission failure")
    monkeypatch.setattr(controller, "create_engine_snapshot", unavailable)
    wizard.inspect()
    assert wizard._operation is None and not dialog.is_busy
    assert "Injected engine snapshot permission failure" in wizard.reportView.toPlainText()
    assert "did not start" not in wizard.progress.format()
    assert not list(dialog.job_cache.glob("tools-*"))
    wizard.deleteLater()
    wait_until(lambda: sip.isdeleted(wizard))


@pytest.mark.parametrize("separator", ["/", "\\"])
@pytest.mark.parametrize("inventory", ["valid", "missing", "outside", "drive"])
def test_population_summary_reuses_only_contained_available_artifact_hash(native_dialog, tmp_path, monkeypatch, separator, inventory):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    run = tmp_path / "project/output/runs/legacy-run"
    target = run / "agesex/population_f0.tif"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic-GUI-map-transaction")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    name = f"agesex{separator}population_f0.tif"
    artifact_name = name if inventory == "valid" else "../outside.tif" if inventory == "outside" else "C:\\outside.tif"
    manifest = {"status": "complete", "outputs": [name], "artifacts": [] if inventory == "missing" else
                [{"path": artifact_name, "sha256": digest}]}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    dialog.refresh_results()
    dialog._open_population_summary()
    popup = dialog._summary_window
    assert popup is not None
    assert popup._selected_hash() == (digest if inventory == "valid" else None)
    assert ("will be verified" in popup.integrityCaption.text()) == (inventory == "valid")
    requests = []
    monkeypatch.setattr(dialog.tools_controller, "start", lambda request: requests.append(request) or False)
    popup.aoi.edit.setText(str(tmp_path / "aoi.geojson"))
    popup.start()
    assert requests[0].get("expected_population_sha256") == (digest if inventory == "valid" else None)
    popup.reject()
    QApplication.processEvents()


@pytest.mark.parametrize("contents,expected", [
    (b"zone_id,total,label\n" + b"1,12," + b"a" * (65536 - 19 - 5) + "\u0416".encode("utf-8") + b"\n", "CSV columns: zone_id, total, label"),
    (b'\xef\xbb\xbf"zone,id","total count"\n1,12\n', "CSV columns: zone,id, total count"),
    (b'"zone\nid",total\n1,12\n', "CSV columns: zone\nid, total"),
], ids=["utf8-body-boundary", "bom-quoted-columns", "multiline-quoted-header"])
def test_bounded_header_preview_handles_body_unicode_bom_and_custom_quoted_columns(native_dialog, native_package, tmp_path, contents, expected):
    wizard = wizard_for(native_dialog, native_package[0], tmp_path)
    source = tmp_path / "headers.csv"
    source.write_bytes(contents)
    wizard.census.edit.setText(str(source))
    assert wizard.columnMessage.text() == expected
    wizard.deleteLater()
    wait_until(lambda: sip.isdeleted(wizard))


@pytest.mark.parametrize("contents", [b"a" * 65537 + b"\n", b'"unfinished header'],
                         ids=["oversized-header", "unfinished-quote"])
def test_header_limit_and_malformed_quotes_remain_visible_errors(native_dialog, native_package, tmp_path, contents):
    wizard = wizard_for(native_dialog, native_package[0], tmp_path)
    source = tmp_path / "headers.csv"
    source.write_bytes(contents)
    wizard.census.edit.setText(str(source))
    assert "Could not preview the CSV header" in wizard.columnMessage.text()
    wizard.deleteLater()
    wait_until(lambda: sip.isdeleted(wizard))


def test_preparation_escape_before_work_preserves_project_and_reopens_cleanly(native_dialog, tmp_path):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    before = Path(dialog.config_manager.config_path).read_bytes()
    dialog._open_preparation()
    first = dialog._preparation_window
    QApplication.processEvents()
    QTest.keyClick(first, Qt.Key.Key_Escape)
    wait_until(lambda: dialog._preparation_window is None)
    assert not dialog.is_busy and dialog._project_ready
    dialog._open_preparation()
    second = dialog._preparation_window
    assert second is not first and second._operation is None
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    second.reject()
    QApplication.processEvents()


def test_real_busy_runtime_rejection_has_truthful_idle_wizard_state(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    wizard = wizard_for(dialog, native_package[0], tmp_path)
    entered, release = threading.Event(), threading.Event()
    def held_health(cancellation_token=None):
        entered.set()
        while not release.is_set():
            cancellation_token.check()
            time.sleep(0.005)
        return dialog.runtime_controller.manager.path
    monkeypatch.setattr(dialog.runtime_controller.manager, "get_python", held_health)
    dialog.runtime_controller.check()
    wait_until(entered.is_set)
    try:
        assert dialog.is_busy and not dialog.tools_controller.is_running
        wizard.inspect()  # Actual ToolsController refuses another owned task.
        assert wizard._operation is None and not wizard._ready
        assert "Another task" in wizard.reportView.toPlainText()
    finally:
        release.set()
        wait_until(lambda: not dialog.is_busy)
        wizard.deleteLater()
        wait_until(lambda: sip.isdeleted(wizard))


def test_actual_qprocess_failed_start_then_retry_restores_controls(native_dialog, native_package, tmp_path):
    dialog = native_dialog
    prepare_inputs(dialog, tmp_path)
    module = importlib.import_module(native_package[0] + ".gui.dialogs.preparation_dialog")
    wizard = module.PreparationWizard(dialog)
    real_python = dialog.runtime_controller.python
    dialog.runtime_controller.python = tmp_path / "missing-python"
    wizard.inspect()
    wait_until(lambda: not dialog.is_busy and wizard._operation is None)
    assert not wizard._ready and wizard.progress.value() == 0
    message = wizard.reportView.toPlainText().casefold()
    assert "failed to start" in message or "could not start" in message or "no such" in message
    assert not list(dialog.job_cache.glob("tools-*"))
    # Real engine retry reaches validation, not a stale FailedToStart callback.
    dialog.runtime_controller.python = real_python
    wizard.inspect()
    wait_until(lambda: not dialog.is_busy and wizard._operation is None)
    assert "Inputs are compatible" in wizard.reportView.toPlainText()
    assert wizard.progress.value() == 100 and wizard._ready
    assert not list(dialog.job_cache.glob("tools-*"))
    wizard.deleteLater()
    wait_until(lambda: sip.isdeleted(wizard))


def test_navigation_and_escape_during_real_inspection_preserve_project_and_sources(native_dialog, tmp_path):
    dialog = native_dialog
    project, source = prepare_inputs(dialog, tmp_path)
    config_before = (project / "config.yaml").read_bytes()
    sources_before = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    dialog._open_preparation()
    wizard = dialog._preparation_window
    for _ in range(3):
        wizard.next()
    wizard.show()
    QApplication.processEvents()
    original_page = wizard.currentId()
    wizard.inspect()
    assert dialog.is_busy and dialog.tools_controller.is_running
    assert not wizard.reference.isEnabled() and not wizard.covariates.isEnabled()
    back = wizard.button(wizard.WizardButton.BackButton)
    assert not back.isEnabled()
    QTest.mouseClick(back, Qt.MouseButton.LeftButton)
    assert wizard.currentId() == original_page
    QTest.keyClick(wizard, Qt.Key.Key_Escape)
    wait_until(lambda: not dialog.is_busy and dialog._preparation_window is None)
    assert (project / "config.yaml").read_bytes() == config_before
    assert sources_before == {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    assert not list(dialog.job_cache.glob("tools-*"))
    dialog._open_preparation()
    reopened = dialog._preparation_window
    assert reopened is not wizard and reopened._operation is None and not reopened._ready
    reopened.reject()
    QApplication.processEvents()


@pytest.mark.parametrize("failure", ["lock", "write"])
def test_covariate_registration_failure_never_exposes_phantom_and_retry_works(native_dialog, tmp_path, monkeypatch, failure):
    dialog = native_dialog
    project = tmp_path / "project"
    initialize(dialog, project)
    source = tmp_path / "predictor.tif"
    source.write_bytes(b"owned-import-transaction-fixture")
    before = Path(dialog.config_manager.config_path).read_bytes()
    if failure == "lock":
        with dialog.config_manager._mutation_lock():
            dialog._begin_import([str(source)], "covariate")
            wait_until(lambda: not dialog.is_busy)
    else:
        original_write = dialog.config_manager._write_config
        def cannot_write(config):
            raise OSError("Injected configuration disk-full failure")
        monkeypatch.setattr(dialog.config_manager, "_write_config", cannot_write)
        dialog._begin_import([str(source)], "covariate")
        wait_until(lambda: not dialog.is_busy)
        monkeypatch.setattr(dialog.config_manager, "_write_config", original_write)
    assert dialog.covariatesTable.rowCount() == 0
    assert dialog.config_manager.get_config()["covariates"] == {}
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    retained = project / "data" / source.name
    assert retained.read_bytes() == source.read_bytes()
    dialog._begin_import([str(retained)], "covariate")
    wait_until(lambda: not dialog.is_busy)
    assert dialog.config_manager.get_config()["covariates"] == {"predictor": source.name}
    assert dialog.covariatesTable.rowCount() == 1 and dialog.covariatesTable.item(0, 0).text() == "predictor"


def test_covariate_partial_registration_preserves_earlier_success(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    paths = [tmp_path / "first.tif", tmp_path / "second.tif"]
    for path in paths:
        path.write_bytes(b"owned-partial-import-fixture")
    original = dialog.config_manager.update_config
    def write_first_only(key, value):
        if key == "covariate_second":
            raise OSError("Injected second registration failure")
        return original(key, value)
    monkeypatch.setattr(dialog.config_manager, "update_config", write_first_only)
    dialog._begin_import([str(path) for path in paths], "covariate")
    wait_until(lambda: not dialog.is_busy)
    assert dialog.config_manager.get_config()["covariates"] == {"first": "first.tif"}
    assert dialog.covariatesTable.rowCount() == 1 and dialog.covariatesTable.item(0, 0).text() == "first"
    assert all((tmp_path / "project/data" / path.name).read_bytes() == path.read_bytes() for path in paths)


def test_post_commit_ui_failure_rebuilds_from_canonical_config_without_undo(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    source = tmp_path / "predictor.tif"
    source.write_bytes(b"owned-postcommit-ui-fixture")
    original = dialog.covariatesTable.setItem
    attempted = []
    def fail_once(*args):
        if not attempted:
            attempted.append(True)
            raise RuntimeError("Injected one-time Qt row failure")
        return original(*args)
    monkeypatch.setattr(dialog.covariatesTable, "setItem", fail_once)
    dialog._begin_import([str(source)], "covariate")
    wait_until(lambda: not dialog.is_busy)
    assert attempted == [True]
    assert dialog.config_manager.get_config()["covariates"] == {"predictor": source.name}
    assert dialog.covariatesTable.rowCount() == 1 and dialog.covariatesTable.item(0, 0).text() == "predictor"


@pytest.mark.parametrize("damage", ["missing", "malformed", "traversal", "drive", "empty", "prediction-only"])
def test_damaged_history_is_invalid_and_cannot_trigger_actions_or_read_artifacts(native_dialog, native_package, tmp_path, monkeypatch, damage):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    run = tmp_path / "project/output/runs/damaged"
    run.mkdir(parents=True)
    (run / "prediction.tif").write_bytes(b"not-a-population-map")
    names = {"missing": ["missing.tif"], "traversal": ["../outside.tif"],
             "drive": ["C:\\outside.tif"], "empty": [], "prediction-only": ["prediction.tif"]}
    manifest = "{broken" if damage == "malformed" else json.dumps({"status": "complete", "outputs": names[damage]})
    (run / "manifest.json").write_text(manifest, encoding="utf-8")
    requests = []
    presenter = importlib.import_module(native_package[0] + ".gui.presenters.results_presenter")
    monkeypatch.setattr(presenter, "open_folder", lambda path: requests.append(("folder", Path(path).resolve())))
    monkeypatch.setattr(dialog.layer_integration, "add_run", lambda *args: requests.append("maps"))
    monkeypatch.setattr(dialog.tools_controller, "start", lambda *args: requests.append("summary"))
    report_loads = []
    load = dialog.quality_panel.load_run
    def observe_load(path):
        report_loads.append(path)
        return load(path)
    monkeypatch.setattr(dialog.quality_panel, "load_run", observe_load)
    dialog.refresh_results()
    assert dialog.resultsTree.topLevelItemCount() == 1
    item = dialog.resultsTree.topLevelItem(0)
    assert item.text(1) == "Invalid" and item.text(2) == "0"
    dialog.resultsTree.setCurrentItem(item)
    QApplication.processEvents()
    assert dialog.openRunButton.isEnabled() and not dialog.addRunLayersButton.isEnabled()
    assert not dialog.summarizePopulationButton.isEnabled()
    assert report_loads and all(path is None for path in report_loads)
    for button in (dialog.openRunButton, dialog.addRunLayersButton, dialog.summarizePopulationButton):
        button.click()
    assert requests == [("folder", run.resolve())]


def test_linked_history_run_directory_is_not_opened_or_listed(native_dialog, tmp_path):
    initialize(native_dialog, tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{broken", encoding="utf-8")
    runs = tmp_path / "project/output/runs"
    runs.mkdir(parents=True)
    alias = runs / "linked"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink privilege unavailable")
    native_dialog.refresh_results()
    assert native_dialog.resultsTree.topLevelItemCount() == 0
    assert (outside / "manifest.json").read_text() == "{broken"


def test_config_commit_then_exception_reconciles_row_without_undo(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    source = tmp_path / "predictor.tif"
    source.write_bytes(b"owned-after-atomic-commit-fixture")
    original = dialog.config_manager.update_config
    def commit_then_fail(key, value):
        original(key, value)
        raise OSError("Injected error after successful atomic commit")
    monkeypatch.setattr(dialog.config_manager, "update_config", commit_then_fail)
    dialog._begin_import([str(source)], "covariate")
    wait_until(lambda: not dialog.is_busy)
    assert dialog.config_manager.get_config()["covariates"] == {"predictor": source.name}
    assert dialog.covariatesTable.rowCount() == 1 and dialog.covariatesTable.item(0, 0).text() == "predictor"


def test_folder_action_rechecks_run_directory_after_symlink_redirection(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    run = tmp_path / "project/output/runs/damaged"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text("{broken", encoding="utf-8")
    dialog.refresh_results()
    dialog.resultsTree.setCurrentItem(dialog.resultsTree.topLevelItem(0))
    assert dialog.openRunButton.isEnabled()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # Only owned synthetic files; no recursive deletion or outside file changes.
    (run / "manifest.json").unlink()
    run.rmdir()
    try:
        run.symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink privilege unavailable")
    opened = []
    presenter = importlib.import_module(native_package[0] + ".gui.presenters.results_presenter")
    monkeypatch.setattr(presenter, "open_folder", opened.append)
    dialog.openRunButton.click()
    assert not opened and list(elsewhere.iterdir()) == []


def test_linked_manifest_is_invalid_before_any_external_metadata_read(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    run = tmp_path / "project/output/runs/marker-alias"
    run.mkdir(parents=True)
    (run / "population.tif").write_bytes(b"owned-ui-map")
    external = tmp_path / "external.json"
    external.write_text(json.dumps({"status": "complete", "outputs": ["population.tif"]}), encoding="utf-8")
    marker = run / "manifest.json"
    try:
        marker.symlink_to(external)
    except OSError:
        pytest.skip("File symlink privilege unavailable")
    presenter = importlib.import_module(native_package[0] + ".gui.presenters.results_presenter")
    read = presenter.read_manifest
    metadata_reads = []
    def observe_read(path):
        metadata_reads.append(Path(path))
        return read(path)
    monkeypatch.setattr(presenter, "read_manifest", observe_read)
    opened = []
    monkeypatch.setattr(presenter, "open_folder", lambda path: opened.append(Path(path).resolve()))
    dialog.refresh_results()
    assert dialog.resultsTree.topLevelItemCount() == 1
    item = dialog.resultsTree.topLevelItem(0)
    assert item.text(1) == "Invalid" and item.text(2) == "0"
    dialog.resultsTree.setCurrentItem(item)
    QApplication.processEvents()
    assert not metadata_reads
    assert dialog.openRunButton.isEnabled()
    assert not dialog.addRunLayersButton.isEnabled() and not dialog.summarizePopulationButton.isEnabled()
    dialog.openRunButton.click()
    assert opened == [run.resolve()]
    assert external.read_text() == json.dumps({"status": "complete", "outputs": ["population.tif"]})


def test_saved_run_action_guards_recheck_redirected_selected_folder_before_reads(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    run = tmp_path / "project/output/runs/selected"
    run.mkdir(parents=True)
    (run / "population.tif").write_bytes(b"owned-map")
    (run / "manifest.json").write_text(json.dumps({"status": "complete", "outputs": ["population.tif"]}), encoding="utf-8")
    dialog.iface = object()
    dialog.refresh_results()
    assert dialog.addRunLayersButton.isEnabled() and dialog.summarizePopulationButton.isEnabled()
    retained = tmp_path / "retained-old-run"
    assert run.resolve().is_relative_to(tmp_path.resolve()) and retained.resolve().is_relative_to(tmp_path.resolve())
    assert not retained.exists()
    run.rename(retained)  # Recoverable move of only the owned synthetic fixture.
    foreign = tmp_path / "outside-saved-runs"
    foreign.mkdir()
    (foreign / "manifest.json").write_text(json.dumps({"status": "complete", "outputs": ["foreign.tif"]}))
    (foreign / "foreign.tif").write_bytes(b"must-not-load")
    try:
        run.symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink privilege unavailable")
    reads, actions = [], []
    presenter = importlib.import_module(native_package[0] + ".gui.presenters.results_presenter")
    monkeypatch.setattr(presenter, "read_manifest", lambda path: reads.append(path))
    monkeypatch.setattr(dialog.layer_integration, "add_run", lambda *args: actions.append("maps"))
    monkeypatch.setattr(dialog.tools_controller, "start", lambda *args: actions.append("summary"))
    dialog._add_selected_run()
    dialog._open_population_summary()
    assert not reads and not actions
    assert not dialog.addRunLayersButton.isEnabled() and not dialog.summarizePopulationButton.isEnabled()
    assert "Refresh Results" in dialog.statusLabel.text()
    assert (foreign / "foreign.tif").read_bytes() == b"must-not-load"


def test_one_folder_stat_failure_does_not_abort_other_history_entries(native_dialog, native_package, tmp_path, monkeypatch):
    dialog = native_dialog
    initialize(dialog, tmp_path / "project")
    runs = tmp_path / "project/output/runs"
    for name in ("unreadable", "good"):
        directory = runs / name
        directory.mkdir(parents=True)
        (directory / "population.tif").write_bytes(b"owned-map")
        (directory / "manifest.json").write_text(json.dumps({"status": "complete", "outputs": ["population.tif"]}))
    presenter = importlib.import_module(native_package[0] + ".gui.presenters.results_presenter")
    class LocalPath(type(Path())):
        def is_dir(self):
            if self == runs / "unreadable":
                raise OSError("Injected one-folder metadata permission failure")
            return super().is_dir()
    monkeypatch.setattr(presenter, "Path", LocalPath)
    dialog.refresh_results()
    assert dialog.resultsTree.topLevelItemCount() == 1
    assert dialog.resultsTree.topLevelItem(0).text(0) == "good"
    assert dialog.resultsTree.topLevelItem(0).text(1) == "Complete"


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junction requires Windows")
def test_junction_history_run_directory_is_not_opened_or_listed(native_dialog, tmp_path):
    initialize(native_dialog, tmp_path / "project")
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (outside / "manifest.json").write_text("{broken", encoding="utf-8")
    runs = tmp_path / "project/output/runs"
    runs.mkdir(parents=True)
    alias = runs / "junction"
    assert alias.parent.resolve().is_relative_to(tmp_path.resolve()) and outside.is_relative_to(tmp_path.resolve())
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(outside)], capture_output=True, check=True)
    assert alias.is_junction() and not alias.is_symlink()
    native_dialog.refresh_results()
    assert native_dialog.resultsTree.topLevelItemCount() == 0
    assert (outside / "manifest.json").read_text() == "{broken"
