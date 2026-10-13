from logging import Logger
from pathlib import Path
from typing import Any, List

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QTableWidgetItem, QTableWidget
from qgis.PyQt import QtWidgets, QtCore


class CovariateTableError(Exception):
    """Custom exception for covariate table operations."""

    pass


class CovariateTableHandler:
    """Handler for covariates table in QGIS plugin.

    Manages the display and manipulation of covariate data in a table format,
    including file information and actions.

    Attributes:
        table: QTableWidget instance for displaying covariates
        config_manager: ConfigManager instance for handling config updates
        logger: Logger instance for output messages
    """

    def __init__(
        self, table_widget: QTableWidget, config_manager: Any, logger: Logger
    ) -> None:
        """Initialize CovariateTableHandler.

        Args:
            table_widget: QTableWidget instance
            config_manager: ConfigManager instance
            logger: Logger instance

        Raises:
            CovariateTableError: If initialization fails
        """
        try:
            self.table = table_widget
            self.config_manager = config_manager
            self.logger = logger
            self.setup_table()

            # Connect delete key handler
            self.table.keyPressEvent = self.handle_table_keypress

        except Exception as e:
            raise CovariateTableError(f"Failed to initialize covariate table: {str(e)}")

    def setup_table(self) -> None:
        """Setup covariates table structure.

        Configures columns, headers, and resize modes for the table.

        Raises:
            CovariateTableError: If table setup fails
        """
        try:
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["Name", "Size", "File Path", "Actions"])
            header = self.table.horizontalHeader()

            # Set column resize modes
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        except Exception as e:
            raise CovariateTableError(f"Failed to setup table: {str(e)}")

    def add_covariates(self, filenames: List[str]) -> None:
        """Add new covariates to table.

        Args:
            filenames: List of filenames that are already in data directory

        Raises:
            CovariateTableError: If adding covariates fails
        """
        if not filenames:
            return

        try:
            data_dir = Path(self.config_manager.working_dir) / self.config_manager.get_config().get("data_dir", "data")

            for filename in filenames:
                if self.check_duplicate(filename):
                    self.logger.warning(f"Covariate already exists in table: {filename}")
                    continue

                self._add_covariate_row(filename, data_dir)

        except Exception as e:
            raise CovariateTableError(f"Failed to add covariates: {str(e)}")

    def _add_covariate_row(self, filename: str, data_dir: Path, name=None, update=True) -> None:
        """Add a single covariate row to the table.

        Args:
            filename: Filename to add
            data_dir: Data directory path
        """
        row = self.table.rowCount()
        self.table.insertRow(row)

        name = name or Path(filename).stem
        file_path = data_dir / filename

        # Add name
        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.ItemDataRole.UserRole, name)
        self.table.setItem(row, 0, name_item)

        # Add size
        size_item = QTableWidgetItem(self.format_size(file_path.stat().st_size)
                                    if file_path.is_file() else "Missing")
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 1, size_item)

        # Add path
        self.table.setItem(row, 2, QTableWidgetItem(str(file_path)))
        for column in range(3):
            item = self.table.item(row, column)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Add delete button
        delete_button = QtWidgets.QPushButton("Delete")
        delete_button.setToolTip("Delete this covariate")
        self._create_delete_button(row, delete_button)
        self.table.setCellWidget(row, 3, delete_button)

        # Update config
        if update:
            self.config_manager.update_config(f"covariate_{name}", filename)

    def _create_delete_button(self, row: int, button: QtWidgets.QPushButton) -> None:
        """Create delete button with proper connection.

        Args:
            row: Row index for button
            button: Button widget to configure
        """
        key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        button.clicked.connect(lambda checked=False, key=key: self._remove_by_key(key))

    def _remove_by_key(self, key):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == key:
                self.remove_covariate(row)
                return

    def remove_covariate(self, row: int) -> None:
        """Remove covariate from table and config.

        Args:
            row: Row index to remove

        Raises:
            CovariateTableError: If removal fails
        """
        try:
            if not 0 <= row < self.table.rowCount():
                raise ValueError(f"Invalid row index: {row}")

            name = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.logger.debug(f"Removing covariate '{name}' from row {row}")

            self.config_manager.clear_config_value(f"covariate_{name}")
            self.table.removeRow(row)
            if hasattr(self, "on_changed"):
                self.on_changed()

            self.logger.info(f"Successfully removed covariate: {name}")

        except Exception as e:
            raise CovariateTableError(f"Failed to remove covariate at row {row}: {str(e)}")

    def _update_delete_buttons(self, start_row: int) -> None:
        """Update delete buttons after row removal.

        Args:
            start_row: Starting row for update
        """
        for i in range(start_row, self.table.rowCount()):
            delete_button = QtWidgets.QPushButton("Delete")
            delete_button.setToolTip("Delete this covariate")
            self._create_delete_button(i, delete_button)
            self.table.setCellWidget(i, 3, delete_button)

    def remove_selected_covariates(self):
        """Remove selected covariates from table and config"""
        selected_rows = sorted(
            set(item.row() for item in self.table.selectedItems()), reverse=True
        )

        if not selected_rows:
            return

        for row in selected_rows:
            self.remove_covariate(row)

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
            existing_name = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            existing_path = self.table.item(row, 2).text()
            if existing_name.casefold() == name.casefold() or Path(existing_path).stem.casefold() == name.casefold():
                return True
        return False

    def handle_table_keypress(self, event) -> None:
        """Handle keypress events in covariates table.

        Args:
            event: QKeyEvent instance
        """
        if event.key() == QtCore.Qt.Key.Key_Delete:
            self.remove_selected_covariates()
        else:
            QTableWidget.keyPressEvent(self.table, event)

    @staticmethod
    def format_size(size: int) -> str:
        """
        Format file size to human readable format.

        Args:
            size: Size in bytes

        Returns:
            str: Formatted size string
        """
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
