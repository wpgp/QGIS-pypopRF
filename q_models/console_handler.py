# -*- coding: utf-8 -*-
import os

from pypoprf.utils.logger import get_logger
from qgis.PyQt import QtWidgets, QtCore
from PyQt5.QtCore import QObject, pyqtSignal, Qt

logger = get_logger()


class ConsoleStream(QObject):
    """Stream handler for QGIS console output."""
    messageReceived = pyqtSignal(str)

    def __init__(self, text_widget, parent=None):
        super().__init__(parent)
        self.text_widget = text_widget
        self.messageReceived.connect(self._append_text)

    def _append_text(self, text):
        """Append text to console widget."""
        scrollbar = self.text_widget.verticalScrollBar()
        was_at_bottom = scrollbar.value() == scrollbar.maximum()

        self.text_widget.append(text)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def write(self, text):
        """Write formatted text to console."""
        text = text.strip()
        if text:
            self.messageReceived.emit(text)

class ConsoleHandler:
    """Handler for QGIS plugin console output."""

    def __init__(self, parent_widget):
        """Initialize console handler."""
        # Setup console widget
        self.console_text = QtWidgets.QTextEdit(parent_widget)
        self.console_text.setReadOnly(True)
        self.console_text.setAcceptRichText(True)

        font = self.console_text.font()
        font.setPointSize(10)
        font.setFamily('Consolas')
        self.console_text.setFont(font)

        self.console_text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                color: black;
                font-family: 'Consolas', monospace;
                border: 1px solid #ccc;
                padding: 5px;
            }
        """)

        # Setup layout
        layout = QtWidgets.QVBoxLayout(parent_widget)
        layout.addWidget(self.console_text)

        # Setup logger
        self.logger = get_logger()
        self.stream = ConsoleStream(self.console_text, parent=parent_widget)
        self.logger.set_output_stream(self.stream)

        # Store settings
        self._log_file = None
        self._log_level = 'INFO'

    def clear(self):
        """Clear console content."""
        self.console_text.clear()

    def update_logging_settings(self, level: str, save_log: bool, work_dir: str = None, filename: str = None):
        """Update logging settings."""
        # Update level if changed
        if level != self._log_level:
            self._log_level = level
            self.logger.set_level(level)

        # Update log file if needed
        if save_log and work_dir and filename:
            log_file = os.path.join(work_dir, 'output', filename)
            if log_file != self._log_file:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                self._log_file = log_file
                self.logger.set_log_file(log_file)
