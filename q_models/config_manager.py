import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


class ConfigManager:
    """Manager for handling YAML configuration file"""

    def __init__(self, logger):
        """
        Initialize ConfigManager.

        Args:
            logger: Logger instance for output messages
        """
        self.logger = logger
        self.config_path = None
        self.working_dir = None
        self._lock = threading.Lock()

    @contextmanager
    def _open_config(self, mode='r'):
        """Context manager для безопасной работы с конфигом"""
        with self._lock:
            with open(self.config_path, mode) as f:
                yield f

    def create_initial_config(self, working_dir: str) -> bool:
        """
        Create initial configuration file.

        Args:
            working_dir: Working directory path

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.working_dir = working_dir
            config_path = Path(working_dir) / 'config.yaml'
            self.config_path = str(config_path)

            output_dir = Path(working_dir) / 'output'
            output_dir.mkdir(parents=True, exist_ok=True)

            log_file = output_dir / 'logs_pypoprf.log'

            try:
                if log_file.exists():
                    with open(log_file, 'w') as f:
                        pass
                    self.logger.info("Previous log file cleared")
                else:
                    log_file.parent.mkdir(parents=True, exist_ok=True)
                    log_file.touch()
                    self.logger.info("New log file created")
            except Exception as e:
                self.logger.warning(f"Issue with log file handling: {str(e)}")

            config = {
                'work_dir': str(working_dir),
                'data_dir': 'data',
                'output_dir': 'output',
                'mastergrid': None,
                'mask': None,
                'covariates': {},
                'constrain': None,
                'census_data': None,
                'census_pop_column': 'pop',
                'census_id_column': 'id',
                'by_block': True,
                'block_size': [256, 256],
                'max_workers': 8,
                'show_progress': False,
                'logging': {
                    'level': 'INFO',
                    'file': 'logs_pypoprf.log'
                }
            }

            with self._open_config('w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self.logger.info(f"Created config at {config_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create config: {str(e)}")
            return False

    def update_config(self, key: str, value: Any):
        """
        Update configuration value.

        Args:
            key: Configuration key to update
            value: New value
        """

        with self._open_config('r') as f:
            config = yaml.safe_load(f)
        if key.startswith('covariate_'):
            name = key.replace('covariate_', '')
            config['covariates'][name] = value
            self.logger.info(f"Added covariate '{name}': {value}")
        else:
            config[key] = value
            if key not in ['logging', 'census_id_column', 'census_pop_column']:
                self.logger.info(f"Updated {key}: {value}")
        with self._open_config('w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    def clear_config_value(self, key: str):
        """
        Clear configuration value (set to null).

        Args:
            key: Configuration key to clear
        """
        if not self.config_path:
            return

        try:
            with self._open_config('r') as f:
                config = yaml.safe_load(f)
            if key.startswith('covariate_'):
                name = key.replace('covariate_', '')
                if name in config['covariates']:
                    del config['covariates'][name]
            else:
                config[key] = None
                self.logger.info(f"Cleared {key} in config")

            with self._open_config('w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        except Exception as e:
            self.logger.error(f"Failed to clear config value: {str(e)}")
