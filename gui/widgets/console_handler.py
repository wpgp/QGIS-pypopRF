"""Bounded, plain-text QGIS diagnostics without numerical-engine imports."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QFontDatabase, QTextCursor
from qgis.PyQt import QtWidgets

from ...services.config_manager import validate_log_filename
from ...services.project_location import ensure_gui_log_location


class AppLogger:
    """The GUI owns this logger; the engine writes its own run log."""
    def __init__(self):
        self.logger = logging.Logger("pypopRF interface")
        self.logger.setLevel(logging.INFO)
        self.console_handler = None
        self.file_handler = None

    def set_level(self, level):
        self.logger.setLevel(level.upper())

    def set_output_stream(self, stream=sys.stdout):
        if self.console_handler:
            self.logger.removeHandler(self.console_handler)
            self.console_handler.close()
        self.console_handler = logging.StreamHandler(stream)
        self.console_handler.setFormatter(logging.Formatter("%(levelname)s · %(message)s"))
        self.logger.addHandler(self.console_handler)

    def set_log_file(self, filepath):
        if self.file_handler:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None
        if filepath:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            self.file_handler = RotatingFileHandler(
                filepath, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            self.file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(self.file_handler)

    def close(self):
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()
        self.console_handler = self.file_handler = None

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def critical(self, message):
        self.logger.critical(message)


class ConsoleStream(QObject):
    messageReceived = pyqtSignal(str)

    def __init__(self, text_widget, parent=None):
        super().__init__(parent)
        self.text_widget = text_widget
        self.messageReceived.connect(self._append_text)

    def _append_text(self, text):
        scrollbar = self.text_widget.verticalScrollBar()
        bottom = scrollbar.value() == scrollbar.maximum()
        self.text_widget.moveCursor(QTextCursor.MoveOperation.End)
        self.text_widget.insertPlainText(text + "\n")
        if bottom:
            scrollbar.setValue(scrollbar.maximum())

    def write(self, text):
        if text.strip():
            self.messageReceived.emit(text.rstrip())

    def flush(self):
        pass


class ConsoleHandler:
    def __init__(self, parent_widget, protected_locations=None):
        self._protected_locations = dict(protected_locations or {})
        self.console_text = QtWidgets.QPlainTextEdit(parent_widget)
        self.console_text.setReadOnly(True)
        self.console_text.document().setMaximumBlockCount(3000)
        self.console_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout = parent_widget.layout() or QtWidgets.QVBoxLayout(parent_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.console_text)
        self.logger = AppLogger()
        self.stream = ConsoleStream(self.console_text, parent=parent_widget)
        self.logger.set_output_stream(self.stream)
        self._log_file = None

    def clear(self):
        self.console_text.clear()

    def update_logging_settings(self, level, save_log, work_dir=None, filename=None):
        self.logger.set_level(level)
        if save_log and work_dir and filename:
            validate_log_filename(filename)
            path = str(ensure_gui_log_location(work_dir, filename, **self._protected_locations))
            if path != self._log_file:
                self.logger.set_log_file(path)
                self._log_file = path
