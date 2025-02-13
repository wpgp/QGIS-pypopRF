from logging import Logger
from typing import Any, Optional

import yaml


class SettingsError(Exception):
    """Custom exception for settings-related errors."""

    pass


class SettingsHandler:
    """Handler for processing settings in QGIS plugin.

    Manages loading, saving, and validation of plugin settings,
    including logging configuration and processing parameters.

    Attributes:
        config_manager: ConfigManager instance
        logger: Logger instance
        _pending_log_filename: Temporary storage for log filename changes
        _pending_pop_column: Temporary storage for population column changes
        _pending_id_column: Temporary storage for ID column changes
    """

    def __init__(self, config_manager: Any, logger: Logger) -> None:
        """Initialize SettingsHandler.

        Args:
            config_manager: ConfigManager instance
            logger: Logger instance

        Raises:
            SettingsError: If initialization fails
        """
        self.config_manager = config_manager
        self.logger = logger
        self._pending_log_filename: Optional[str] = None
        self._pending_pop_column: Optional[str] = None
        self._pending_id_column: Optional[str] = None

    def connect_log_filename_signals(self, dialog) -> None:
        """Connect signals for log filename input.

        Args:
            dialog: Main dialog instance
        """
        dialog.logsColumnEdit.textChanged.connect(
            lambda text: setattr(self, "_pending_log_filename", text)
        )
        dialog.logsColumnEdit.editingFinished.connect(
            lambda: self._apply_log_filename_update(dialog)
        )

    def connect_census_fields_signals(self, dialog):
        """Connect signals for census fields input."""
        # Для поля population
        dialog.popColumnEdit.textChanged.connect(
            lambda text: setattr(self, "_pending_pop_column", text)
        )
        dialog.popColumnEdit.editingFinished.connect(lambda: self._apply_census_update())

        # Для поля id
        dialog.idColumnEdit.textChanged.connect(
            lambda text: setattr(self, "_pending_id_column", text)
        )
        dialog.idColumnEdit.editingFinished.connect(lambda: self._apply_census_update())

    def _apply_log_filename_update(self, dialog) -> None:
        """Apply log filename changes when editing is finished.

        Args:
            dialog: Main dialog instance

        Raises:
            SettingsError: If update fails
        """
        try:
            if self._pending_log_filename is not None:
                self.config_manager.update_config(
                    "logging",
                    {
                        "level": dialog.comboBox.currentText(),
                        "file": self._pending_log_filename,
                    },
                )

                dialog.console_handler.update_logging_settings(
                    level=dialog.comboBox.currentText(),
                    save_log=True,
                    work_dir=dialog.workingDirEdit.filePath(),
                    filename=self._pending_log_filename,
                )

                self._pending_log_filename = None
        except Exception as e:
            raise SettingsError(f"Failed to update log filename: {str(e)}")

    def _apply_census_update(self):
        """Apply census fields changes when editing is finished."""
        if hasattr(self, "_pending_pop_column") and self._pending_pop_column is not None:
            self.config_manager.update_config("census_pop_column", self._pending_pop_column)
            self._pending_pop_column = None

        if hasattr(self, "_pending_id_column") and self._pending_id_column is not None:
            self.config_manager.update_config("census_id_column", self._pending_id_column)
            self._pending_id_column = None

    def load_settings(self, dialog):
        """
        Load settings from config to dialog.

        Args:
            dialog: Main dialog instance
        """
        try:
            with open(self.config_manager.config_path, "r") as f:
                config = yaml.safe_load(f)

            # Load logging settings
            if "logging" in config:
                if config["logging"].get("file"):
                    dialog.logsColumnEdit.setText(config["logging"]["file"])
                if "level" in config["logging"]:
                    index = dialog.comboBox.findText(config["logging"]["level"])
                    if index >= 0:
                        dialog.comboBox.setCurrentIndex(index)

            # Load processing settings
            dialog.enableParallelCheckBox.setChecked(True)

            dialog.enableBlockProcessingCheckBox.setChecked(config.get("by_block", True))
            block_size = f"{config['block_size'][0]},{config['block_size'][1]}"
            index = dialog.blockSizeComboBox.findText(block_size)
            if index >= 0:
                dialog.blockSizeComboBox.setCurrentIndex(index)
            else:
                dialog.blockSizeComboBox.setCurrentText(block_size)

            # Load census settings
            dialog.popColumnEdit.setText(config["census_pop_column"])
            dialog.idColumnEdit.setText(config["census_id_column"])

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
                "logging": {"level": dialog.comboBox.currentText(), "file": "pypoprf.log"},
                "max_workers": int(dialog.cpuCoresComboBox.currentText()),
                "by_block": dialog.enableBlockProcessingCheckBox.isChecked(),
                "census_pop_column": dialog.popColumnEdit.text(),
                "census_id_column": dialog.idColumnEdit.text(),
            }

            # Handle block size
            block_size_text = dialog.blockSizeComboBox.currentText()
            try:
                w, h = map(int, block_size_text.split(","))
                settings["block_size"] = [w, h]
            except ValueError:
                self.logger.warning("Invalid block size format, using default 512,512")
                settings["block_size"] = [512, 512]

            for key, value in settings.items():
                self.config_manager.update_config(key, value)

            self.logger.info("Settings saved successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save settings: {str(e)}")
            return False

    def validate_settings(self, dialog) -> bool:
        """Validate current settings.

        Args:
            dialog: Main dialog instance

        Returns:
            bool: True if settings are valid

        Raises:
            SettingsError: If validation fails
        """

        is_valid = True
        errors = []

        try:
            # Validate census columns
            pop_column = dialog.popColumnEdit.text().strip()
            id_column = dialog.idColumnEdit.text().strip()

            if not pop_column:
                errors.append("Population column name cannot be empty")
                is_valid = False
            if not id_column:
                errors.append("ID column name cannot be empty")
                is_valid = False

            # Validate parallel processing
            if dialog.enableParallelCheckBox.isChecked():
                try:
                    cores = int(dialog.cpuCoresComboBox.currentText())
                    if cores <= 0:
                        errors.append("Number of CPU cores must be positive")
                        is_valid = False
                except ValueError:
                    errors.append("Invalid number of CPU cores")
                    is_valid = False

            # Validate block size
            if dialog.enableBlockProcessingCheckBox.isChecked():
                try:
                    w, h = map(int, dialog.blockSizeComboBox.currentText().split(","))
                    if w <= 0 or h <= 0:
                        errors.append("Block size dimensions must be positive")
                        is_valid = False
                except ValueError:
                    errors.append("Invalid block size format (should be width,height)")
                    is_valid = False

        except Exception as e:
            self.logger.error(f"Settings validation failed: {str(e)}")
            return False

            # Log all errors
        for error in errors:
            self.logger.error(error)

        return is_valid
