"""Project imports run outside the GUI, publishing only completed copies."""
from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal

from ..services.file_handlers import FileHandler
from .runtime_controller import SetupToken


class ImportWorker(QThread):
    progress = pyqtSignal(int, str)

    def __init__(self, working_dir, data_dir, paths, kind, logger, parent=None, options=None):
        super().__init__(parent)
        self.handler = FileHandler(working_dir, logger)
        self.handler.data_dir = data_dir
        self.paths, self.kind = paths, kind
        self.options = dict(options or {})
        self.token = SetupToken()
        self.result = {"kind": kind, "filenames": [], "errors": [], "conflicts": [], "cancelled": False}

    def run(self):
        for index, path in enumerate(self.paths):
            try:
                self.token.check()
                resolution = self.options.get("resolution") if index == 0 else None
                if not resolution:
                    conflict = self.handler.inspect_conflict(path, self.kind, self.token,
                        self.progress.emit, self.options.get("id_column", "id"))
                    self.token.check()
                    if conflict:
                        conflict["remaining_paths"] = list(self.paths[index:])
                        self.result["conflicts"].append(conflict)
                        break
                filename = self.handler.copy_to_data_dir(
                    path, self.kind, cancellation_token=self.token, progress=self.progress.emit,
                    id_column=self.options.get("id_column", "id"), **(resolution or {}))
                self.result["filenames"].append(filename)
            except Exception as exc:
                if self.token.event.is_set():
                    self.result["cancelled"] = True
                    break
                self.result["errors"].append(str(exc))


class ImportController(QObject):
    progress = pyqtSignal(int, str)
    imported = pyqtSignal(dict)
    completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.pending_conflict = None
        self._context = None

    @property
    def is_running(self):
        return self.worker is not None or self.pending_conflict is not None

    def start(self, working_dir, data_dir, paths, kind, logger, options=None):
        if self.is_running:
            return False
        self._context = (working_dir, data_dir, list(paths), kind, logger, dict(options or {}))
        self.worker = ImportWorker(working_dir, data_dir, paths, kind, logger, self, options)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self._finished)
        self.worker.start()
        return True

    def resolve_conflict(self, action, destination_name=None):
        if self.worker or not self.pending_conflict:
            return False
        conflict, context = self.pending_conflict, self._context
        self.pending_conflict = None
        if action == "cancel":
            self._cancel_pending(conflict["kind"])
            return True
        work, data, _, kind, logger, options = context
        options = dict(options, resolution={"conflict": conflict, "action": action,
                                           "destination_name": destination_name})
        return self.start(work, data, conflict["remaining_paths"], kind, logger, options)

    def _cancel_pending(self, kind):
        self._context = None
        self.imported.emit({"kind": kind, "filenames": [], "errors": [],
                            "conflicts": [], "cancelled": True})
        self.completed.emit()

    def stop(self):
        if self.worker:
            self.worker.token.cancel()
        elif self.pending_conflict:
            kind = self.pending_conflict["kind"]
            self.pending_conflict = None
            self._cancel_pending(kind)

    def _finished(self):
        worker = self.worker
        self.worker = None
        result = worker.result
        worker.deleteLater()
        if result.get("conflicts") and not worker.token.event.is_set():
            self.pending_conflict = result["conflicts"][0]
        else:
            self._context = None
            if worker.token.event.is_set():
                result["conflicts"] = []
                result["cancelled"] = True
        should_complete = not self.pending_conflict
        self.imported.emit(result)
        if should_complete:
            self.completed.emit()
