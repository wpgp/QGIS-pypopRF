import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from services import engine_snapshot
from services.engine_snapshot import create_engine_snapshot, engine_arguments, SnapshotError
from shared.runtime_environment import child_environment
from core.pypoprf.utils.runtime import CancellationToken, CancelledError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "installed-plugin"
    for relative in engine_snapshot.REQUIRED_FILES + engine_snapshot.PROVENANCE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# fixture module\n")
    (root / "shared/runtime_environment.py").write_bytes((ROOT / "shared/runtime_environment.py").read_bytes())
    (root / "metadata.txt").write_bytes(b"[general]\nversion=fixture-v1\n")
    (root / "requirements-engine.lock").write_text("pytest==" + version("pytest") + " --hash=sha256:" + "a" * 64 + "\n")
    (root / "requirements.txt").write_bytes(b"# empty direct summary\n")
    main = b"""import hashlib,json,os,pathlib,sys
from .later import VALUE
print(json.dumps({'value':VALUE,'file':__file__,'cwd':os.getcwd(),'no_bytecode':sys.dont_write_bytecode,
                 'threads':os.environ['OMP_NUM_THREADS'],'args':sys.argv[1:],
                 'snapshot':getattr(sys,'_pypoprf_engine_snapshot',None),
                 'source_sha':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}))
"""
    (root / "core/pypoprf/__main__.py").write_bytes(main)
    (root / "core/pypoprf/tools.py").write_bytes(main)
    (root / "core/pypoprf/later.py").write_bytes(b"VALUE='frozen-v1'\n")
    return root


def new_job(tmp_path, name="job"):
    path = tmp_path / name
    path.mkdir()
    return path


def run(root, module="core.pypoprf", arguments=()):
    return subprocess.run([sys.executable, *engine_arguments(root, module, arguments)],
                          cwd=root.parent, env=child_environment(sys.executable),
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def test_snapshot_copies_only_bounded_engine_bytes_and_provenance(package, tmp_path):
    (package / "gui").mkdir()
    (package / "gui/not-for-child.py").write_bytes(b"GUI must not be copied")
    (package / "core/input-data.tif").write_bytes(b"not input data")
    (package / "core/__pycache__").mkdir()
    (package / "core/__pycache__/old.pyc").write_bytes(b"not bytecode")
    before = {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}
    job = new_job(tmp_path)
    (job / "request.json").write_bytes(b"existing caller-owned metadata")
    root = create_engine_snapshot(package, job)
    manifest = json.loads((root / engine_snapshot.MANIFEST_NAME).read_bytes())
    assert root == job / "engine_source"
    assert manifest["schema_version"] == 1 and manifest["source_root"] == str(package)
    assert manifest["file_count"] == len(manifest["files"])
    assert manifest["total_bytes"] == sum(record["bytes"] for record in manifest["files"].values())
    assert set(engine_snapshot.PROVENANCE_FILES).issubset(manifest["files"])
    assert not {"gui/not-for-child.py", "core/input-data.tif", "core/__pycache__/old.pyc"} & manifest["files"].keys()
    for relative, record in manifest["files"].items():
        assert (root / relative).read_bytes() == before[relative]
        assert record == {"bytes": len(before[relative]), "sha256": hashlib.sha256(before[relative]).hexdigest()}
    assert {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()} == before
    assert (job / "request.json").read_bytes() == b"existing caller-owned metadata"


@pytest.mark.parametrize("module", ["core.pypoprf", "core.pypoprf.tools"])
def test_actual_child_uses_frozen_lazy_code_after_source_folder_removed(package, tmp_path, module):
    job = new_job(tmp_path, "проект_人口")
    root = create_engine_snapshot(package, job)
    # Move only this exclusively created fixture source, not real plugin code.
    moved = tmp_path / "old-plugin"
    package.rename(moved)
    (moved / "core/pypoprf/later.py").write_bytes(b"VALUE='replacement-v2'\n")
    before_env, before_cwd = dict(os.environ), Path.cwd()
    result = run(root, module, ["--literal", "путь"])
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["value"] == "frozen-v1" and Path(value["file"]).is_relative_to(root)
    assert Path(value["cwd"]) == job and value["no_bytecode"] is True
    assert value["threads"] == "1" and value["args"] == ["--literal", "путь"]
    manifest_bytes = (root / engine_snapshot.MANIFEST_NAME).read_bytes()
    manifest = json.loads(manifest_bytes)
    assert value["snapshot"] == {"manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                                  "file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"],
                                  "original_source_root": str(package)}
    assert value["source_sha"] == hashlib.sha256((root / Path(value["file"]).relative_to(root)).read_bytes()).hexdigest()
    assert not list(root.rglob("__pycache__"))
    assert dict(os.environ) == before_env and Path.cwd() == before_cwd


@pytest.mark.parametrize("corruption", ["source", "manifest", "extra", "directory"])
def test_child_refuses_snapshot_mutation_before_any_core_execution(package, tmp_path, corruption):
    root = create_engine_snapshot(package, new_job(tmp_path))
    args = engine_arguments(root, "core.pypoprf", [])
    if corruption == "source":
        (root / "core/pypoprf/later.py").write_bytes(b"VALUE='tampered'\n")
    elif corruption == "manifest":
        (root / engine_snapshot.MANIFEST_NAME).write_bytes(b"{}")
    elif corruption == "extra":
        (root / "core/extra.py").write_bytes(b"extra resources")
    else:
        (root / "core/extra-directory").mkdir()
    result = subprocess.run([sys.executable, *args], cwd=root.parent,
                            env=child_environment(sys.executable), capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and not result.stdout
    assert "Snapshot" in result.stderr


def test_frozen_lock_rejects_stale_interpreter_versions(package, tmp_path):
    # The installed test pytest distribution exists, but this impossible lock
    # version must fail BEFORE the fixture's core module is executed.
    (package / "requirements-engine.lock").write_text("pytest==0.0.0 --hash=sha256:" + "a" * 64 + "\n")
    root = create_engine_snapshot(package, new_job(tmp_path))
    manifest = json.loads((root / engine_snapshot.MANIFEST_NAME).read_bytes())
    assert manifest["locked_dependencies"] == {"pytest": "0.0.0"}
    result = run(root)
    assert result.returncode != 0 and not result.stdout
    assert "do not match the frozen lock" in result.stderr


def test_nested_requirement_bytes_and_pins_are_frozen(package, tmp_path):
    (package / "requirements-engine.lock").write_bytes(b"-r locks/nested.lock\n")
    (package / "locks").mkdir()
    nested = b"tiny-package==1.2 \\\n --hash=sha256:" + b"a" * 64 + b"\n"
    (package / "locks/nested.lock").write_bytes(nested)
    root = create_engine_snapshot(package, new_job(tmp_path))
    manifest = json.loads((root / engine_snapshot.MANIFEST_NAME).read_bytes())
    assert (root / "locks/nested.lock").read_bytes() == nested
    assert manifest["locked_dependencies"] == {"tiny-package": "1.2"}


@pytest.mark.parametrize("bad_lock", ["# empty lock\n", "-r cyclic.lock\n"])
def test_empty_or_cyclic_locks_never_produce_a_ready_snapshot(package, tmp_path, bad_lock):
    (package / "requirements-engine.lock").write_text(bad_lock)
    (package / "cyclic.lock").write_text("-r requirements-engine.lock\n")
    job = new_job(tmp_path)
    with pytest.raises(SnapshotError, match="pins|Cyclic"):
        create_engine_snapshot(package, job)
    assert not (job / "engine_source").exists()


@pytest.mark.parametrize("limit", ["file", "total", "count"])
def test_limits_remove_only_new_snapshot_and_preserve_caller_files(package, tmp_path, monkeypatch, limit):
    job = new_job(tmp_path)
    (job / "canary").write_bytes(b"caller-owned")
    if limit == "file":
        (package / "core/oversized.py").write_bytes(b"x" * (engine_snapshot.MAX_FILE_BYTES + 1))
    elif limit == "total":
        monkeypatch.setattr(engine_snapshot, "MAX_TOTAL_BYTES", 5)
    else:
        monkeypatch.setattr(engine_snapshot, "MAX_FILES", 2)
    with pytest.raises(SnapshotError):
        create_engine_snapshot(package, job)
    assert list(job.iterdir()) == [job / "canary"]
    assert (job / "canary").read_bytes() == b"caller-owned"
    assert (package / "metadata.txt").exists()


@pytest.mark.parametrize("mutation", ["bytes", "new_file", "cancel"])
def test_concurrent_source_change_or_cancellation_does_not_publish(package, tmp_path, monkeypatch, mutation):
    original = engine_snapshot._read_source
    fired = False
    token = CancellationToken()
    def mutate(path, cancellation_token=None):
        nonlocal fired
        data = original(path, cancellation_token)
        if path.name == "later.py" and not fired:
            fired = True
            if mutation == "bytes":
                path.write_bytes(b"VALUE='changed'\n")
            elif mutation == "new_file":
                (path.parent / "new.py").write_bytes(b"new source")
            else:
                token.cancel()
        return data
    monkeypatch.setattr(engine_snapshot, "_read_source", mutate)
    job = new_job(tmp_path)
    with pytest.raises(CancelledError if mutation == "cancel" else SnapshotError):
        create_engine_snapshot(package, job, token)
    assert fired and not (job / "engine_source").exists()


def test_existing_destination_and_overlapping_source_are_never_overwritten(package, tmp_path):
    job = new_job(tmp_path)
    target = job / "engine_source"
    target.mkdir()
    (target / "canary").write_bytes(b"existing snapshot")
    with pytest.raises(FileExistsError):
        create_engine_snapshot(package, job)
    assert (target / "canary").read_bytes() == b"existing snapshot"
    with pytest.raises(SnapshotError, match="overlap"):
        create_engine_snapshot(package, package)
    with pytest.raises(SnapshotError, match="overlap"):
        create_engine_snapshot(package, tmp_path)


@pytest.mark.parametrize("role", ["source_file", "source_directory", "destination"])
def test_symlinks_are_refused_before_copy_or_execution(package, tmp_path, role):
    job = new_job(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "canary").write_bytes(b"do not delete")
    link = package / "core/pypoprf/later.py" if role == "source_file" else package / "core/foreign" if role == "source_directory" else job / "engine_source"
    if role == "source_file":
        link.unlink()
    try:
        link.symlink_to(foreign / "canary" if role == "source_file" else foreign, target_is_directory=role != "source_file")
    except OSError:
        pytest.skip("This Windows user cannot create symlinks")
    with pytest.raises(SnapshotError, match="links"):
        create_engine_snapshot(package, job)
    assert (foreign / "canary").read_bytes() == b"do not delete"


def test_real_current_package_snapshot_runs_analysis_help_without_live_source(tmp_path):
    job = new_job(tmp_path)
    root = create_engine_snapshot(ROOT, job)
    result = run(root, arguments=["--help"])
    assert result.returncode == 0, result.stderr
    assert "--config" in result.stdout and not list(root.rglob("__pycache__"))


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows source CWD lock")
def test_snapshot_child_does_not_pin_original_plugin_folder(package, tmp_path):
    root = create_engine_snapshot(package, new_job(tmp_path))
    # Only fixture source is deleted; the real backend source is never mutated.
    shutil.rmtree(package)
    result = run(root)
    assert result.returncode == 0 and not package.exists(), result.stderr


def test_parent_identity_change_before_creation_never_writes_replacement_job(package, tmp_path, monkeypatch):
    job = new_job(tmp_path)
    old = tmp_path / "old-owned-job"
    original = engine_snapshot._inventory
    def replace_parent(*args, **kwargs):
        result = original(*args, **kwargs)
        job.rename(old)
        job.mkdir()
        (job / "foreign-canary").write_bytes(b"new identity")
        return result
    monkeypatch.setattr(engine_snapshot, "_inventory", replace_parent)
    with pytest.raises(SnapshotError, match="ownership changed"):
        create_engine_snapshot(package, job)
    assert list(job.iterdir()) == [job / "foreign-canary"]
    assert old.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junction boundary")
@pytest.mark.parametrize("role", ["source", "during_copy"])
def test_real_junction_refusal_preserves_foreign_tree(package, tmp_path, monkeypatch, role):
    job = new_job(tmp_path)
    foreign = tmp_path / "foreign-directory"
    foreign.mkdir()
    (foreign / "canary").write_bytes(b"never copy/delete here")
    def junction(link):
        assert link.is_relative_to(tmp_path) and foreign.is_relative_to(tmp_path)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(foreign)],
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        assert link.is_junction()
    if role == "source":
        junction(package / "core/foreign")
    else:
        original = engine_snapshot._read_source
        def redirect_nested_destination(path, token=None):
            data = original(path, token)
            if path == package / "core/__init__.py":
                junction(job / "engine_source/core")
            return data
        monkeypatch.setattr(engine_snapshot, "_read_source", redirect_nested_destination)
    with pytest.raises(SnapshotError, match="links/junctions"):
        create_engine_snapshot(package, job)
    assert {p.name: p.read_bytes() for p in foreign.iterdir()} == {"canary": b"never copy/delete here"}
