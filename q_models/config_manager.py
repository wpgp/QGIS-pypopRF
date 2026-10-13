"""Atomic project configuration. Opening existing projects is read-only."""
import copy
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import yaml
from ..atomic_files import atomic_replace

DEFAULT_CONFIG = {
    "data_dir": "data", "output_dir": "output", "mastergrid": None,
    "mask": None, "covariates": {}, "constrain": None, "census_data": None,
    "agesex_data": None, "census_pop_column": "pop", "census_id_column": "id",
    "by_block": True, "block_size": [512, 512], "max_workers": 1,
    "show_progress": False, "log_scale": True, "selection_threshold": 0.01,
    "logging": {"level": "INFO", "file": "logs_pypoprf.log"},
}


class ConfigError(ValueError):
    pass


def validate_log_filename(filename):
    """Accept only portable .log basenames, never input/config paths."""
    if (not isinstance(filename, str) or not filename.strip()
            or filename != filename.strip() or "/" in filename or "\\" in filename
            or ":" in filename or Path(filename).suffix.lower() != ".log"
            or any(char in filename for char in '<>"|?*')
            or any(ord(char) < 32 for char in filename)):
        raise ConfigError("Log filename must be a plain filename ending in .log")
    device = filename.split(".", 1)[0].upper()
    if device in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                  *(f"LPT{i}" for i in range(1, 10))}:
        raise ConfigError("Log filename cannot be a reserved device name")
    return filename


class ConfigManager:
    def __init__(self, logger):
        self.logger = logger
        self.config_path = None
        self.working_dir = None
        self._lock = threading.RLock()

    def create_initial_config(self, working_dir):
        root = Path(working_dir).resolve()
        path = root / "config.yaml"
        if path.exists():
            raise ConfigError("Project already exists; open it instead")
        root.mkdir(parents=True, exist_ok=True)
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["work_dir"] = str(root)
        descriptor, pending_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=root)
        pending = Path(pending_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                yaml.safe_dump(config, stream, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Exclusive atomic publication; never expose a half-written config.
            try:
                os.link(pending, path)
            except FileExistsError:
                raise
            except OSError:
                if os.name != "nt":
                    raise
                os.rename(pending, path)
        finally:
            pending.unlink(missing_ok=True)
        self.working_dir, self.config_path = str(root), str(path)
        (root / "data").mkdir(exist_ok=True)
        self.logger.info(f"Created project: {root}")
        return True

    def open_project(self, working_dir):
        root = Path(working_dir).resolve()
        path = root / "config.yaml"
        with path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        self.validate_ui_config(config)
        # Snapshot root is the selected project; moving a folder is supported.
        self.working_dir, self.config_path = str(root), str(path)
        return config

    @staticmethod
    def validate_ui_config(config):
        """Validate saved UI state without requiring a finished input setup."""
        if not isinstance(config, dict) or set(DEFAULT_CONFIG) - config.keys():
            raise ConfigError("Project configuration is missing required settings")
        if not isinstance(config["covariates"], dict) or any(
                not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v
                for k, v in config["covariates"].items()):
            raise ConfigError("Covariates must map nonempty names to filenames")
        for name in ("data_dir", "output_dir", "census_pop_column", "census_id_column"):
            if not isinstance(config[name], str) or not config[name].strip():
                raise ConfigError(f"Invalid project setting: {name}")
        for name in ("mastergrid", "mask", "constrain", "census_data", "agesex_data"):
            if config[name] is not None and not isinstance(config[name], str):
                raise ConfigError(f"Invalid input filename: {name}")
        for name in ("by_block", "show_progress", "log_scale"):
            if not isinstance(config[name], bool):
                raise ConfigError(f"Invalid boolean setting: {name}")
        workers = config["max_workers"]
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ConfigError("max_workers must be a positive integer")
        size = config["block_size"]
        if (not isinstance(size, (list, tuple)) or len(size) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) or v < 16 or v % 16 for v in size)):
            raise ConfigError("block_size must contain two positive multiples of 16")
        threshold = config["selection_threshold"]
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or threshold < 0):
            raise ConfigError("selection_threshold must be finite and nonnegative")
        logging = config["logging"]
        if not isinstance(logging, dict) or logging.get("level") not in {
                "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("Invalid logging level")
        validate_log_filename(logging.get("file"))

    def get_config(self):
        if not self.config_path:
            raise ConfigError("Configuration path not set")
        with self._lock:
            with Path(self.config_path).open(encoding="utf-8") as stream:
                config = yaml.safe_load(stream)
            if not isinstance(config, dict):
                raise ConfigError("Configuration must be a mapping")
            return config

    def _write_config(self, config):
        path = Path(self.config_path)
        # Same-directory replace avoids truncating a valid config on failures.
        descriptor, name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                yaml.safe_dump(config, stream, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def update_many(self, values):
        with self._mutation_lock():
            config = self.get_config()
            config.update(values)
            self._write_config(config)

    def update_config(self, key, value):
        with self._mutation_lock():
            config = self.get_config()
            if key.startswith("covariate_"):
                config.setdefault("covariates", {})[key[len("covariate_"):]] = value
            else:
                config[key] = value
            self._write_config(config)

    def clear_config_value(self, key):
        if not self.config_path:
            return
        with self._mutation_lock():
            config = self.get_config()
            if key.startswith("covariate_"):
                config.setdefault("covariates", {}).pop(key[len("covariate_"):], None)
            else:
                config[key] = None
            self._write_config(config)

    @contextmanager
    def _mutation_lock(self):
        """Serialize full updates across plugin instances without blocking the UI."""
        with self._lock:
            if not self.config_path:
                raise ConfigError("Configuration path not set")
            path = Path(self.config_path).with_suffix(".yaml.lock")
            with path.open("a+b") as stream:
                if stream.seek(0, os.SEEK_END) == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ConfigError("Another session is updating this project; retry after it finishes") from exc
                try:
                    yield
                finally:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
