"""Collision decisions verify bytes again and never replace an original."""
import logging
import os
import ast
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.file_handlers import FileHandler, FileHandlerError


@pytest.fixture
def inputs(tmp_path):
    project = tmp_path / "project"
    data = project / "data"
    data.mkdir(parents=True)
    source = tmp_path / "counts.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    target = data / source.name
    target.write_bytes(source.read_bytes())
    return FileHandler(str(project), logging.getLogger("collision-test")), source, target


def inspect(inputs):
    handler, source, _ = inputs
    return handler.inspect_conflict(str(source), "census_data")


def test_identical_reuse_is_explicit_and_default_still_refuses(inputs):
    handler, source, target = inputs
    conflict = inspect(inputs)
    assert conflict["identical"] and conflict["reuse_allowed"]
    with pytest.raises(FileHandlerError, match="overwrite"):
        handler.copy_to_data_dir(str(source), "census_data")
    assert handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="reuse") == target.name
    assert target.read_bytes() == source.read_bytes() == b"id,pop\n1,12\n"


def test_different_bytes_never_offer_reuse_and_separate_copy_preserves_both(inputs):
    handler, source, target = inputs
    target.write_bytes(b"id,pop\n1,99\n")
    conflict = inspect(inputs)
    assert not conflict["reuse_allowed"]
    with pytest.raises(FileHandlerError, match="verified identical"):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="reuse")
    assert handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="copy", destination_name="counts_copy.csv") == "counts_copy.csv"
    assert target.read_bytes() == b"id,pop\n1,99\n"
    assert (target.parent / "counts_copy.csv").read_bytes() == source.read_bytes()


@pytest.mark.parametrize("which", ["source", "destination"])
@pytest.mark.parametrize("action", ["reuse", "copy"])
def test_changed_file_after_decision_is_refused(inputs, which, action):
    handler, source, target = inputs
    conflict = inspect(inputs)
    changed = source if which == "source" else target
    changed.write_bytes(b"id,pop\n1,34\n")
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action=action,
                                 destination_name=target.name if action == "reuse" else "copy.csv")
    assert changed.read_bytes() == b"id,pop\n1,34\n"
    assert not (target.parent / "copy.csv").exists()


def test_identical_replacement_inode_not_reused(inputs):
    handler, source, target = inputs
    conflict = inspect(inputs)
    replacement = target.with_name("replacement.csv")
    replacement.write_bytes(target.read_bytes())
    os.replace(replacement, target)
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="reuse")


def test_source_changes_while_destination_is_hashed(inputs):
    handler, source, target = inputs
    conflict = inspect(inputs)
    calls = []
    def mutate(percent, name):
        calls.append(name)
        if len(calls) == 2:
            source.write_bytes(b"id,pop\n1,67\n")
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="reuse", progress=mutate)
    assert target.read_bytes() == b"id,pop\n1,12\n"


@pytest.mark.parametrize("name", ["../counts.csv", "CON.csv", "same.tif", " counts.csv", "a.csv."])
def test_copy_name_must_be_portable_same_extension(inputs, name):
    handler, source, target = inputs
    with pytest.raises(FileHandlerError):
        handler.copy_to_data_dir(str(source), "census_data", conflict=inspect(inputs), action="copy", destination_name=name)
    assert len(list(target.parent.iterdir())) == 1


def test_concurrent_new_copy_collision_preserves_existing_target(inputs):
    handler, source, target = inputs
    new = target.with_name("separate.csv")
    conflict = inspect(inputs)
    def collide(percent, name):
        if not new.exists():
            new.write_bytes(b"another process input")
    with pytest.raises(FileHandlerError):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="copy",
                                 destination_name=new.name, progress=collide)
    assert new.read_bytes() == b"another process input"
    assert not list(target.parent.glob(".import-*"))


def test_source_changes_during_separate_copy_are_not_published(inputs):
    handler, source, target = inputs
    conflict = inspect(inputs)
    calls = []
    def mutate(percent, name):
        calls.append(name)
        if len(calls) == 4:
            source.write_bytes(b"id,pop\n1,67\n")
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data", conflict=conflict, action="copy",
                                 destination_name="new.csv", progress=mutate)
    assert not (target.parent / "new.csv").exists()
    assert not list(target.parent.glob(".import-*"))
    assert target.read_bytes() == b"id,pop\n1,12\n"


@pytest.mark.parametrize("side", ["source", "destination"])
def test_identical_raster_bytes_with_sidecars_cannot_be_reused(tmp_path, side):
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    data = Path(handler.working_dir) / "data"
    data.mkdir(parents=True)
    source, target = tmp_path / "zones.tif", data / "zones.tif"
    source.write_bytes(b"raster bytes"); target.write_bytes(source.read_bytes())
    Path(str(source if side == "source" else target) + ".msk").write_bytes(b"mask")
    conflict = handler.inspect_conflict(str(source), "mastergrid")
    assert conflict["identical"] and not conflict["reuse_allowed"]
    with pytest.raises(FileHandlerError):
        handler.copy_to_data_dir(str(source), "mastergrid", conflict=conflict, action="reuse")
    assert target.read_bytes() == b"raster bytes"


def test_sidecar_created_after_choice_prevents_reuse(tmp_path):
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    data = Path(handler.working_dir) / "data"; data.mkdir(parents=True)
    source, target = tmp_path / "zones.tif", data / "zones.tif"
    source.write_bytes(b"raster bytes"); target.write_bytes(source.read_bytes())
    conflict = handler.inspect_conflict(str(source), "mastergrid")
    Path(str(target) + ".aux.xml").write_bytes(b"metadata")
    with pytest.raises(FileHandlerError, match="external mask"):
        handler.copy_to_data_dir(str(source), "mastergrid", conflict=conflict, action="reuse")


def test_file_symlink_refused_before_hash(inputs, tmp_path):
    handler, source, target = inputs
    alias = tmp_path / "alias.csv"
    try:
        alias.symlink_to(source)
    except OSError:
        pytest.skip("Symbolic links unavailable")
    with pytest.raises(FileHandlerError, match="aliases"):
        handler.inspect_conflict(str(alias), "census_data")
    assert target.read_bytes() == source.read_bytes()


def test_hash_cancellation_is_cooperative_and_writes_nothing(inputs):
    handler, source, target = inputs
    class Token:
        def check(self):
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        handler.inspect_conflict(str(source), "census_data", Token())
    assert target.read_bytes() == source.read_bytes()
    assert len(list(target.parent.iterdir())) == 1


def test_age_sex_role_uses_supported_headers_and_configured_id(inputs):
    handler, source, target = inputs
    with pytest.raises(FileHandlerError, match="regular population table"):
        handler.inspect_conflict(str(source), "agesex_data")
    source.write_bytes(b"zone,f_0_4,m_65+\n1,2,3\n")
    target.write_bytes(source.read_bytes())
    conflict = handler.inspect_conflict(str(source), "agesex_data", id_column="zone")
    assert conflict["headers"] == ["zone", "f_0_4", "m_65+"]


def test_first_census_import_allows_custom_id_before_mapping(tmp_path):
    source = tmp_path / "census.csv"
    source.write_bytes(b"zone_code,total_population\n1,20\n")
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("test"))
    assert handler.copy_to_data_dir(str(source), "census_data") == source.name
    assert (tmp_path / "project/data/census.csv").read_bytes() == source.read_bytes()


def test_age_column_pattern_tracks_core_contract_without_importing_engine():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "core/pypoprf/algorithms/dasymetric.py").read_text(encoding="utf-8"))
    core_pattern = next(ast.literal_eval(node.value.args[0]) for node in ast.walk(tree)
                        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                        and target.id == "AGE_COLUMN" for target in node.targets))
    service_tree = ast.parse((root / "services/file_handlers.py").read_text(encoding="utf-8"))
    preview_patterns = [ast.literal_eval(node.args[0]) for node in ast.walk(service_tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "fullmatch"]
    assert core_pattern.removeprefix("^").removesuffix("$") in preview_patterns


def test_first_import_rejects_same_size_source_mutation_with_restored_mtime(tmp_path):
    source = tmp_path / "census.csv"
    original = b"id,pop\n" + b"".join(f"{i},1\n".encode() for i in range(1, 200001))
    changed = original.replace(b",1\n", b",2\n")
    assert len(original) == len(changed) and len(original) > 1024 * 1024
    source.write_bytes(original)
    metadata = source.stat()
    project = tmp_path / "project"
    handler = FileHandler(str(project), logging.getLogger("first-import-snapshot"))
    mutations = []
    def mutate_copy(percent, name):
        # Ignore pre-verification progress: change while the actual staged copy
        # is in progress, using real filesystem metadata rather than stat fakes.
        if not mutations and list((project / "data").glob(".import-*.tmp")):
            source.write_bytes(changed)
            os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            mutations.append(True)
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data", progress=mutate_copy)
    assert mutations == [True]
    assert source.read_bytes() == changed
    assert not (project / "data" / source.name).exists()
    assert not list((project / "data").glob(".import-*.tmp"))


def test_first_import_without_progress_verifies_its_source_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "census.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    metadata = source.stat()
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("first-copy2-snapshot"))
    fingerprint = handler._fingerprint
    def change_after_snapshot(path, *args, **kwargs):
        info = fingerprint(path, *args, **kwargs)
        if path == source:
            source.write_bytes(b"id,pop\n1,99\n")
            os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        return info
    monkeypatch.setattr(handler, "_fingerprint", change_after_snapshot)
    with pytest.raises(FileHandlerError, match="changed"):
        handler.copy_to_data_dir(str(source), "census_data")
    assert source.read_bytes() == b"id,pop\n1,99\n"
    assert list((tmp_path / "project/data").iterdir()) == []


@pytest.mark.parametrize("phase", ["source-before", "staging", "source-after"])
def test_all_first_import_verification_passes_are_cancellable(tmp_path, monkeypatch, phase):
    source = tmp_path / "large.tif"
    original = b"x" * (2 * 1024 * 1024)
    source.write_bytes(original)
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("cancel-verification"))
    class Token:
        cancelled = False
        def check(self):
            if self.cancelled:
                raise RuntimeError("cancelled during verification")
    token = Token()
    fingerprint, observed = handler._fingerprint, []
    def verify(path, cancellation_token=None, progress=None):
        observed.append("source-before" if path == source and not observed else
                        "source-after" if path == source else "staging")
        if observed[-1] == phase:
            def cancel(percent, name):
                token.cancelled = True
            progress = cancel
        return fingerprint(path, cancellation_token, progress)
    monkeypatch.setattr(handler, "_fingerprint", verify)
    with pytest.raises(FileHandlerError, match="cancelled"):
        handler.copy_to_data_dir(str(source), "mastergrid", cancellation_token=token)
    assert phase in observed and token.cancelled
    assert source.read_bytes() == original
    assert list((tmp_path / "project/data").iterdir()) == []


def test_source_disappearing_after_staging_creation_leaves_no_pending_file(tmp_path, monkeypatch):
    source = tmp_path / "census.csv"
    source.write_bytes(b"id,pop\n1,12\n")
    handler = FileHandler(str(tmp_path / "project"), logging.getLogger("missing-source"))
    module = importlib.import_module(FileHandler.__module__)
    mkstemp = module.tempfile.mkstemp
    def create_then_remove(*args, **kwargs):
        result = mkstemp(*args, **kwargs)
        source.unlink()
        return result
    monkeypatch.setattr(module, "tempfile", SimpleNamespace(mkstemp=create_then_remove))
    with pytest.raises(FileHandlerError, match="No such file|cannot find|not find"):
        handler.copy_to_data_dir(str(source), "census_data")
    assert list((tmp_path / "project/data").iterdir()) == []
