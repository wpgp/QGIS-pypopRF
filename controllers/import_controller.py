"""Project imports run outside the GUI, publishing only completed copies."""
from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal

from ..services.file_handlers import FileHandler
from .runtime_controller import SetupToken


class ImportWorker(QThread):
    progress = pyqtSignal(int, str)

    def __init__(self, working_dir, data_dir, paths, kind, logger, parent=None):
        super().__init__(parent)
        self.handler = FileHandler(working_dir, logger)
        self.handler.data_dir = data_dir
        self.paths, self.kind = paths, kind
        self.token = SetupToken()
        self.result = {"kind": kind, "filenames": [], "errors": []}

    def run(self):
        for path in self.paths:
            try:
                self.token.check()
                filename = self.handler.copy_to_data_dir(
                    path, self.kind, cancellation_token=self.token, progress=self.progress.emit)
                self.result["filenames"].append(filename)
            except Exception as exc:
                self.result["errors"].append(str(exc))
                if self.token.event.is_set():
                    break


class ImportController(QObject):
    progress = pyqtSignal(int, str)
    imported = pyqtSignal(dict)
    completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

    @property
    def is_running(self):
        return self.worker is not None

    def start(self, working_dir, data_dir, paths, kind, logger):
        if self.worker:
            return
        self.worker = ImportWorker(working_dir, data_dir, paths, kind, logger, self)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.token.cancel()

    def _finished(self):
        worker = self.worker
        self.worker = None
        result = worker.result
        worker.deleteLater()
        self.imported.emit(result)
        self.completed.emit()
