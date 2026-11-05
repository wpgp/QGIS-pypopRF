"""Asynchronous runtime discovery/setup; no host installation or binary imports."""
from threading import Event

from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
from ..services.runtime_manager import RuntimeNotReady


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

    def __init__(self, manager, python=None, parent=None, operation=None, discover=False):
        super().__init__(parent)
        self.manager, self.python = manager, python
        self.operation = operation or ("setup" if python else "check")
        self.discover = discover
        self.token = SetupToken()
        self.result = None

    def run(self):
        executable = None
        known_invalidated = False
        try:
            self.token.check()
            if self.operation == "inspect":
                info = self.manager.check_interpreter(self.python, cancellation_token=self.token)
                self.token.check()
                self.result = {"path": str(self.python), "info": info, "error": None}
            elif self.operation == "setup":
                executable = self.manager.setup(self.python, progress=self.progress.emit,
                                                cancellation_token=self.token)
                self.result = {"python": str(executable), "candidates": [], "interpreters": [],
                               "setup_needed": False, "reason": None, "error": None}
            else:
                try:
                    executable = self.manager.get_python(cancellation_token=self.token)
                    interpreters, reason = [], None
                except RuntimeNotReady as exc:
                    executable = None
                    known_invalidated = True
                    reason = str(exc)
                    self.token.check()
                if executable is None or self.discover:
                    if hasattr(self.manager, "discover_interpreters"):
                        interpreters = self.manager.discover_interpreters(cancellation_token=self.token)
                    else:
                        candidates = self.manager.detect_python_candidates(cancellation_token=self.token)
                        interpreters = [{"path": str(path), "version": "unknown", "bits": None,
                                         "source": "legacy", "recommended": index == 0, "embedded": False}
                                        for index, path in enumerate(candidates)]
                self.token.check()
                self.result = {"python": str(executable) if executable else None,
                               "candidates": [record["path"] for record in interpreters], "interpreters": interpreters,
                               "setup_needed": executable is None, "reason": reason, "error": None,
                               "cancelled": False, "known_invalidated": known_invalidated}
        except Exception as exc:
            self.result = ({"path": str(self.python), "info": None, "error": str(exc)} if self.operation == "inspect"
                           else {"python": str(executable) if executable else None, "candidates": [], "interpreters": [],
                                 "setup_needed": executable is None, "reason": str(exc), "error": str(exc),
                                 "cancelled": self.token.event.is_set(), "known_invalidated": known_invalidated})


class RuntimeController(QObject):
    changed = pyqtSignal(dict)
    progress = pyqtSignal(int, str)
    completed = pyqtSignal()
    interpreterChecked = pyqtSignal(dict)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.worker = None
        self.python = None

    @property
    def is_running(self):
        return self.worker is not None

    def check(self, discover=False):
        return self._start(None, discover=discover)

    def setup(self, python):
        self._start(python)

    def inspect(self, python):
        """Inspect one selection asynchronously, without replacing healthy state."""
        return self._start(python, "inspect")

    def _start(self, python, operation=None, discover=False):
        if self.worker:
            return False
        self.worker = RuntimeWorker(self.manager, python, self, operation=operation, discover=discover)
        self.worker.progress.connect(lambda value, message, owned=self.worker: self._progress(value, message, owned))
        self.worker.finished.connect(lambda owned=self.worker: self._finished(owned))
        self.worker.start()
        return True

    def _progress(self, value, message, owned):
        if self.worker is owned:
            self.progress.emit(value, message)

    def stop(self):
        if self.worker:
            self.worker.token.cancel()

    def _finished(self, owned=None):
        worker = self.worker
        if worker is None or (owned is not None and owned is not worker):
            return
        if worker.operation == "inspect":
            result = worker.result or {"path": str(worker.python), "info": None, "error": "Interpreter inspection ended without a result"}
            self.worker = None
            worker.deleteLater()
            self.interpreterChecked.emit(result)
            self.completed.emit()
            return
        result = worker.result or {"python": None, "candidates": [], "error": "Setup ended without a result"}
        if (worker.operation == "check" and result.get("cancelled")
                and not result.get("known_invalidated") and self.python):
            # A stopped health probe supplies no new evidence that the existing
            # engine is invalid. Preserve it only until a real health check can
            # complete; observed RuntimeNotReady must still clear old state.
            result["python"] = self.python
            result["setup_needed"] = False
        if worker.python and result["error"] and self.python:
            result["python"] = self.python
        self.python = result["python"]
        self.worker = None
        worker.deleteLater()
        self.changed.emit(result)
        self.completed.emit()
