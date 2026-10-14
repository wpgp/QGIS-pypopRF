"""Owned nonblocking collision choice: never overwrite an existing input."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QDialogButtonBox

from ...services.file_handlers import FileHandler, FileHandlerError
from ..widgets.light_theme import apply_light_theme


class ImportConflictDialog(QDialog):
    choiceMade = pyqtSignal(str, str)

    def __init__(self, conflict, parent=None):
        super().__init__(parent)
        apply_light_theme(self)
        self.conflict = conflict
        self._chosen = False
        self.setWindowTitle("An input with this name already exists")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        roles = {"mastergrid": "zone grid", "census_data": "population census",
                 "agesex_data": "age-sex counts", "mask": "water mask",
                 "constrain": "constrained support", "covariate": "covariate"}
        role = roles.get(conflict["kind"], "input")
        self.explanation = QLabel(self)
        self.explanation.setTextFormat(Qt.TextFormat.PlainText)
        self.explanation.setWordWrap(True)
        message = f"Importing {conflict['filename']} as {role}. The project already contains this filename. Neither file will be overwritten."
        if conflict.get("headers"):
            message += "\nCSV headers: " + ", ".join(conflict["headers"])
            message += "\nColumn mapping and numerical validity are checked when the analysis starts."
        if not conflict.get("sidecar_compatible", True):
            message += "\nExternal raster masks/metadata prevent byte-only reuse. Export with internal masks and georeferencing first."
        message += "\n" + ("Verified identical file bytes; reuse is available." if conflict["reuse_allowed"] else "Reuse is unavailable: bytes differ or raster resources are incompatible.")
        self.explanation.setText(message)
        layout.addWidget(self.explanation)
        self.reuseButton = QPushButton("Use verified existing file", self)
        self.reuseButton.setEnabled(conflict["reuse_allowed"])
        self.reuseButton.clicked.connect(lambda: self._choose("reuse", conflict["filename"]))
        layout.addWidget(self.reuseButton)
        self.filenameEdit = QLineEdit(self)
        original = Path(conflict["filename"])
        self.filenameEdit.setText(original.stem + "_copy" + original.suffix)
        self.filenameEdit.setAccessibleName("Separate copy filename")
        layout.addWidget(QLabel("Import a separate copy under a new filename:", self))
        layout.addWidget(self.filenameEdit)
        self.errorLabel = QLabel(self)
        self.errorLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.errorLabel.setWordWrap(True)
        layout.addWidget(self.errorLabel)
        self.copyButton = QPushButton("Import separate copy", self)
        self.copyButton.clicked.connect(self._copy)
        layout.addWidget(self.copyButton)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy(self):
        name = self.filenameEdit.text()
        try:
            FileHandler.validate_basename(name, Path(self.conflict["filename"]).suffix)
            if name.casefold() == self.conflict["filename"].casefold():
                raise FileHandlerError("Choose a different filename; originals are never replaced")
        except FileHandlerError as exc:
            self.errorLabel.setText(str(exc))
            return
        self._choose("copy", name)

    def _choose(self, action, name):
        if self._chosen:
            return
        self._chosen = True
        self.choiceMade.emit(action, name)
        self.accept()

    def reject(self):
        if not self._chosen:
            self._chosen = True
            self.choiceMade.emit("cancel", "")
        super().reject()
