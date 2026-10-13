"""AOI population-summary dialog using the isolated tools controller."""
import re
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from ..widgets.file_choice import FileChoice
from ...controllers.tools_controller import validate_population_summary


class PopulationSummaryDialog(QtWidgets.QDialog):
    def __init__(self, dialog, maps, artifact_hashes=None):
        super().__init__(dialog)
        self.dialog, self.controller = dialog, dialog.tools_controller
        self._active, self._close_pending = False, False
        self._artifact_hashes = dict(artifact_hashes or {})
        self.setWindowTitle("Population inside an area")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(720, 480)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.population = QtWidgets.QComboBox()
        for path in maps:
            self.population.addItem(Path(path).name, str(path))
        self.aoi = FileChoice("vector")
        form.addRow("Population map", self.population)
        form.addRow("Area polygons", self.aoi)
        layout.addLayout(form)
        caption = QtWidgets.QLabel("Counts are summed in persons per pixel. A cell is included when its center lies inside or on the polygon boundary. No area-weighted boundary interpolation is performed.")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.integrityCaption = QtWidgets.QLabel()
        self.integrityCaption.setTextFormat(Qt.TextFormat.PlainText)
        self.integrityCaption.setWordWrap(True)
        layout.addWidget(self.integrityCaption)
        self.progress = QtWidgets.QProgressBar()
        layout.addWidget(self.progress)
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.calculate = QtWidgets.QPushButton("Calculate population")
        self.cancel = QtWidgets.QPushButton("Close")
        buttons.addWidget(self.calculate)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self.calculate.clicked.connect(self.start)
        self.cancel.clicked.connect(self.reject)
        self.controller.progress.connect(self._progress)
        self.controller.resultReady.connect(self._result)
        self.population.currentIndexChanged.connect(self._update_integrity_caption)
        self._update_integrity_caption()

    def _selected_hash(self):
        value = self._artifact_hashes.get(self.population.currentData())
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None

    def _update_integrity_caption(self, *args):
        self.integrityCaption.setText("The completed-run raster fingerprint will be verified before calculation."
            if self._selected_hash() else "No saved artifact fingerprint is available. The current file can be summarized, but its integrity against a completed run is not verified.")

    def start(self):
        if self._active:
            return
        try:
            aoi = self.aoi.record()
            if not aoi["path"]:
                raise ValueError("Choose a local polygon file or QGIS layer first.")
        except (ValueError, OSError, RuntimeError) as exc:
            self.summary.setPlainText(str(exc))
            return
        self._active = True
        request = {"schema_version": 1, "operation": "population_summary",
            "population_raster": self.population.currentData(), "aoi": aoi,
            "inclusion": "cell_center", "units": "persons_per_pixel"}
        if self._selected_hash():
            request["expected_population_sha256"] = self._selected_hash()
        self.progress.setValue(0)
        self.progress.setFormat("Calculating population summary")
        if self.controller.start(request):
            self.calculate.setEnabled(False)
            self.population.setEnabled(False)
            self.aoi.setEnabled(False)
            self.cancel.setText("Stop")
        else:
            self._active = False

    def _progress(self, percent, message):
        if self._active:
            self.progress.setValue(percent)
            self.progress.setFormat(message)

    def _result(self, result):
        if not self._active or result.get("operation") != "population_summary":
            return
        self._active = False
        self.calculate.setEnabled(True)
        self.population.setEnabled(True)
        self.aoi.setEnabled(True)
        self.cancel.setText("Close")
        if self._close_pending:
            super().reject()
            return
        try:
            if not result.get("success"):
                raise ValueError(result.get("message") or "Population summary failed")
            report = result["report"]
            values = validate_population_summary(report["summary"])
            lines = [f"Estimated population in selected valid cells: {values['display_persons']:,} persons",
                     "Model estimate, rounded to whole persons; this is not a pixel-accuracy guarantee.",
                     f"Selected cell centers: {values['selected_cells']:,}; valid cells: {values['valid_cells']:,}",
                     "Inclusion: cell centers inside or on the polygon boundary."]
            coverage = values.get("coverage_fraction")
            if coverage is not None:
                lines.append(f"Valid coverage of selected raster cell centers: {float(coverage):.1%} (not total AOI area)")
            if not values.get("complete_coverage"):
                lines.append("PARTIAL COVERAGE: this is not a total for the entire area. Some cells or area are outside valid raster coverage.")
            for warning in report.get("warnings", []):
                lines.append(str(warning.get("message", warning) if isinstance(warning, dict) else warning))
            if not self._selected_hash():
                lines.append("WARNING: no saved artifact fingerprint was available; this map was not verified against a completed run.")
            self.summary.setPlainText("\n".join(lines))
            self.progress.setValue(100)
            self.progress.setFormat("Summary complete" if values.get("complete_coverage") else
                                    "Summary complete: partial coverage")
        except (ValueError, KeyError, TypeError) as exc:
            self.progress.setValue(0)
            self.progress.setFormat("Summary did not complete")
            self.summary.setPlainText(str(exc))

    def reject(self):
        if self._active and self.controller.is_running:
            self._close_pending = True
            self.controller.stop()
            return
        super().reject()

    def closeEvent(self, event):
        if self._active and self.controller.is_running:
            self._close_pending = True
            self.controller.stop()
            event.ignore()
        else:
            super().closeEvent(event)
