"""Real Qt worker/hash, collision choices, cancellation and disposal."""
import importlib
import time
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="Collision UI requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QThread
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              initialize, wait_until)


def collision(dialog, tmp_path, different=False):
    project = tmp_path / "project"
    initialize(dialog, project)
    source = tmp_path / "census.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    destination = project / "data/census.csv"
    destination.write_bytes(b"id,pop\n1,99\n" if different else source.read_bytes())
    dialog._begin_import([str(source)], "census_data")
    wait_until(lambda: dialog.project_presenter._conflict_dialog is not None)
    popup = dialog.project_presenter._conflict_dialog
    assert dialog.import_controller.worker is None
    assert dialog.import_controller.is_running and dialog.is_busy
    assert popup.isVisible()
    return source, destination, popup


def test_identical_choice_reuses_only_in_worker_and_restores_canonical_widget(native_dialog, native_package, tmp_path, monkeypatch):
    module = importlib.import_module(native_package[0] + ".services.file_handlers")
    old = module.FileHandler._fingerprint
    threads = []
    def probe(self, *args, **kwargs):
        threads.append(QThread.currentThread() != QApplication.instance().thread())
        return old(self, *args, **kwargs)
    monkeypatch.setattr(module.FileHandler, "_fingerprint", probe)
    source, target, popup = collision(native_dialog, tmp_path)
    assert popup.reuseButton.isEnabled()
    assert "population census" in popup.explanation.text()
    popup.reuseButton.click()
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.config_manager.get_config()["census_data"] == target.name
    assert native_dialog.populationCensusFileWidget.filePath() == str(target)
    assert target.read_bytes() == source.read_bytes() == b"id,pop\n1,12\n"
    assert len(threads) >= 4 and all(threads)


def test_age_sex_missing_id_shows_actionable_inline_error_and_keeps_input(native_dialog, tmp_path):
    project = tmp_path / "project"
    initialize(native_dialog, project)
    source = tmp_path / "age.csv"
    source.write_bytes(b"IDX,f_00,m_00\n188720000001,5,6\n")
    native_dialog._begin_import([str(source)], "agesex_data")
    wait_until(lambda: not native_dialog.is_busy)
    label = native_dialog._input_errors["agesex_data"]
    assert not label.isHidden()
    assert "zone-ID column 'id'" in label.text()
    assert "crosswalk" in label.toolTip() and "IDX" in label.toolTip()
    assert not native_dialog.config_manager.get_config().get("agesex_data")
    assert native_dialog.agesexCensusFileWidget.filePath() == ""
    assert not (project / "data/age.csv").exists()
    assert source.read_bytes() == b"IDX,f_00,m_00\n188720000001,5,6\n"


def test_different_choice_can_only_copy_to_new_portable_name(native_dialog, tmp_path):
    source, target, popup = collision(native_dialog, tmp_path, different=True)
    assert not popup.reuseButton.isEnabled()
    popup.filenameEdit.setText("../overwrite.csv")
    popup.copyButton.click()
    assert popup.errorLabel.text() and native_dialog.import_controller.worker is None
    popup.filenameEdit.setText("census_new.csv")
    popup.copyButton.click()
    wait_until(lambda: not native_dialog.is_busy)
    copied = target.with_name("census_new.csv")
    assert copied.read_bytes() == source.read_bytes()
    assert target.read_bytes() == b"id,pop\n1,99\n"
    assert native_dialog.config_manager.get_config()["census_data"] == copied.name


def test_cancel_retains_files_and_old_field_without_pending_worker(native_dialog, tmp_path):
    source, target, popup = collision(native_dialog, tmp_path)
    popup.reject()
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.project_presenter._conflict_dialog is None
    assert native_dialog.config_manager.get_config()["census_data"] is None
    assert native_dialog.populationCensusFileWidget.filePath() == ""
    assert target.read_bytes() == source.read_bytes()
    assert "cancelled" in native_dialog.statusLabel.text().lower()


@pytest.mark.parametrize("which", ["source", "destination"])
def test_changing_file_after_popup_refuses_reuse_and_preserves_new_bytes(native_dialog, tmp_path, which):
    source, target, popup = collision(native_dialog, tmp_path)
    changed = source if which == "source" else target
    changed.write_bytes(b"id,pop\n1,67\n")
    popup.reuseButton.click()
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.config_manager.get_config()["census_data"] is None
    assert native_dialog.populationCensusFileWidget.filePath() == ""
    assert changed.read_bytes() == b"id,pop\n1,67\n"
    assert "changed" in native_dialog.statusLabel.text()


def test_unload_pending_choice_disposes_without_restart(native_dialog, tmp_path):
    source, target, popup = collision(native_dialog, tmp_path)
    controller = native_dialog.import_controller
    native_dialog.dispose_when_idle()
    wait_until(lambda: sip.isdeleted(native_dialog))
    assert sip.isdeleted(popup)
    assert controller.worker is None and controller.pending_conflict is None
    assert target.read_bytes() == source.read_bytes()
    assert len(list(target.parent.iterdir())) == 1


def test_close_pending_choice_cancels_and_never_restarts(native_dialog, tmp_path):
    source, target, popup = collision(native_dialog, tmp_path)
    native_dialog.reject()
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.project_presenter._conflict_dialog is None
    assert target.read_bytes() == source.read_bytes()
    assert native_dialog.config_manager.get_config()["census_data"] is None


def test_project_config_change_during_choice_blocks_resume(native_dialog, tmp_path):
    source, target, popup = collision(native_dialog, tmp_path)
    native_dialog.config_manager.update_many({"data_dir": "new-data"})
    edited = Path(native_dialog.config_manager.config_path).read_bytes()
    popup.reuseButton.click()
    wait_until(lambda: not native_dialog.is_busy)
    assert "Project or data directory changed" in native_dialog.statusLabel.text()
    assert Path(native_dialog.config_manager.config_path).read_bytes() == edited
    assert not (target.parent.parent / "new-data").exists()
    assert source.read_bytes() == target.read_bytes()


def test_population_csv_not_silently_registered_as_age_sex(native_dialog, tmp_path):
    initialize(native_dialog, tmp_path / "project")
    source = tmp_path / "population.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    native_dialog._begin_import([str(source)], "agesex_data")
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.config_manager.get_config()["agesex_data"] is None
    assert "Age-sex CSV" in native_dialog.statusLabel.text()
    assert not (tmp_path / "project/data/population.csv").exists()


def test_config_change_before_worker_completion_does_not_register_wrong_namespace(native_dialog, native_package, tmp_path, monkeypatch):
    project = tmp_path / "project"
    initialize(native_dialog, project)
    module = importlib.import_module(native_package[0] + ".services.file_handlers")
    original_copy = module.FileHandler.copy_to_data_dir
    def copy_then_edit(self, *args, **kwargs):
        name = original_copy(self, *args, **kwargs)
        native_dialog.config_manager.update_many({"data_dir": "new-data"})
        return name
    monkeypatch.setattr(module.FileHandler, "copy_to_data_dir", copy_then_edit)
    source = tmp_path / "first.csv"
    source.write_bytes(b"custom_zone,custom_count\n1,20\n")
    native_dialog._begin_import([str(source)], "census_data")
    wait_until(lambda: not native_dialog.is_busy)
    config = native_dialog.config_manager.get_config()
    assert config["data_dir"] == "new-data" and config["census_data"] is None
    assert (project / "data/first.csv").read_bytes() == source.read_bytes()
    assert not (project / "new-data").exists()
    assert "Project or data directory changed" in native_dialog.statusLabel.text()


def test_cancel_while_hashing_never_opens_a_stale_choice(native_dialog, native_package, tmp_path, monkeypatch):
    project = tmp_path / "project"
    initialize(native_dialog, project)
    source = tmp_path / "census.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    target = project / "data/census.csv"
    target.write_bytes(source.read_bytes())
    module = importlib.import_module(native_package[0] + ".services.file_handlers")
    def cooperative_scan(self, path, token=None, progress=None):
        progress(1, path.name)
        for _ in range(1000):
            token.check()
            time.sleep(.005)
        pytest.fail("Cancellation should stop this owned worker")
    monkeypatch.setattr(module.FileHandler, "_fingerprint", cooperative_scan)
    native_dialog._begin_import([str(source)], "census_data")
    wait_until(lambda: native_dialog.mainProgressBar.value() == 1)
    native_dialog.cancel_all()
    wait_until(lambda: not native_dialog.is_busy)
    assert native_dialog.project_presenter._conflict_dialog is None
    assert native_dialog.import_controller.pending_conflict is None
    assert native_dialog.config_manager.get_config()["census_data"] is None
    assert target.read_bytes() == source.read_bytes()
    assert "cancelled" in native_dialog.statusLabel.text().lower()


@pytest.mark.parametrize("write_fails", [False, True])
def test_clearing_selection_retains_file_and_failure_restores_last_field(native_dialog, tmp_path, monkeypatch, write_fails):
    project = tmp_path / "project"
    initialize(native_dialog, project)
    target = project / "data/census.csv"
    target.write_bytes(b"id,pop\n1,12\n")
    native_dialog.config_manager.update_many({"census_data": target.name})
    native_dialog._restore_file_widget("census_data")
    original_config = Path(native_dialog.config_manager.config_path).read_bytes()
    if write_fails:
        def fail(*args):
            raise OSError("fixture config is read-only")
        monkeypatch.setattr(native_dialog.config_manager, "clear_config_value", fail)
    native_dialog.populationCensusFileWidget.setFilePath("")
    assert target.read_bytes() == b"id,pop\n1,12\n"
    if write_fails:
        assert native_dialog.populationCensusFileWidget.filePath() == str(target)
        assert Path(native_dialog.config_manager.config_path).read_bytes() == original_config
        assert "Could not clear input" in native_dialog.statusLabel.text()
    else:
        assert native_dialog.config_manager.get_config()["census_data"] is None
        assert native_dialog.populationCensusFileWidget.filePath() == ""


def test_batch_continues_after_conflict_without_losing_completed_imports(native_dialog, tmp_path):
    project = tmp_path / "project"
    initialize(native_dialog, project)
    # Import service fixture bytes only; these are not opened as numerical rasters.
    sources = [tmp_path / name for name in ("first.tif", "second.tif", "third.tif")]
    for index, source in enumerate(sources):
        source.write_bytes(f"synthetic import fixture {index}".encode())
    old = project / "data/second.tif"
    old.write_bytes(b"original input fixture")
    native_dialog._begin_import([str(path) for path in sources], "covariate")
    wait_until(lambda: native_dialog.project_presenter._conflict_dialog is not None)
    assert "first" in native_dialog.config_manager.get_config()["covariates"]
    popup = native_dialog.project_presenter._conflict_dialog
    popup.filenameEdit.setText("second_copy.tif")
    popup.copyButton.click()
    wait_until(lambda: not native_dialog.is_busy)
    assert set(native_dialog.config_manager.get_config()["covariates"]) == {"first", "second_copy", "third"}
    assert old.read_bytes() == b"original input fixture"
    assert old.with_name("second_copy.tif").read_bytes() == sources[1].read_bytes()
    assert old.with_name("third.tif").read_bytes() == sources[2].read_bytes()
