# -*- coding: utf-8 -*-
import os
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QFont
from qgis.PyQt import QtWidgets

from ..core.pypoprf.utils.logger import get_logger

# Constants
DEFAULT_FONT_FAMILY = "Consolas"
DEFAULT_FONT_SIZE = 10
DEFAULT_LOG_LEVEL = "INFO"
CONSOLE_STYLE = """
    QTextEdit {
        background-color: white;
        color: black;
        font-family: 'Consolas', monospace;
        border: 1px solid #ccc;
        padding: 5px;
    }
"""


class ConsoleStreamError(Exception):
    """Custom exception for console stream operations."""

    pass


class ConsoleStream(QObject):
    """Stream handler for QGIS console output.

    A custom stream handler that formats and displays text in the QGIS console
    while maintaining scroll position and text formatting.

    Attributes:
        text_widget: QTextEdit widget for displaying console output
        messageReceived: Signal emitted when new text is received
    """

    messageReceived = pyqtSignal(str)

    def __init__(
        self, text_widget: QtWidgets.QTextEdit, parent: Optional[QObject] = None
    ) -> None:
        """Initialize the console stream.

        Args:
            text_widget: QTextEdit widget for displaying console output
            parent: Parent QObject for Qt hierarchy
        """
        super().__init__(parent)
        self.text_widget = text_widget
        self.messageReceived.connect(self._append_text)

    def _append_text(self, text):
        """Append text to console widget while maintaining scroll position.

        Args:
            text: Text to append to console
        """

        scrollbar = self.text_widget.verticalScrollBar()
        was_at_bottom = scrollbar.value() == scrollbar.maximum()

        self.text_widget.append(text)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def write(self, text: str) -> None:
        """Write formatted text to console.

        Args:
            text: Text to write to console
        """
        text = text.strip()
        if text:
            self.messageReceived.emit(text)


class ConsoleHandler:
    """Handler for QGIS plugin console output.

    Manages console widget setup, logging configuration, and text display
    in the QGIS plugin interface.

    Attributes:
        console_text: QTextEdit widget for console display
        logger: Logger instance
        stream: ConsoleStream instance
        _log_file: Current log file path
        _log_level: Current logging level
    """

    def __init__(self, parent_widget: QtWidgets.QWidget) -> None:
        """Initialize console handler.

        Args:
            parent_widget: Parent widget for console display

        Raises:
            ConsoleStreamError: If console initialization fails
        """
        try:
            self._setup_console_widget(parent_widget)
            self._setup_logger(parent_widget)

            # Store settings
            self._log_file: Optional[str] = None
            self._log_level: str = DEFAULT_LOG_LEVEL

        except Exception as e:
            raise ConsoleStreamError(f"Console initialization failed: {str(e)}")

    def _setup_console_widget(self, parent_widget: QtWidgets.QWidget) -> None:
        """Setup console widget with proper styling.

        Args:
            parent_widget: Parent widget for console
        """
        # Setup console widget
        self.console_text = QtWidgets.QTextEdit(parent_widget)
        self.console_text.setReadOnly(True)
        self.console_text.setAcceptRichText(True)

        # Setup font
        font = QFont(DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE)
        self.console_text.setFont(font)
        self.console_text.setStyleSheet(CONSOLE_STYLE)

        # Setup layout
        layout = QtWidgets.QVBoxLayout(parent_widget)
        layout.addWidget(self.console_text)

    def _setup_logger(self, parent_widget: QtWidgets.QWidget) -> None:
        """Setup logger with console stream.

        Args:
            parent_widget: Parent widget for stream
        """
        self.logger = get_logger()
        self.stream = ConsoleStream(self.console_text, parent=parent_widget)
        self.logger.set_output_stream(self.stream)

    def clear(self) -> None:
        """Clear console content."""
        try:
            self.console_text.clear()
        except Exception as e:
            raise ConsoleStreamError(f"Failed to clear console: {str(e)}")

    def update_logging_settings(
        self,
        level: str,
        save_log: bool,
        work_dir: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> None:
        """Update logging settings.

        Args:
            level: Logging level (INFO, DEBUG, etc.)
            save_log: Whether to save logs to file
            work_dir: Working directory for log file
            filename: Log file name

        Raises:
            ConsoleStreamError: If logging settings update fails
        """

        # Update level if changed
        if level != self._log_level:
            self._log_level = level
            self.logger.set_level(level)

        if work_dir and filename:
            log_file = os.path.join(work_dir, "output", filename)
            if log_file != self._log_file:
                try:
                    os.makedirs(os.path.dirname(log_file), exist_ok=True)
                    self._log_file = log_file
                    self.logger.set_log_file(log_file)
                    self.logger.info(f"Log file set to: {log_file}")
                except Exception as e:
                    raise ConsoleStreamError(f"Failed to set log file: {str(e)}")
