import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG = {
    "data_dir": "data",
    "output_dir": "output",
    "mastergrid": None,
    "mask": None,
    "covariates": {},
    "constrain": None,
    "census_data": None,
    "agesex_data": None,
    "census_pop_column": "pop",
    "census_id_column": "id",
    "by_block": True,
    "block_size": [512, 512],
    "max_workers": 1,
    "show_progress": False,
    "logging": {"level": "INFO", "file": "logs_pypoprf.log"},
}


class ConfigError(Exception):
    """Custom exception for configuration related errors."""

    pass


class ConfigManager:
    """Manager for handling YAML configuration file.

    This class provides thread-safe operations for reading and writing
    configuration settings for the pypopRF plugin.

    Attributes:
        logger: Logger instance for output messages
        config_path: Path to configuration file
        working_dir: Current working directory
        _lock: Thread lock for safe file operations
    """

    def __init__(self, logger):
        """Initialize ConfigManager.

        Args:
            logger: Logger instance for output messages
        """

        self.logger = logger
        self.config_path = None
        self.working_dir = None
        self._lock = threading.Lock()

    @contextmanager
    def _open_config(self, mode="r"):
        """Context manager for safe config file operations.

        Args:
            mode: File open mode ('r' or 'w')

        Raises:
            ConfigError: If config path is not set or file operation fails
        """

        if not self.config_path:
            raise ConfigError("Configuration path not set")

        try:
            with self._lock:
                with open(self.config_path, mode) as f:
                    yield f
        except Exception as e:
            raise ConfigError(f"Config file operation failed: {str(e)}")

    def create_initial_config(self, working_dir: str) -> bool:
        """Create initial configuration file.

        Args:
            working_dir: Working directory path

        Returns:
            bool: True if successful

        Raises:
            ConfigError: If configuration creation fails
        """
        try:
            self.working_dir = working_dir
            config_path = Path(working_dir) / "config.yaml"
            self.config_path = str(config_path)

            # Create output directory
            output_dir = Path(working_dir) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Setup log file
            log_file = output_dir / "logs_pypoprf.log"
            self._setup_log_file(log_file)

            # Create config
            config = DEFAULT_CONFIG.copy()
            config["work_dir"] = str(working_dir)

            with self._open_config("w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self.logger.info(f"Created config at {config_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create config: {str(e)}")
            raise ConfigError(f"Configuration creation failed: {str(e)}")

    def update_config(self, key: str, value: Any):
        """Update configuration value.

        Args:
            key: Configuration key to update
            value: New value

        Raises:
            ConfigError: If update fails
        """
        try:
            with self._open_config("r") as f:
                config = yaml.safe_load(f)
            if key.startswith("covariate_"):
                name = key.replace("covariate_", "")
                config["covariates"][name] = value
                self.logger.info(f"Added covariate '{name}': {value}")
            else:
                config[key] = value
                if key not in ["logging", "census_id_column", "census_pop_column"]:
                    self.logger.info(f"Updated {key}: {value}")
            with self._open_config("w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            raise ConfigError(f"Configuration update failed: {str(e)}")

    def _setup_log_file(self, log_file: Path) -> None:
        """Setup log file with proper error handling.

        Args:
            log_file: Path to log file

        Raises:
            ConfigError: If log file setup fails
        """
        try:
            if log_file.exists():
                log_file.write_text("")
                self.logger.info("Previous log file cleared")
            else:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_file.touch()
                self.logger.info("New log file created")
        except Exception as e:
            raise ConfigError(f"Log file setup failed: {str(e)}")

    def get_config(self) -> Dict[str, Any]:
        """Get current configuration.

        Returns:
            Dict containing current configuration

        Raises:
            ConfigError: If configuration cannot be read
        """
        try:
            with self._open_config("r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise ConfigError(f"Failed to read configuration: {str(e)}")

    def clear_config_value(self, key: str):
        """Clear configuration value (set to null).

        Args:
            key: Configuration key to clear

        Raises:
            ConfigError: If clear operation fails
        """
        if not self.config_path:
            return

        try:
            config = self.get_config()
            if key.startswith("covariate_"):
                name = key.replace("covariate_", "")
                if name in config["covariates"]:
                    del config["covariates"][name]
            else:
                config[key] = None
                self.logger.info(f"Cleared {key} in config")

            with self._open_config("w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        except Exception as e:
            raise ConfigError(f"Failed to clear config value: {str(e)}")
