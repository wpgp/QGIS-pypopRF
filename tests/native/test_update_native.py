"""Real QGIS installer qualification in a fail-closed isolated child profile."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from scripts.build_plugin import verify_package

pytest.importorskip("qgis.core", reason="Installer acceptance requires native QGIS")
pytestmark = pytest.mark.qgis
ROOT = Path(__file__).resolve().parents[2]


def validated_archive():
    archive = Path(os.environ.get("PYPOPRF_TEST_PLUGIN_ZIP", str(ROOT / "dist" / "pypopRF.zip")))
    if not archive.is_file():
        pytest.skip("Supply a validated plugin ZIP with PYPOPRF_TEST_PLUGIN_ZIP")
    verify_package(archive)
    return archive.resolve()


def create_sandbox(tmp_path):
    sandbox = tmp_path / "owned-installer-sandbox"
    sandbox.mkdir()
    nonce = uuid4().hex
    (sandbox / "owned-sandbox.txt").write_text(nonce)
    return sandbox, nonce


def run_sandbox(archive, sandbox, nonce, scenario):
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, str(ROOT / "tests" / "helpers" / "installer_sandbox.py"),
        str(sandbox), nonce, str(archive), scenario], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha256
    records = [line.split("=", 1)[1] for line in result.stdout.splitlines()
               if line.startswith("INSTALLER_SANDBOX_RESULT=")]
    assert len(records) == 1
    report = json.loads(records[0])
    assert report["status"] == "complete" and report["scenario"] == scenario
    assert Path(report["settings_file"]).resolve().is_relative_to(sandbox.resolve())
    assert Path(report["plugins_dir"]).resolve().is_relative_to(sandbox.resolve())
    return report


@pytest.mark.parametrize("scenario", ["idle_update_reinstall", "busy_unload", "probe_unload", "failed_tool",
                                     "corrupt_archive", "incomplete_archive", "gc_busy_unload"])
def test_native_installer_update_lifecycle_is_profile_isolated(tmp_path, scenario):
    archive = validated_archive()
    sandbox, nonce = create_sandbox(tmp_path)
    report = run_sandbox(archive, sandbox, nonce, scenario)
    if scenario == "idle_update_reinstall":
        assert report["close_reopen_cycles"] == 4
    if scenario in {"busy_unload", "gc_busy_unload"}:
        assert report["zip_replaced_while_child_alive"]
        assert report["frozen_source_unchanged"] and report["plugin_collected"]
        assert report["dialog_deleted"] and report["logger_handlers"] == 0
        assert report["log_rename_completed"] and report["job_cache_removed_after_exit"]


@pytest.mark.skipif(os.name != "nt", reason="A copied Windows loaded-image lock requires Windows")
def test_native_legacy_loaded_dll_migrates_after_one_normal_process_exit(tmp_path):
    archive = validated_archive()
    sandbox, nonce = create_sandbox(tmp_path)
    first = run_sandbox(archive, sandbox, nonce, "legacy_migration_prepare")
    assert first["loaded_fixture_remained_locked_after_unload"]
    assert first["plugin_disabled_for_next_start"] and first["system_dll_unchanged"]
    # subprocess.run returned: only the normal helper process exit releases
    # its loaded fixture. No FreeLibrary, process-tree kill or manual deletion.
    second = run_sandbox(archive, sandbox, nonce, "legacy_migration_finish")
    assert second["same_profile_fresh_process_install_enable"]
    assert not second["manual_folder_delete"]
    assert second["saved_project_and_data_preserved"]
