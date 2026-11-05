"""Configuration locks are dedicated metadata, never writable input aliases."""
import importlib
import logging
import os
from pathlib import Path

import pytest

from services.config_manager import ConfigManager, ConfigError


@pytest.fixture
def project(tmp_path):
    manager = ConfigManager(logging.getLogger("dedicated-project-lock"))
    root = tmp_path / "project"
    manager.create_initial_config(str(root))
    return manager, root, root / "config.yaml.lock"


def test_hardlinked_config_lock_cannot_seed_foreign_empty_file(project, tmp_path):
    manager, root, lock = project
    protected = tmp_path / "fake-plugin"
    protected.mkdir()
    foreign = protected / "foreign.bin"
    foreign.write_bytes(b"")
    os.link(foreign, lock)
    before = Path(manager.config_path).read_bytes()
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("show_progress", True)
    assert foreign.read_bytes() == lock.read_bytes() == b""
    assert Path(manager.config_path).read_bytes() == before


@pytest.mark.parametrize("contents", [b"", b"foreign input bytes"])
def test_file_symlink_lock_is_refused_before_open_or_write(project, tmp_path, contents):
    manager, root, lock = project
    foreign = tmp_path / "foreign.bin"
    foreign.write_bytes(contents)
    try:
        lock.symlink_to(foreign)
    except OSError:
        pytest.skip("File-symlink privilege unavailable")
    before = Path(manager.config_path).read_bytes()
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("max_workers", 3)
    assert foreign.read_bytes() == contents and lock.is_symlink()
    assert Path(manager.config_path).read_bytes() == before


def test_directory_lock_is_rejected_without_config_write(project):
    manager, root, lock = project
    lock.mkdir()
    before = Path(manager.config_path).read_bytes()
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("max_workers", 3)
    assert lock.is_dir() and list(lock.iterdir()) == []
    assert Path(manager.config_path).read_bytes() == before


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
def test_nonregular_fifo_lock_is_rejected_before_blocking_open(project):
    manager, root, lock = project
    os.mkfifo(lock)
    before = Path(manager.config_path).read_bytes()
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("max_workers", 3)
    assert Path(manager.config_path).read_bytes() == before


def test_ordinary_dedicated_lock_still_serializes_sessions(project):
    first, root, lock = project
    second = ConfigManager(logging.getLogger("second-session"))
    second.open_project(str(root))
    before = Path(first.config_path).read_bytes()
    with first._mutation_lock():
        with pytest.raises(ConfigError, match="Another session"):
            second.update_config("max_workers", 3)
        assert Path(first.config_path).read_bytes() == before
    second.update_config("max_workers", 3)
    assert first.get_config()["max_workers"] == 3
    assert lock.read_bytes() == b"\0" and lock.stat().st_nlink == 1


def test_new_hardlink_after_open_is_caught_by_descriptor_check(project, tmp_path, monkeypatch):
    manager, root, lock = project
    lock.write_bytes(b"")
    foreign = tmp_path / "foreign.bin"
    before = Path(manager.config_path).read_bytes()
    module = importlib.import_module(ConfigManager.__module__)
    class LocalOS:
        def __getattr__(self, name):
            return getattr(os, name)
        def fstat(self, descriptor):
            if not foreign.exists():
                os.link(lock, foreign)
            return os.fstat(descriptor)
    monkeypatch.setattr(module, "os", LocalOS())
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("max_workers", 3)
    assert foreign.read_bytes() == lock.read_bytes() == b""
    assert Path(manager.config_path).read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="Windows open handles already deny delete sharing")
def test_replaced_path_after_open_is_caught_before_seeding(project, monkeypatch):
    manager, root, lock = project
    lock.write_bytes(b"")
    before = Path(manager.config_path).read_bytes()
    module = importlib.import_module(ConfigManager.__module__)
    replaced = []
    class LocalOS:
        def __getattr__(self, name):
            return getattr(os, name)
        def fstat(self, descriptor):
            if not replaced:
                lock.unlink()
                lock.write_bytes(b"")
                replaced.append(True)
            return os.fstat(descriptor)
    monkeypatch.setattr(module, "os", LocalOS())
    with pytest.raises(ConfigError, match="lock"):
        manager.update_config("max_workers", 3)
    assert replaced == [True] and lock.read_bytes() == b""
    assert Path(manager.config_path).read_bytes() == before
