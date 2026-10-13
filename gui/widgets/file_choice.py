"""Local-file and explicit current-project layer selection widget."""
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import pyqtSignal
from ..layer_integration import choose_project_layer


class FileChoice(QtWidgets.QWidget):
    changed = pyqtSignal()

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind, self.layer_name = kind, None
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("Choose a local file")
        browse = QtWidgets.QPushButton("Browse…")
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        browse.clicked.connect(self.browse)
        if kind in {"raster", "vector"}:
            layers = QtWidgets.QPushButton("QGIS layer…")
            layout.addWidget(layers)
            layers.clicked.connect(self.use_layer)
        self.edit.textChanged.connect(self._changed)

    def _changed(self):
        self.layer_name = None
        self.changed.emit()

    def path(self):
        value = self.edit.text().strip()
        if not value:
            return ""
        path = Path(value).expanduser().absolute()
        if path.is_symlink():
            raise ValueError("Select the original file, not a file symlink, so directory-local masks and metadata remain unambiguous")
        return str(path.parent.resolve() / path.name)

    def record(self):
        result = {"path": self.path()}
        if self.layer_name:
            result["layer"] = self.layer_name
        return result

    def browse(self):
        filters = {"raster": "GeoTIFF (*.tif *.tiff)", "csv": "Census CSV (*.csv)",
                   "vector": "Vector files (*.gpkg *.geojson *.shp);;All files (*)"}
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select input", "", filters[self.kind])
        if path:
            self.edit.setText(path)

    def use_layer(self):
        try:
            record = choose_project_layer(self, self.kind)
            if record:
                self.edit.setText(record["path"])
                self.layer_name = record.get("layer")
                self.changed.emit()
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.warning(self, "Layer selection", str(exc))
