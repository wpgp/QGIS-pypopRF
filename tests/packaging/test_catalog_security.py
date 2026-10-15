"""Submission configs may accept public hashes, never new secrets or code."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from scripts.build_plugin import build_plugin, verify_package


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "plugin.zip"
    build_plugin(path)
    return path


def test_checksum_baseline_is_deterministic_and_cannot_disable_scanners(archive):
    with zipfile.ZipFile(archive) as package:
        baseline = json.loads(package.read("pypopRF/.secrets.baseline"))
        assert set(baseline) == {"version", "results", "_comment", "plugins_used", "filters_used"}
        assert len(baseline["plugins_used"]) == 27
        assert not any("regex" in item["path"] for item in baseline["filters_used"])
        assert set(baseline["results"]) == {"pypopRF/PACKAGE_MANIFEST.json", "pypopRF/requirements-engine-wheels.json"}
        assert all(item["type"] == "Hex High Entropy String" and item["is_secret"] is False
                   for items in baseline["results"].values() for item in items)


def test_modified_scan_baseline_is_rejected(archive, tmp_path):
    with zipfile.ZipFile(archive) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    baseline = json.loads(entries["pypopRF/.secrets.baseline"])
    baseline["plugins_used"] = []
    entries["pypopRF/.secrets.baseline"] = json.dumps(baseline).encode()
    target = tmp_path / "tampered.zip"
    with zipfile.ZipFile(target, "w") as package:
        for name, data in entries.items():
            package.writestr(name, data)
    with pytest.raises(ValueError, match="baseline differs"):
        verify_package(target)


def test_package_passes_independent_unbaselined_security_scan(archive):
    pytest.importorskip("bandit")
    pytest.importorskip("detect_secrets")
    from scripts.check_catalog import check_catalog
    report = check_catalog(archive)
    assert report["passed"], report
    assert report["secrets"]["reviewed_checksum_findings"] > 100
    assert report["secrets"]["detectors_enabled"] >= 27


def test_unrelated_hex_secret_is_not_accepted_as_a_file_hash(archive, tmp_path):
    pytest.importorskip("detect_secrets")
    from scripts.check_catalog import scan_secrets
    with zipfile.ZipFile(archive) as package:
        package.extractall(tmp_path / "extracted")
    directory = tmp_path / "extracted"
    baseline = json.loads((directory / "pypopRF/.secrets.baseline").read_text())
    fixture = hashlib.sha256(b"synthetic-secret-not-a-credential").hexdigest()
    (directory / "pypopRF/fixture.py").write_text(f"value = '{fixture}'\n", encoding="utf-8")
    report = scan_secrets(directory, baseline)
    assert any(item["file"] == "pypopRF/fixture.py" for item in report["new_findings"])


def test_new_subprocess_call_is_not_suppressed(tmp_path):
    pytest.importorskip("bandit")
    from scripts.check_catalog import scan_bandit
    (tmp_path / "fixture.py").write_text("import subprocess\nsubprocess.run(['python', '-V'])\n", encoding="utf-8")
    assert any(item["rule"] == "B603" for item in scan_bandit(tmp_path))


def test_no_legacy_qgis_enum_fallbacks_remain():
    root = Path(__file__).resolve().parents[2]
    shader = (root / "gui/layer_integration.py").read_text(encoding="utf-8")
    project = (root / "gui/presenters/project_presenter.py").read_text(encoding="utf-8")
    assert "Qgis.ShaderInterpolationMethod.Linear" in shader
    assert "QgsColorRampShader.Interpolated" not in shader
    assert "QgsFileWidget.GetDirectory" not in project


def test_packaged_baseline_keeps_default_detector_selection(archive, tmp_path):
    pytest.importorskip("detect_secrets")
    with zipfile.ZipFile(archive) as package:
        package.extractall(tmp_path / "selection")
    baseline = tmp_path / "selection/pypopRF/.secrets.baseline"
    before = baseline.read_bytes()
    command = [sys.executable, "-m", "detect_secrets", "scan", "--list-all-plugins"]
    default = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    configured = subprocess.run([*command, "--baseline", str(baseline)],
                               capture_output=True, text=True, timeout=30, check=True)
    assert set(configured.stdout.splitlines()) == set(default.stdout.splitlines())
    assert len(configured.stdout.splitlines()) >= 27
    assert baseline.read_bytes() == before
    from detect_secrets.settings import default_settings
    with default_settings() as settings:
        expected = settings.json()
    data = json.loads(before)
    assert {item["name"]: item for item in data["plugins_used"]} == {
        item["name"]: item for item in expected["plugins_used"]}
    assert data["filters_used"] == expected["filters_used"]


@pytest.mark.parametrize("returncode,stdout", [(0, ""), (2, "{}"), (0, "not json")])
def test_scan_tool_errors_cannot_become_green(monkeypatch, tmp_path, returncode, stdout):
    from scripts.check_catalog import run_json
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], returncode, stdout, "scanner failed"))
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        run_json([sys.executable, "-m", "scanner"], tmp_path)
