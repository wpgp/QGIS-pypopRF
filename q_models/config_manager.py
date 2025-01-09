# -*- coding: utf-8 -*-
import yaml
from pathlib import Path


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
                'block_size': [512, 512],
                'max_workers': 8,
                'show_progress': True
            }

            with open(config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self.logger.info(f"Created config at {config_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create config: {str(e)}")
            return False

    def update_config(self, key: str, value: str):
        """
        Update configuration value.

        Args:
            key: Configuration key to update
            value: New value
        """

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        if key.startswith('covariate_'):
            name = key.replace('covariate_', '')
            config['covariates'][name] = value
            self.logger.info(f"Added covariate '{name}': {value}")
        else:
            config[key] = value
            self.logger.info(f"Updated {key}: {value}")

        with open(self.config_path, 'w') as f:
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
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            if key.startswith('covariate_'):
                name = key.replace('covariate_', '')
                if name in config['covariates']:
                    del config['covariates'][name]
            else:
                config[key] = None
                self.logger.info(f"Cleared {key} in config")

            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        except Exception as e:
            self.logger.error(f"Failed to clear config value: {str(e)}")
