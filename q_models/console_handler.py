# -*- coding: utf-8 -*-
import os

from pypoprf.utils.logger import PopRFLogger
from qgis.PyQt import QtWidgets
from PyQt5.QtCore import QObject, pyqtSignal, Qt


class ConsoleStream(QObject):
    """Stream handler for redirecting logs to QTextEdit with color formatting"""
    messageReceived = pyqtSignal(str)

    def __init__(self, text_widget, parent=None):
        """
        Initialize ConsoleStream.

        Args:
            text_widget: QTextEdit widget for displaying logs
            parent: Parent QObject
        """
        super(ConsoleStream, self).__init__(parent)
        self.text_widget = text_widget
        self.colors = {
            'DEBUG': '#0000FF',  # Blue
            'INFO': '#008000',  # Green
            'WARNING': '#FFA500',  # Orange
            'ERROR': '#FF0000',  # Red
            'CRITICAL': '#8B0000'  # Dark Red
        }

        self.messageReceived.connect(self._append_text)

    def _append_text(self, text):
        self.text_widget.append(text)

    def write(self, text):
        """
        Write formatted text to console widget.

        Args:
            text: Log message to write
        """
        text = text.strip()
        if text:
            try:
                parts = text.split(' - ', 2)
                if len(parts) == 3:
                    timestamp, level, message = parts
                    color = self.colors.get(level, '#000000')
                    formatted_text = (
                        f'<span style="color: #666666">{timestamp}</span> - '
                        f'<span style="color: {color}">{level}</span> - '
                        f'<span style="color: #000000">{message}</span>'
                    )
                else:
                    formatted_text = text
                self.messageReceived.emit(formatted_text)
            except Exception as e:
                print(f"Error in ConsoleStream.write: {str(e)}")

    def flush(self):
        """Flush the stream (required for stream interface)"""
        pass


class ConsoleHandler:
    """Handler for console output in QGIS plugin"""

    def __init__(self, parent_widget):
        """
        Initialize ConsoleHandler.

        Args:
            parent_widget: Widget that will contain the console
        """
        # Create console text widget
        self.console_text = QtWidgets.QTextEdit(parent_widget)
        self.console_text.setReadOnly(True)
        self.console_text.setAcceptRichText(True)

        font = self.console_text.font()
        font.setPointSize(10) # Set font size
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

        # Add to layout
        layout = QtWidgets.QVBoxLayout(parent_widget)
        layout.addWidget(self.console_text)

        # Initialize logger
        self.logger = PopRFLogger()
        self.stream = ConsoleStream(self.console_text, parent=parent_widget)
        self.logger.set_output_stream(self.stream)

        # Store logging settings
        self._log_file = None
        self._log_level = 'INFO'


    def clear(self):
        """Clear console content"""
        self.console_text.clear()

    def update_logging_settings(self, level: str, save_log: bool, work_dir: str = None, filename: str = None):
        """
        Update logging settings.

        Args:
            level: Logging level (INFO, DEBUG, etc.)
            save_log: Whether to save log to file
            work_dir: Working directory path for log file
            filename: Custom log filename
        """
        # Update logging level
        if level != self._log_level:
            self._log_level = level
            self.logger.set_level(level)
            self.logger.info(f"Changed logging level to: {level}")

        # Update log file
        if save_log:
            log_file = os.path.join(work_dir, 'output', filename)
            if log_file != self._log_file:
                # Create output directory if it doesn't exist
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                self._log_file = log_file
                self.logger.set_log_file(log_file)
                self.logger.info(f"Changed log file to: {log_file}")