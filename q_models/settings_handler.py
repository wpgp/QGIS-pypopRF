# -*- coding: utf-8 -*-
from qgis.PyQt import QtWidgets, QtCore

import yaml


class SettingsHandler:
    """Handler for processing settings in QGIS plugin"""

    def __init__(self, config_manager, logger):
        """
        Initialize SettingsHandler.

        Args:
            config_manager: ConfigManager instance
            logger: Logger instance for output messages
        """
        self.config_manager = config_manager
        self.logger = logger

    def load_settings(self, dialog):
        """
        Load settings from config to dialog.

        Args:
            dialog: Main dialog instance
        """
        try:
            with open(self.config_manager.config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Load logging settings
            if 'logging' in config:
                dialog.saveLogCheckBox.setChecked(bool(config['logging'].get('file')))
                if config['logging'].get('file'):
                    dialog.logsColumnEdit.setText(config['logging']['file'])
                if 'level' in config['logging']:
                    index = dialog.comboBox.findText(config['logging']['level'])
                    if index >= 0:
                        dialog.comboBox.setCurrentIndex(index)

            # Load processing settings
            dialog.enableParallelCheckBox.setChecked(config['max_workers'] > 0)
            dialog.cpuCoresComboBox.setCurrentText(str(config['max_workers']))

            dialog.enableBlockProcessingCheckBox.setChecked(config.get('by_block', True))
            block_size = f"{config['block_size'][0]},{config['block_size'][1]}"
            index = dialog.blockSizeComboBox.findText(block_size)
            if index >= 0:
                dialog.blockSizeComboBox.setCurrentIndex(index)
            else:
                dialog.blockSizeComboBox.setCurrentText(block_size)

            # Load census settings
            dialog.popColumnEdit.setText(config['census_pop_column'])
            dialog.idColumnEdit.setText(config['census_id_column'])

            self.logger.info("Settings loaded successfully")

        except Exception as e:
            self.logger.error(f"Failed to load settings: {str(e)}")

    def save_settings(self, dialog):
        """
        Save settings from dialog to config.

        Args:
            dialog: Main dialog instance
        """
        try:
            settings = {
                'logging': {
                    'level': dialog.comboBox.currentText(),
                    'file': 'pypoprf.log'
                },
                'max_workers': int(dialog.cpuCoresComboBox.currentText()),
                'by_block': dialog.enableBlockProcessingCheckBox.isChecked(),
                'census_pop_column': dialog.popColumnEdit.text(),
                'census_id_column': dialog.idColumnEdit.text()
            }

            # Handle block size
            block_size_text = dialog.blockSizeComboBox.currentText()
            try:
                w, h = map(int, block_size_text.split(','))
                settings['block_size'] = [w, h]
            except ValueError:
                self.logger.warning("Invalid block size format, using default 512,512")
                settings['block_size'] = [512, 512]

            for key, value in settings.items():
                self.config_manager.update_config(key, value)

            self.logger.info("Settings saved successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save settings: {str(e)}")
            return False

    def _debounce_settings_update(self, dialog, setting_key, value):
        if not hasattr(dialog, '_settings_update_timer'):
            dialog._settings_update_timer = QtCore.QTimer()
            dialog._settings_update_timer.setSingleShot(True)

        if not hasattr(dialog, '_pending_updates'):
            dialog._pending_updates = {}

        dialog._pending_updates[setting_key] = value

        if not dialog._settings_update_timer.isActive():
            dialog._settings_update_timer.timeout.connect(
                lambda: self._apply_pending_updates(dialog)
            )
            dialog._settings_update_timer.start(1500)

    def _apply_pending_updates(self, dialog):

        if hasattr(dialog, '_pending_updates'):
            for key, value in dialog._pending_updates.items():
                if key == 'logging':
                    dialog.config_manager.update_config('logging', {
                        'level': dialog.comboBox.currentText(),
                        'file': value
                    })
                elif key == 'census':
                    dialog.config_manager.update_config('census_pop_column', dialog.popColumnEdit.text())
                    dialog.config_manager.update_config('census_id_column', dialog.idColumnEdit.text())

                if key == 'logging':
                    dialog.console_handler.update_logging_settings(
                        level=dialog.comboBox.currentText(),
                        save_log=dialog.saveLogCheckBox.isChecked(),
                        work_dir=dialog.workingDirEdit.filePath(),
                        filename=value
                    )

            dialog._pending_updates.clear()

    def validate_settings(self, dialog) -> bool:
        """
        Validate current settings.

        Args:
            dialog: Main dialog instance

        Returns:
            bool: True if settings are valid
        """
        try:
            # Validate census columns
            pop_column = dialog.popColumnEdit.text().strip()
            id_column = dialog.idColumnEdit.text().strip()

            if not pop_column:
                self.logger.error("Population column name cannot be empty")
                return False
            if not id_column:
                self.logger.error("ID column name cannot be empty")
                return False

            # Validate parallel processing
            if dialog.enableParallelCheckBox.isChecked():
                try:
                    cores = int(dialog.cpuCoresComboBox.currentText())
                    if cores <= 0:
                        self.logger.error("Number of CPU cores must be positive")
                        return False
                except ValueError:
                    self.logger.error("Invalid number of CPU cores")
                    return False

            # Validate block size
            if dialog.enableBlockProcessingCheckBox.isChecked():
                try:
                    w, h = map(int, dialog.blockSizeComboBox.currentText().split(','))
                    if w <= 0 or h <= 0:
                        self.logger.error("Block size dimensions must be positive")
                        return False
                except ValueError:
                    self.logger.error("Invalid block size format (should be width,height)")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Settings validation failed: {str(e)}")
            return False
