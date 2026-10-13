"""Asynchronous runtime discovery/setup; no host installation or binary imports."""
from threading import Event

from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
from ..runtime_manager import RuntimeNotReady


class SetupCancelled(RuntimeError):
    pass


class SetupToken:
    def __init__(self):
        self.event = Event()

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise SetupCancelled("Engine setup cancelled")


class RuntimeWorker(QThread):
    progress = pyqtSignal(int, str)

    def __init__(self, manager, python=None, parent=None):
        super().__init__(parent)
        self.manager, self.python = manager, python
        self.token = SetupToken()
        self.result = None

    def run(self):
        try:
            self.token.check()
            if self.python:
                executable = self.manager.setup(self.python, progress=self.progress.emit,
                                                cancellation_token=self.token)
                self.result = {"python": str(executable), "candidates": [], "error": None}
            else:
                try:
                    executable = self.manager.get_python(cancellation_token=self.token)
                    candidates = []
                except RuntimeNotReady:
                    executable = None
                    self.token.check()
                    candidates = self.manager.detect_python_candidates(cancellation_token=self.token)
                self.token.check()
                self.result = {"python": str(executable) if executable else None,
                               "candidates": [str(p) for p in candidates], "error": None}
        except Exception as exc:
            self.result = {"python": None, "candidates": [], "error": str(exc)}


class RuntimeController(QObject):
    changed = pyqtSignal(dict)
    progress = pyqtSignal(int, str)
    completed = pyqtSignal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.worker = None
        self.python = None

    @property
    def is_running(self):
        return self.worker is not None

    def check(self):
        self._start(None)

    def setup(self, python):
        self._start(python)

    def _start(self, python):
        if self.worker:
            return
        self.worker = RuntimeWorker(self.manager, python, self)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.token.cancel()

    def _finished(self):
        worker = self.worker
        result = worker.result or {"python": None, "candidates": [], "error": "Setup ended without a result"}
        if worker.python and result["error"] and self.python:
            result["python"] = self.python
        self.python = result["python"]
        self.worker = None
        worker.deleteLater()
        self.changed.emit(result)
        self.completed.emit()
