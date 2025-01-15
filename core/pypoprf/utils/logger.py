# src/pypoprf/utils/logger.py
import logging
import sys
from typing import Optional, TextIO
from pathlib import Path
from colorama import Fore, Style


class PopRFLogger:
    """Logger for pypopRF with file and stream output support."""

    def __init__(self, name: str = 'pypopRF'):
        # Initialize base logger
        self.logger = logging.getLogger(name)
        self.logger.handlers.clear()
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        # Initialize handlers
        self.console_handler = None
        self.file_handler = None

    def _get_formatter(self, colored: bool = False) -> logging.Formatter:
        """Get message formatter."""
        if not colored:
            return logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        class ColorFormatter(logging.Formatter):
            COLORS = {
                logging.DEBUG: '#0000FF',  # Blue
                logging.INFO: '#008000',  # Green
                logging.WARNING: '#FFA500',  # Orange
                logging.ERROR: '#FF0000',  # Red
                logging.CRITICAL: '#8B0000'  # Dark Red
            }

            def format(self, record):
                timestamp = self.formatTime(record, self.datefmt)
                level = record.levelname
                msg = record.getMessage()

                color = self.COLORS.get(record.levelno, '#000000')
                return (
                    f'<span style="color: #666666">{timestamp}</span> - '
                    f'<span style="color: {color}">{level} - {msg}</span>'
                )

        return ColorFormatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def set_level(self, level: str) -> None:
        """Set logging level."""
        levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        self.logger.setLevel(levels.get(level.upper(), logging.INFO))

    def set_output_stream(self, stream: TextIO = sys.stdout) -> None:
        """Set stream output (console)."""
        # Remove existing handler
        if self.console_handler:
            self.logger.removeHandler(self.console_handler)

        # Create new handler
        self.console_handler = logging.StreamHandler(stream)
        self.console_handler.setFormatter(self._get_formatter(colored=True))
        self.logger.addHandler(self.console_handler)

    def set_log_file(self, filepath: str) -> None:
        """Set file output."""
        # Remove existing handler
        if self.file_handler:
            self.file_handler.close()
            self.logger.removeHandler(self.file_handler)

        # Create directory if needed
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Create new handler
        self.file_handler = logging.FileHandler(filepath, mode='w')
        self.file_handler.setFormatter(self._get_formatter())
        self.logger.addHandler(self.file_handler)

    def close(self) -> None:
        """Close all handlers."""
        if self.file_handler:
            self.file_handler.close()
            self.logger.removeHandler(self.file_handler)
        if self.console_handler:
            self.logger.removeHandler(self.console_handler)

    def __del__(self):
        """Cleanup on deletion."""
        self.close()

    # Logging methods
    def debug(self, msg: str): self.logger.debug(msg)
    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)
    def critical(self, msg: str): self.logger.critical(msg)


# Global logger instance
logger = PopRFLogger()

def get_logger(log_file: Optional[str] = None,
               output_stream: Optional[TextIO] = None) -> PopRFLogger:
    """Get global logger instance."""
    if log_file:
        logger.set_log_file(log_file)
    if output_stream:
        logger.set_output_stream(output_stream)
    return logger