"""Genuine Qt location refusals, with only owned Temp fake plugin/cache roots."""
import importlib
import os
from pathlib import Path
import subprocess

import pytest

pytest.importorskip("qgis.core", reason="Project-location UI tests require native QGIS")
pytestmark = pytest.mark.qgis

from .test_qgis_native import (native_package as native_package, native_dialog as native_dialog, initialize)


def protected_roots(dialog, tmp_path, monkeypatch):
    plugin, cache, engine = (tmp_path / name for name in ("fake-installed-plugin", "fake-gui-cache", "fake-engine-cache"))
    for root in (plugin, cache, engine):
        root.mkdir()
        (root / "canary").write_bytes(b"fixture must survive")
    monkeypatch.setattr(dialog, "plugin_root", plugin)
    monkeypatch.setattr(dialog, "job_cache", cache / "jobs")
    monkeypatch.setattr(dialog.runtime_controller.manager, "cache_root", engine, raising=False)
    return {"plugin": plugin, "gui_cache": cache, "runtime": engine}


@pytest.mark.parametrize("role", ["plugin", "gui_cache", "runtime"])
@pytest.mark.parametrize("existing", [False, True])
def test_native_create_or_open_protected_location_preserves_active_project(native_dialog, native_package, tmp_path, monkeypatch, role, existing):
    dialog = native_dialog
    active = tmp_path / "safe-active-project"
    initialize(dialog, active)
    active_config = Path(dialog.config_manager.config_path)
    active_bytes = active_config.read_bytes()
    roots = protected_roots(dialog, tmp_path, monkeypatch)
    candidate = roots[role] / "user-project"
    if existing:
        module = importlib.import_module(native_package[0] + ".services.config_manager")
        manager = module.ConfigManager(dialog.logger)
        manager.create_initial_config(candidate)
        (candidate / "data/population-canary").write_bytes(b"user data")
        (candidate / "output").mkdir()
        (candidate / "output/protected.log").write_bytes(b"existing project log")
    before = {p: p.read_bytes() for root in roots.values() for p in root.rglob("*") if p.is_file()}
    dialog.workingDirEdit.setFilePath(str(candidate))
    dialog.init_project()
    assert Path(dialog.config_manager.config_path) == active_config
    assert dialog.config_manager.working_dir == str(active)
    assert active_config.read_bytes() == active_bytes
    assert {p: p.read_bytes() for root in roots.values() for p in root.rglob("*") if p.is_file()} == before
    assert "Back up and move" in dialog.statusLabel.text()
    assert "No project files were moved or deleted" in dialog.statusLabel.text()
    if not existing:
        assert not candidate.exists()
    # Refusal does not poison subsequent activation of a genuinely safe sibling.
    safe = tmp_path / "safe-next-project"
    initialize(dialog, safe)
    assert dialog._project_ready
    assert active_config.read_bytes() == active_bytes


@pytest.mark.parametrize("role", ["plugin", "gui_cache", "runtime"])
def test_native_preparation_refuses_protected_destination_before_controller_start(native_dialog, tmp_path, monkeypatch, role):
    dialog = native_dialog
    initialize(dialog, tmp_path / "safe-active")
    old_path = dialog.config_manager.config_path
    old_bytes = Path(old_path).read_bytes()
    roots = protected_roots(dialog, tmp_path, monkeypatch)
    dialog._open_preparation()
    wizard = dialog._preparation_window
    # This test reaches only GUI request construction; no fake raster is opened
    # by a numerical process and no real plugin/cache directory is selected.
    census = tmp_path / "census.csv"
    census.write_bytes(b"id,pop\n1,10\n")
    wizard.reference.edit.setText(str(tmp_path / "reference.tif"))
    wizard.census.edit.setText(str(census))
    wizard.outputEdit.setText(str(roots[role] / "prepared-project"))
    for _ in range(3):
        wizard.next()
    assert wizard.currentPage() is wizard.reviewPage
    wizard._checked = wizard._request("inspect")
    wizard._expected_inputs = [{"path": str(census), "bytes": census.stat().st_size, "sha256": "a" * 64}]
    wizard._ready = True
    wizard.confirm.setChecked(True)
    calls = []
    monkeypatch.setattr(dialog.tools_controller, "start", lambda request: calls.append(request) or False)
    assert wizard.validateCurrentPage() is False
    assert calls == [] and not (roots[role] / "prepared-project").exists()
    assert "Back up and move" in wizard.reportView.toPlainText()
    assert dialog.config_manager.config_path == old_path and Path(old_path).read_bytes() == old_bytes
    assert all((root / "canary").read_bytes() == b"fixture must survive" for root in roots.values())
    wizard.reject()


@pytest.mark.parametrize("field", ["data_dir", "output_dir"])
def test_native_existing_external_project_with_protected_configured_path_is_not_activated(native_dialog, native_package, tmp_path, monkeypatch, field):
    dialog = native_dialog
    initialize(dialog, tmp_path / "safe-active")
    old_config = dialog.config_manager.config_path
    old_bytes = Path(old_config).read_bytes()
    roots = protected_roots(dialog, tmp_path, monkeypatch)
    module = importlib.import_module(native_package[0] + ".services.config_manager")
    candidate = tmp_path / "external-candidate"
    manager = module.ConfigManager(dialog.logger)
    manager.create_initial_config(candidate)
    manager.update_many({field: str(roots["plugin"] / "must-not-create")})
    before = {p: p.read_bytes() for base in (candidate, *roots.values()) for p in base.rglob("*") if p.is_file()}
    dialog.workingDirEdit.setFilePath(str(candidate))
    dialog.init_project()
    assert dialog.config_manager.config_path == old_config and Path(old_config).read_bytes() == old_bytes
    assert {p: p.read_bytes() for base in (candidate, *roots.values()) for p in base.rglob("*") if p.is_file()} == before
    assert field + " is unsafe" in dialog.statusLabel.text()
    assert not (roots["plugin"] / "must-not-create").exists()


@pytest.mark.parametrize("alias", ["output_directory", "log_symlink", "log_hardlink"])
def test_native_fixed_gui_log_alias_cannot_activate_or_modify_protected_files(native_dialog, native_package, tmp_path, monkeypatch, alias):
    dialog = native_dialog
    initialize(dialog, tmp_path / "safe-active")
    old_path = dialog.config_manager.config_path
    old_bytes = Path(old_path).read_bytes()
    roots = protected_roots(dialog, tmp_path, monkeypatch)
    module = importlib.import_module(native_package[0] + ".services.config_manager")
    candidate = tmp_path / "external-candidate"
    manager = module.ConfigManager(dialog.logger)
    manager.create_initial_config(candidate)
    manager.update_many({"output_dir": "results", "logging": {"level": "INFO", "file": "review.log"}})
    target = roots["plugin"] / "metadata.txt"
    target.write_bytes(b"foreign metadata must not be logged")
    output = candidate / "output"
    if alias == "output_directory":
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(output), str(roots["plugin"])],
                                    capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stderr
        else:
            output.symlink_to(roots["plugin"], target_is_directory=True)
    else:
        output.mkdir()
        if alias == "log_hardlink":
            os.link(target, output / "review.log")
        else:
            try:
                (output / "review.log").symlink_to(target)
            except OSError:
                pytest.skip("Windows user lacks file-symlink privilege")
    config_bytes = (candidate / "config.yaml").read_bytes()
    dialog.workingDirEdit.setFilePath(str(candidate))
    dialog.init_project()
    assert dialog.config_manager.config_path == old_path and Path(old_path).read_bytes() == old_bytes
    assert (candidate / "config.yaml").read_bytes() == config_bytes
    assert target.read_bytes() == b"foreign metadata must not be logged"
    assert not (roots["plugin"] / "review.log").exists()
    assert "GUI log" in dialog.statusLabel.text()


def test_native_current_data_dir_edit_blocks_import_before_worker_or_ui_changes(native_dialog, tmp_path, monkeypatch):
    dialog = native_dialog
    project = tmp_path / "safe-active"
    initialize(dialog, project)
    roots = protected_roots(dialog, tmp_path, monkeypatch)
    dialog.config_manager.update_many({"data_dir": str(roots["plugin"])})
    config_path = Path(dialog.config_manager.config_path)
    edited = config_path.read_bytes()
    source = tmp_path / "new-input.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    states = (dialog.workingDirEdit.isEnabled(), dialog.initProjectButton.isEnabled(),
              dialog.setupRuntimeButton.isEnabled(), dialog.mainStartButton.text(), dialog._project_ready)
    monkeypatch.setattr(dialog.import_controller, "start", lambda *args: pytest.fail("Protected import must never start a worker"))
    dialog._begin_import([str(source)], "census_data")
    assert not dialog.import_controller.is_running
    assert states == (dialog.workingDirEdit.isEnabled(), dialog.initProjectButton.isEnabled(),
                      dialog.setupRuntimeButton.isEnabled(), dialog.mainStartButton.text(), dialog._project_ready)
    assert config_path.read_bytes() == edited and not (roots["plugin"] / source.name).exists()
    assert (roots["plugin"] / "canary").read_bytes() == b"fixture must survive"
    assert "Import blocked" in dialog.statusLabel.text() and "data_dir is unsafe" in dialog.statusLabel.text()
