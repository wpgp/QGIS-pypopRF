import os
from pathlib import Path
import subprocess
import sys

import pytest

from services.project_location import ensure_project_location, ensure_project_paths, ensure_gui_log_location, ProjectLocationError


@pytest.fixture
def protected(tmp_path):
    plugin, cache, runtime = (tmp_path / name for name in ("installed-plugin", "gui-cache", "engine-cache"))
    for root in (plugin, cache, runtime):
        root.mkdir()
        (root / "canary").write_bytes(b"protected user data")
    return {"plugin_root": plugin, "job_cache": cache / "jobs", "runtime_cache": runtime}


@pytest.mark.parametrize("role", ["plugin_root", "job_cache", "runtime_cache"])
@pytest.mark.parametrize("child", [False, True])
def test_protected_equality_and_descendants_refused_without_writes(protected, role, child):
    root = protected[role].parent if role == "job_cache" else protected[role]
    candidate = root / "new-project" if child else root
    before = {base / "canary": (base / "canary").read_bytes()
              for base in (protected["plugin_root"], protected["job_cache"].parent, protected["runtime_cache"])}
    with pytest.raises(ProjectLocationError, match="Back up and move"):
        ensure_project_location(candidate, **protected)
    assert {p: p.read_bytes() for p in before} == before
    if child:
        assert not candidate.exists()


def test_safe_external_sibling_and_ancestor_projects_allowed(protected, tmp_path):
    assert ensure_project_location(tmp_path / "safe-external", **protected) == tmp_path / "safe-external"
    assert ensure_project_location(tmp_path, **protected) == tmp_path
    assert ensure_project_location(tmp_path / "installed-plugin-sibling", **protected) == tmp_path / "installed-plugin-sibling"


def test_runtime_cache_optional_and_nonexistent_paths_still_guarded(tmp_path):
    plugin = tmp_path / "future-plugin"
    with pytest.raises(ProjectLocationError):
        ensure_project_location(plugin / "future-project", plugin_root=plugin)
    assert ensure_project_location(tmp_path / "external", plugin_root=plugin) == tmp_path / "external"
    assert list(tmp_path.iterdir()) == []


def test_parent_segments_normalized_before_containment(protected, tmp_path):
    with pytest.raises(ProjectLocationError):
        ensure_project_location(protected["plugin_root"] / "child" / ".." / "project", **protected)
    assert ensure_project_location(protected["plugin_root"] / ".." / "external", **protected) == tmp_path / "external"


@pytest.mark.parametrize("direction", ["project_alias", "protected_alias"])
def test_folder_aliases_resolve_before_comparison(protected, tmp_path, direction):
    alias = tmp_path / "folder-alias"
    target = protected["plugin_root"]
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows user lacks symbolic-link privilege")
    candidate = alias / "project" if direction == "project_alias" else target / "project"
    roots = dict(protected, plugin_root=alias) if direction == "protected_alias" else protected
    with pytest.raises(ProjectLocationError):
        ensure_project_location(candidate, **roots)
    assert (target / "canary").read_bytes() == b"protected user data"


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junctions")
def test_actual_junction_project_alias_cannot_bypass_protected_root(protected, tmp_path):
    alias = tmp_path / "junction-alias"
    assert alias.is_relative_to(tmp_path) and protected["plugin_root"].is_relative_to(tmp_path)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(protected["plugin_root"])],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    with pytest.raises(ProjectLocationError):
        ensure_project_location(alias / "new-project", **protected)
    assert (protected["plugin_root"] / "canary").read_bytes() == b"protected user data"


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows leaf job-cache junction")
def test_redirected_jobs_protect_actual_jobs_not_unrelated_parent(protected, tmp_path):
    actual = tmp_path / "redirected-jobs"
    actual.mkdir()
    link = protected["job_cache"]
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(actual)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    with pytest.raises(ProjectLocationError):
        ensure_project_location(actual / "project", **protected)
    assert ensure_project_location(tmp_path / "safe-sibling", **protected) == tmp_path / "safe-sibling"
    assert ensure_project_location(tmp_path, **protected) == tmp_path


def test_service_import_is_stdlib_only_in_canonical_and_plugin_namespace():
    root = Path(__file__).resolve().parents[2]
    script = f"""import importlib,sys,types
sys.path.insert(0,{str(root)!r})
plugin=types.ModuleType('location_probe');plugin.__path__=[{str(root)!r}];sys.modules[plugin.__name__]=plugin
for name in ('services.project_location','location_probe.services.project_location'): importlib.import_module(name)
assert not any(name in sys.modules for name in ('qgis','numpy','rasterio','sklearn'))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field", ["data_dir", "output_dir"])
@pytest.mark.parametrize("role", ["plugin_root", "job_cache", "runtime_cache"])
def test_external_project_with_protected_configured_directory_is_refused(protected, tmp_path, field, role):
    target = protected[role].parent if role == "job_cache" else protected[role]
    project = tmp_path / "external-project"
    with pytest.raises(ProjectLocationError, match=field + " is unsafe"):
        ensure_project_paths(project, {field: str(target / "user-data")}, **protected)
    assert not project.exists() and not (target / "user-data").exists()


def test_safe_ancestor_project_requires_safe_configured_directories(protected, tmp_path):
    assert ensure_project_paths(tmp_path, {}, **protected) == tmp_path
    with pytest.raises(ProjectLocationError):
        ensure_project_paths(tmp_path, {"output_dir": "installed-plugin/runs"}, **protected)


def directory_alias(link, target):
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


def test_fixed_gui_log_directory_checked_even_with_custom_output(protected, tmp_path):
    project = tmp_path / "external-project"
    project.mkdir()
    directory_alias(project / "output", protected["plugin_root"])
    before = (protected["plugin_root"] / "canary").read_bytes()
    with pytest.raises(ProjectLocationError, match="GUI log directory"):
        ensure_project_paths(project, {"output_dir": "results", "logging": {"file": "review.log"}}, **protected)
    assert not (protected["plugin_root"] / "review.log").exists()
    assert (protected["plugin_root"] / "canary").read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory"])
def test_gui_log_leaf_must_be_dedicated_regular_file(protected, tmp_path, kind):
    project = tmp_path / "external-project"
    output = project / "output"
    output.mkdir(parents=True)
    target = protected["plugin_root"] / "metadata.txt"
    target.write_bytes(b"protected metadata")
    log = output / "review.log"
    if kind == "symlink":
        try:
            log.symlink_to(target)
        except OSError:
            pytest.skip("Windows user lacks symbolic-link privilege")
    elif kind == "hardlink":
        os.link(target, log)
        assert target.stat().st_nlink > 1
    else:
        log.mkdir()
    with pytest.raises(ProjectLocationError, match="dedicated ordinary file"):
        ensure_gui_log_location(project, "review.log", **protected)
    with pytest.raises(ProjectLocationError, match="dedicated ordinary file"):
        ensure_project_paths(project, {"logging": {"file": "review.log"}}, **protected)
    assert target.read_bytes() == b"protected metadata"


def test_safe_external_log_parent_alias_is_not_categorically_refused(protected, tmp_path):
    project = tmp_path / "external-project"
    project.mkdir()
    logs = tmp_path / "external-logs"
    logs.mkdir()
    directory_alias(project / "output", logs)
    assert ensure_gui_log_location(project, "review.log", **protected) == logs / "review.log"
    assert list(logs.iterdir()) == []
