# -*- coding: utf-8 -*-
from pypoprf.utils.logger import PopRFLogger
from qgis.PyQt import QtWidgets


class ConsoleStream:
    """Stream handler for redirecting logs to QTextEdit with color formatting"""

    def __init__(self, text_widget):
        """
        Initialize ConsoleStream.

        Args:
            text_widget: QTextEdit widget for displaying logs
        """
        self.text_widget = text_widget
        self.colors = {
            'DEBUG': '#0000FF',  # Blue
            'INFO': '#008000',  # Green
            'WARNING': '#FFA500',  # Orange
            'ERROR': '#FF0000',  # Red
            'CRITICAL': '#8B0000'  # Dark Red
        }

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
                    self.text_widget.append(formatted_text)
                else:
                    self.text_widget.append(text)
            except:
                self.text_widget.append(text)

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

        # Add to layout
        layout = QtWidgets.QVBoxLayout(parent_widget)
        layout.addWidget(self.console_text)

        # Initialize logger
        self.logger = PopRFLogger()
        self.logger.set_output_stream(ConsoleStream(self.console_text))

    def clear(self):
        """Clear console content"""
        self.console_text.clear()

