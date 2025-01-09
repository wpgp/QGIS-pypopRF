# -*- coding: utf-8 -*-
import os
from pathlib import Path
from qgis.PyQt import QtWidgets, QtCore


class CovariateTableHandler:
    """Handler for covariates table in QGIS plugin"""

    def __init__(self, table_widget, config_manager, logger):
        """
        Initialize CovariateTableHandler.

        Args:
            table_widget: QTableWidget instance
            config_manager: ConfigManager instance for handling config updates
            logger: Logger instance for output messages
        """
        self.table = table_widget
        self.config_manager = config_manager
        self.logger = logger
        self.setup_table()

        # Connect delete key handler
        self.table.keyPressEvent = self.handle_table_keypress

    def setup_table(self):
        """Setup covariates table structure"""
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Name', 'Size', 'File Path', 'Actions'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

    def add_covariates(self, filenames: list):
        """
        Add new covariates to table.

        Args:
            filenames: List of filenames (not paths) that are already in data directory
        """
        if not filenames:
            return

        data_dir = Path(self.config_manager.working_dir) / 'data'

        for filename in filenames:
            if self.check_duplicate(filename):
                self.logger.warning(f"Covariate already exists in table: {filename}")
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            # Add file name
            name = Path(filename).stem
            item_name = QtWidgets.QTableWidgetItem(name)
            self.table.setItem(row, 0, item_name)

            # Get file size from data directory
            file_path = os.path.join(data_dir, filename)
            size = os.path.getsize(file_path)
            size_str = self.format_size(size)
            item_size = QtWidgets.QTableWidgetItem(size_str)
            item_size.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(row, 1, item_size)

            # Add file path
            item_path = QtWidgets.QTableWidgetItem(file_path)
            self.table.setItem(row, 2, item_path)

            # Add delete button
            delete_button = QtWidgets.QPushButton("Delete")
            delete_button.setToolTip("Delete this covariate")
            self._create_delete_button(row, delete_button)
            self.table.setCellWidget(row, 3, delete_button)

            # Update config
            self.config_manager.update_config(f'covariate_{name}', filename)

    def _create_delete_button(self, row: int, button: QtWidgets.QPushButton):
        """Create delete button with proper connection"""

        def delete_handler(row=row):
            self.remove_covariate(row)

        button.clicked.connect(delete_handler)

    def remove_covariate(self, row: int):
        """
        Remove covariate from table and config based on row index.

        Args:
            row: Row index to remove
        """
        try:
            if 0 <= row < self.table.rowCount():
                name = self.table.item(row, 0).text()
                self.logger.info(f"Removing covariate '{name}' from row {row}")
                self.table.removeRow(row)
                self.config_manager.clear_config_value(f'covariate_{name}')
                self.logger.info(f"Successfully removed covariate: {name}")

                # Update delete buttons for remaining rows
                for i in range(row, self.table.rowCount()):
                    delete_button = QtWidgets.QPushButton("Delete")
                    delete_button.setToolTip("Delete this covariate")
                    self._create_delete_button(i, delete_button)
                    self.table.setCellWidget(i, 3, delete_button)
                    self.logger.debug(f"Updated delete button for row {i}")
        except Exception as e:
            self.logger.error(f"Failed to remove covariate at row {row}: {str(e)}")


    def remove_selected_covariates(self):
        """Remove selected covariates from table and config"""
        selected_rows = sorted(set(item.row() for item in self.table.selectedItems()), reverse=True)

        if not selected_rows:
            return

        for row in selected_rows:
            name = self.table.item(row, 0).text()
            self.table.removeRow(row)
            self.config_manager.clear_config_value(f'covariate_{name}')

        self.logger.info("Removed selected covariates")

    def check_duplicate(self, filename: str) -> bool:
        """
        Check if covariate already exists in table.

        Args:
            filename: Path to check

        Returns:
            bool: True if file already exists in table
        """
        name = Path(filename).stem
        for row in range(self.table.rowCount()):
            existing_name = self.table.item(row, 0).text()
            if existing_name == name:
                return True
        return False

    def handle_table_keypress(self, event):
        """
        Handle keypress events in covariates table.

        Args:
            event: QKeyEvent instance
        """
        if event.key() == QtCore.Qt.Key_Delete:
            self.remove_selected_covariates()
        else:
            QtWidgets.QTableWidget.keyPressEvent(self.table, event)

    @staticmethod
    def format_size(size: int) -> str:
        """
        Format file size to human readable format.

        Args:
            size: Size in bytes

        Returns:
            str: Formatted size string
        """
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"