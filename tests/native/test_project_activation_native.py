"""Explicit project activation and button state on genuine Qt/QGIS."""
import importlib
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="Project activation requires genuine QGIS")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QProcess
from qgis.PyQt.QtWidgets import QApplication
from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog,
                              initialize)


def assert_open(dialog, root):
    assert dialog._project_ready
    assert Path(dialog.config_manager.working_dir).resolve() == root.resolve()
    assert dialog.initProjectButton.text() == "Project open"
    assert not dialog.initProjectButton.isEnabled()
    assert dialog.currentProjectLabel.text().startswith("Active project:")
    assert dialog.home_panel.state["project"]


def select(dialog, root):
    dialog.workingDirEdit.setFilePath(str(root))
    QApplication.processEvents()


def test_new_folder_requires_explicit_create_then_marks_project_open(native_dialog, tmp_path):
    dialog, root = native_dialog, tmp_path / "new-project"
    select(dialog, root)
    assert not root.exists() and not dialog._project_ready
    assert dialog.initProjectButton.text().casefold() == "create project"
    assert dialog.initProjectButton.isEnabled() and not dialog.mainStartButton.isEnabled()
    assert "selected folder" in dialog.currentProjectLabel.text().casefold()
    assert "not open" in dialog.currentProjectLabel.text().casefold()
    dialog.initProjectButton.click()
    assert (root / "config.yaml").is_file()
    assert_open(dialog, root)


def test_existing_folder_requires_explicit_open_preserving_config(native_dialog, native_package, tmp_path):
    root = tmp_path / "existing-project"
    manager = importlib.import_module(native_package[0] + ".services.config_manager").ConfigManager(native_dialog.logger)
    manager.create_initial_config(str(root))
    manager.update_many({"max_workers": 1, "selection_threshold": 0.37, "show_progress": False})
    config_path = Path(manager.config_path)
    before = config_path.read_bytes()
    select(native_dialog, root)
    assert not native_dialog._project_ready and native_dialog.config_manager.config_path is None
    assert native_dialog.initProjectButton.text().casefold() == "open project"
    assert native_dialog.initProjectButton.isEnabled()
    assert config_path.read_bytes() == before
    native_dialog.initProjectButton.click()
    assert_open(native_dialog, root)
    assert config_path.read_bytes() == before
    assert native_dialog.config_manager.get_config()["selection_threshold"] == 0.37


def test_active_project_disabled_click_and_direct_duplicate_cannot_reload(native_dialog, tmp_path, monkeypatch):
    dialog, root = native_dialog, tmp_path / "project"
    initialize(dialog, root)
    assert_open(dialog, root)
    dialog.config_manager.update_many({"selection_threshold": 0.43, "max_workers": 1})
    before = Path(dialog.config_manager.config_path).read_bytes()
    original_handler = dialog.logger.file_handler
    def forbidden(*args, **kwargs):
        pytest.fail("An already active project must not reload, initialize or reset its settings")
    monkeypatch.setattr(dialog.config_manager, "open_project", forbidden)
    monkeypatch.setattr(dialog.config_manager, "create_initial_config", forbidden)
    monkeypatch.setattr(dialog.settings_handler, "load_settings", forbidden)
    dialog.initProjectButton.click()  # Disabled native button must not dispatch.
    dialog.init_project()  # Public wrapper must guard duplicate calls as well.
    assert_open(dialog, root)
    assert Path(dialog.config_manager.config_path).read_bytes() == before
    assert dialog.logger.file_handler is original_handler


def test_selecting_second_folder_deactivates_without_opening_or_rewriting_first(native_dialog, tmp_path):
    dialog, first, second = native_dialog, tmp_path / "project-a", tmp_path / "project-b"
    initialize(dialog, first)
    first_config = Path(dialog.config_manager.config_path)
    before = first_config.read_bytes()
    select(dialog, second)
    assert not dialog._project_ready and not dialog.home_panel.state["project"]
    assert not dialog.mainStartButton.isEnabled()
    assert dialog.initProjectButton.isEnabled()
    assert "selected folder" in dialog.currentProjectLabel.text().casefold()
    assert "not open" in dialog.currentProjectLabel.text().casefold()
    assert Path(dialog.config_manager.config_path) == first_config
    assert first_config.read_bytes() == before and not second.exists()
    dialog.initProjectButton.click()
    assert_open(dialog, second)
    assert first_config.read_bytes() == before


def test_same_active_canonical_path_signal_is_noop(native_dialog, tmp_path):
    dialog, root = native_dialog, tmp_path / "project"
    initialize(dialog, root)
    before = Path(dialog.config_manager.config_path).read_bytes()
    dialog.on_working_dir_changed(str(root / "."))
    QApplication.processEvents()
    assert_open(dialog, root)
    assert Path(dialog.config_manager.config_path).read_bytes() == before


@pytest.mark.parametrize("failure", ["invalid-config", "protected-path"])
def test_failed_candidate_never_claims_open_or_changes_prior_config(native_dialog, tmp_path, failure):
    dialog, first = native_dialog, tmp_path / "good-project"
    initialize(dialog, first)
    config_path = Path(dialog.config_manager.config_path)
    before = config_path.read_bytes()
    if failure == "invalid-config":
        candidate = tmp_path / "broken-project"
        candidate.mkdir()
        (candidate / "config.yaml").write_text("logging: [invalid\n", encoding="utf-8")
    else:
        # Only the disposable fixture cache is used, never the installed plugin.
        candidate = dialog.job_cache.parent / "forbidden-project"
    select(dialog, candidate)
    dialog.init_project()
    assert not dialog._project_ready and not dialog.home_panel.state["project"]
    assert dialog.initProjectButton.text() != "Project open"
    assert dialog.initProjectButton.isEnabled() and not dialog.mainStartButton.isEnabled()
    assert not dialog.currentProjectLabel.text().startswith("Active project:")
    assert Path(dialog.config_manager.config_path) == config_path and config_path.read_bytes() == before
    if failure == "protected-path":
        assert not candidate.exists()
        assert "inside the temporary job cache" in dialog.statusLabel.text().casefold()


def test_owned_tool_busy_completion_restores_active_disabled_action(native_dialog, tmp_path, monkeypatch):
    dialog, root = native_dialog, tmp_path / "project"
    initialize(dialog, root)
    assert_open(dialog, root)
    before = Path(dialog.config_manager.config_path).read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("Busy or already active project activation must not touch configuration")
    monkeypatch.setattr(dialog.config_manager, "open_project", forbidden)
    # Exercise genuine Qt signals and the controller's actual ownership predicate,
    # without launching a numerical child or performing filesystem preparation.
    controller = dialog.tools_controller
    owned = QProcess(controller)
    controller.process = owned
    try:
        controller.busyChanged.emit(True)
        assert dialog.is_busy and not dialog.initProjectButton.isEnabled()
        dialog.init_project()
        controller.process = None
        controller.busyChanged.emit(False)
        controller.completed.emit()
        QApplication.processEvents()
        assert not dialog.is_busy
        assert_open(dialog, root)
        assert Path(dialog.config_manager.config_path).read_bytes() == before
    finally:
        controller.process = None
        owned.deleteLater()


def test_late_activation_failure_does_not_claim_project_open(native_dialog, native_package, tmp_path, monkeypatch):
    dialog, first, candidate = native_dialog, tmp_path / "good-project", tmp_path / "candidate"
    initialize(dialog, first)
    first_config = Path(dialog.config_manager.config_path)
    first_before = first_config.read_bytes()
    manager = importlib.import_module(native_package[0] + ".services.config_manager").ConfigManager(dialog.logger)
    manager.create_initial_config(str(candidate))
    candidate_config = Path(manager.config_path)
    candidate_before = candidate_config.read_bytes()
    def unavailable(*args, **kwargs):
        raise OSError("Controlled late history refresh failure")
    monkeypatch.setattr(dialog, "refresh_results", unavailable)
    select(dialog, candidate)
    dialog.init_project()
    assert "Controlled late history refresh failure" in dialog.statusLabel.text()
    assert not dialog._project_ready and not dialog.home_panel.state["project"]
    assert not dialog.mainStartButton.isEnabled()
    assert dialog.initProjectButton.text().casefold() == "open project"
    assert dialog.initProjectButton.isEnabled()
    assert not dialog.currentProjectLabel.text().startswith("Active project:")
    assert first_config.read_bytes() == first_before
    assert candidate_config.read_bytes() == candidate_before
