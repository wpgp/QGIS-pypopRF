"""Explicit preparation and AOI workflows backed by the isolated tools engine."""
import csv
import json
import math
from pathlib import Path

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import pyqtSignal, Qt

from ..layer_integration import choose_project_layer
from ..widgets.file_choice import FileChoice
from ..widgets.light_theme import apply_light_theme
from ...services.project_location import ensure_project_location


class PreparationWizard(QtWidgets.QWizard):
    prepared = pyqtSignal(object)

    def __init__(self, dialog):
        super().__init__(dialog)
        apply_light_theme(self)
        self.dialog, self.controller = dialog, dialog.tools_controller
        self.setWindowTitle("Prepare population inputs — create a new project")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWizardStyle(QtWidgets.QWizard.WizardStyle.ModernStyle)
        self.resize(940, 720)
        self.setMinimumSize(720, 560)
        self._operation, self._ready, self._checked = None, False, None
        self._prepared_project, self._close_pending = None, False
        self._expected_inputs = None
        self._build_sources()
        self._build_columns()
        self._build_covariates()
        self._build_review()
        self.currentIdChanged.connect(self._page_changed)
        self.controller.progress.connect(self._progress)
        self.controller.resultReady.connect(self._result)
        self.confirm.toggled.connect(self._update_finish)
        self.outputEdit.textChanged.connect(self._output_changed)
        self._prefill()

    def _page(self, title, subtitle):
        page = QtWidgets.QWizardPage()
        page.setTitle(title)
        page.setSubTitle(subtitle)
        self.addPage(page)
        return page

    def _build_sources(self):
        self.sourcesPage = self._page("1 · Source data", "Choose the target grid. Source files are read only; derived files go into a new project.")
        form = QtWidgets.QFormLayout(self.sourcesPage)
        self.reference = FileChoice("raster")
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Use an existing zone ID raster", "zones")
        self.mode.addItem("Rasterize census polygons onto the reference grid", "polygons")
        self.zones, self.polygons = FileChoice("raster"), FileChoice("vector")
        self.census = FileChoice("csv")
        form.addRow("Reference raster", self.reference)
        form.addRow("Census zone geometry", self.mode)
        form.addRow("Zone ID raster", self.zones)
        form.addRow("Census polygons", self.polygons)
        form.addRow("Population census CSV", self.census)
        self.sourceMessage = QtWidgets.QLabel("The reference supplies CRS, extent and resolution only. Zone validity comes from the zone raster or polygons; excluded/allowed support is chosen explicitly. Polygons outside the grid are rejected, not silently cropped.")
        self.sourceMessage.setWordWrap(True)
        self.sourceMessage.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.sourceMessage)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        for field in (self.reference, self.zones, self.polygons, self.census):
            field.changed.connect(self._invalidate)
        self.census.changed.connect(self._load_columns)
        self._mode_changed()

    def _mode_changed(self):
        polygon_mode = self.mode.currentData() == "polygons"
        self.zones.setEnabled(not polygon_mode)
        self.polygons.setEnabled(polygon_mode)
        self._invalidate()

    def _build_columns(self):
        self.columnsPage = self._page("2 · Census columns", "Specify identifiers and population totals explicitly. Population is a count, not a density.")
        form = QtWidgets.QFormLayout(self.columnsPage)
        self.idColumn, self.populationColumn, self.polygonColumn = (QtWidgets.QComboBox() for _ in range(3))
        for combo in (self.idColumn, self.populationColumn, self.polygonColumn):
            combo.setEditable(True)
            combo.currentTextChanged.connect(self._invalidate)
        self.idColumn.setCurrentText("id")
        self.populationColumn.setCurrentText("pop")
        self.polygonColumn.setCurrentText("id")
        form.addRow("CSV zone identifier", self.idColumn)
        form.addRow("CSV population total", self.populationColumn)
        form.addRow("Polygon zone identifier", self.polygonColumn)
        self.columnMessage = QtWidgets.QLabel("Duplicate or unmatched zone IDs and invalid populations are diagnosed before preparation.")
        self.columnMessage.setWordWrap(True)
        self.columnMessage.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.columnMessage)

    def _load_columns(self):
        if not hasattr(self, "idColumn"):
            return
        try:
            path = self.census.path()
            if not path:
                return
            with Path(path).open("rb") as stream:
                def header_lines():
                    total, first = 0, True
                    while raw := stream.readline(65537 - total):
                        total += len(raw)
                        if total > 65536:
                            raise ValueError("The CSV header is too large")
                        yield raw.decode("utf-8-sig" if first else "utf-8")
                        first = False
                # Read only the bounded first logical CSV record. A truncated
                # multibyte sequence in a later body row is not a header error.
                columns = next(csv.reader(header_lines(), strict=True))
            columns = [name for name in columns if name]
            for combo in (self.idColumn, self.populationColumn):
                previous = combo.currentText()
                combo.clear()
                combo.addItems(columns)
                combo.setCurrentText(previous)
            self.columnMessage.setText("CSV columns: " + ", ".join(columns)[:1200])
        except (OSError, UnicodeError, ValueError, StopIteration, csv.Error) as exc:
            self.columnMessage.setText(f"Could not preview the CSV header: {exc}. Enter column names explicitly.")

    def _build_covariates(self):
        self.covariatePage = self._page("3 · Predictors and support", "Choose what each covariate measures. Multiclass rasters must be converted to binary indicators; counts are never silently warped.")
        layout = QtWidgets.QVBoxLayout(self.covariatePage)
        self.covariates = QtWidgets.QTableWidget(0, 5)
        self.covariates.setHorizontalHeaderLabels(["Name", "Local raster", "Meaning", "Resampling", ""])
        self.covariates.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.covariates, 1)
        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add raster files…")
        layers = QtWidgets.QPushButton("Add QGIS layer…")
        buttons.addWidget(add)
        buttons.addWidget(layers)
        buttons.addStretch()
        layout.addLayout(buttons)
        add.clicked.connect(self._add_files)
        layers.clicked.connect(self._add_layer)
        optional = QtWidgets.QFormLayout()
        self.mask, self.constrain = FileChoice("raster"), FileChoice("raster")
        optional.addRow("Excluded-area mask (optional)", self.mask)
        optional.addRow("Allowed-area constraint (optional)", self.constrain)
        layout.addLayout(optional)
        self.mask.changed.connect(self._invalidate)
        self.constrain.changed.connect(self._invalidate)
        self.covariates.itemChanged.connect(self._invalidate)

    def add_covariate_path(self, path, name=None):
        row = self.covariates.rowCount()
        self.covariates.insertRow(row)
        self.covariates.setItem(row, 0, QtWidgets.QTableWidgetItem(name or Path(path).stem))
        item = QtWidgets.QTableWidgetItem(str(Path(path).resolve()))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.covariates.setItem(row, 1, item)
        quantity, resampling = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        for label, value in (("Continuous value", "continuous"), ("Binary indicator (0/1)", "categorical"), ("Count (aligned only)", "count")):
            quantity.addItem(label, value)
        self.covariates.setCellWidget(row, 2, quantity)
        self.covariates.setCellWidget(row, 3, resampling)
        remove = QtWidgets.QPushButton("Remove")
        self.covariates.setCellWidget(row, 4, remove)
        def update_resampling():
            previous = resampling.currentText()
            resampling.clear()
            resampling.addItems(["bilinear", "average", "nearest"] if quantity.currentData() == "continuous" else ["nearest"])
            if previous and resampling.findText(previous) >= 0:
                resampling.setCurrentText(previous)
            self._invalidate()
        def remove_row():
            for index in range(self.covariates.rowCount()):
                if self.covariates.cellWidget(index, 4) is remove:
                    self.covariates.removeRow(index)
                    self._invalidate()
                    break
        remove.clicked.connect(remove_row)
        quantity.currentIndexChanged.connect(update_resampling)
        resampling.currentIndexChanged.connect(self._invalidate)
        update_resampling()

    def _add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select predictors", "", "GeoTIFF (*.tif *.tiff)")
        for path in paths:
            self.add_covariate_path(path)

    def _add_layer(self):
        try:
            record = choose_project_layer(self, "raster")
            if record:
                self.add_covariate_path(record["path"])
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.warning(self, "Layer selection", str(exc))

    def _build_review(self):
        self.reviewPage = self._page("4 · Review and create", "Check compatibility first. Preparation creates a standalone project; your current project and sources are not changed.")
        layout = QtWidgets.QVBoxLayout(self.reviewPage)
        form = QtWidgets.QFormLayout()
        self.outputEdit = QtWidgets.QLineEdit()
        output = QtWidgets.QWidget()
        output_layout = QtWidgets.QHBoxLayout(output)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.outputEdit, 1)
        parent = QtWidgets.QPushButton("Choose parent…")
        output_layout.addWidget(parent)
        parent.clicked.connect(self._choose_output)
        form.addRow("New project directory", output)
        layout.addLayout(form)
        self.previewButton = QtWidgets.QPushButton("Check compatibility")
        self.previewButton.clicked.connect(self.inspect)
        layout.addWidget(self.previewButton)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.reportView = QtWidgets.QPlainTextEdit()
        self.reportView.setReadOnly(True)
        self.reportView.setMinimumHeight(100)
        self.reportView.setMaximumHeight(320)
        self.reportView.setPlainText("No checks yet. Choose source files, review columns and predictor meanings, then check compatibility.")
        layout.addWidget(self.reportView, 1)
        self.detailsToggle = QtWidgets.QToolButton()
        self.detailsToggle.setText("Technical report details")
        self.detailsToggle.setCheckable(True)
        self.detailsToggle.setArrowType(Qt.ArrowType.RightArrow)
        self.detailsToggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout.addWidget(self.detailsToggle)
        self.reportDetails = QtWidgets.QPlainTextEdit()
        self.reportDetails.setReadOnly(True)
        self.reportDetails.setMinimumHeight(70)
        self.reportDetails.setMaximumHeight(150)
        self.reportDetails.hide()
        layout.addWidget(self.reportDetails)
        def details_toggled(visible):
            self.reportDetails.setVisible(visible)
            self.reportView.setMaximumHeight(170 if visible else 320)
            self.detailsToggle.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        self.detailsToggle.toggled.connect(details_toggled)
        self.confirm = QtWidgets.QCheckBox("Create new files; preserve the sources and current project.")
        layout.addWidget(self.confirm)

    def _prefill(self):
        if not self.dialog.config_manager.config_path:
            return
        try:
            config = self.dialog.config_manager.get_config()
            root = Path(self.dialog.config_manager.working_dir)
            data = root / config.get("data_dir", "data")
            for field, key in ((self.reference, "mastergrid"), (self.zones, "mastergrid"), (self.census, "census_data"),
                               (self.mask, "mask"), (self.constrain, "constrain")):
                if config.get(key):
                    field.edit.setText(str(data / config[key]))
            self.idColumn.setCurrentText(config.get("census_id_column", "id"))
            self.populationColumn.setCurrentText(config.get("census_pop_column", "pop"))
            for name, filename in config.get("covariates", {}).items():
                self.add_covariate_path(data / filename, name)
            self.outputEdit.setText(str(root.parent / (root.name + "-prepared")))
        except Exception as exc:
            self.dialog.logger.warning(f"Could not prefill the preparation wizard: {exc}")

    def _choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose the parent of the new project")
        if path:
            self.outputEdit.setText(str(Path(path) / "prepared-project"))

    def _request(self, operation):
        if not self.reference.path() or not self.census.path():
            raise ValueError("Choose a reference raster and population census CSV")
        request = {"schema_version": 1, "operation": operation, "reference_raster": self.reference.path(),
            "census": {"path": self.census.path(), "id_column": self.idColumn.currentText().strip(),
                       "population_column": self.populationColumn.currentText().strip()}, "covariates": [], "tile_size": 512}
        if self.mode.currentData() == "polygons":
            if not self.polygons.path():
                raise ValueError("Choose census polygons to rasterize")
            request["census_polygons"] = dict(self.polygons.record(), id_column=self.polygonColumn.currentText().strip())
        else:
            request["zone_raster"] = self.zones.path() or self.reference.path()
        for row in range(self.covariates.rowCount()):
            request["covariates"].append({"name": self.covariates.item(row, 0).text().strip(),
                "path": self.covariates.item(row, 1).text(),
                "quantity": self.covariates.cellWidget(row, 2).currentData(),
                "resampling": self.covariates.cellWidget(row, 3).currentText()})
        for key, field in (("mask", self.mask), ("constrain", self.constrain)):
            if field.path():
                request[key] = dict(field.record(), quantity="categorical", resampling="nearest")
        if operation == "prepare":
            path = Path(self.outputEdit.text().strip()).expanduser()
            if not self.outputEdit.text().strip() or not path.is_absolute():
                raise ValueError("Choose an absolute, new project directory that does not already exist")
            path = ensure_project_location(path, plugin_root=self.dialog.plugin_root, job_cache=self.dialog.job_cache,
                runtime_cache=getattr(self.dialog.runtime_controller.manager, "cache_root", None))
            if path.exists():
                raise ValueError("Choose an absolute, new project directory that does not already exist")
            request["output_dir"] = str(path)
            if not self._expected_inputs:
                raise ValueError("Check compatibility again to bind preparation to the reviewed files")
            request["expected_inputs"] = self._expected_inputs
        return request

    def _invalidate(self, *args):
        self._ready, self._checked, self._prepared_project = False, None, None
        self._expected_inputs = None
        if hasattr(self, "reportView"):
            self.reportView.setPlainText("Inputs changed. Check compatibility again before preparing.")
            self.reportDetails.clear()
            self.setButtonText(QtWidgets.QWizard.WizardButton.FinishButton, "Create prepared project")
            self._update_finish()

    def _page_changed(self, page_id):
        self.polygonColumn.setEnabled(self.mode.currentData() == "polygons")
        self._update_finish()

    def _output_changed(self, *args):
        if self._prepared_project:
            try:
                changed = Path(self.outputEdit.text().strip()).expanduser().resolve() != self._prepared_project
            except (OSError, ValueError, RuntimeError):
                changed = True
            if changed:
                self._prepared_project = None
                self.setButtonText(QtWidgets.QWizard.WizardButton.FinishButton, "Create prepared project")
                self.reportView.appendPlainText("\nDestination changed. The earlier prepared project is preserved; create this new destination before opening it.")
        self._update_finish()

    def _update_finish(self, *args):
        if not hasattr(self, "confirm"):
            return
        enabled = not self.controller.is_running and (self._prepared_project is not None or
            (self._ready and self.confirm.isChecked() and bool(self.outputEdit.text().strip())))
        self.button(QtWidgets.QWizard.WizardButton.FinishButton).setEnabled(enabled)

    def _set_busy(self, busy):
        for page in (self.sourcesPage, self.columnsPage, self.covariatePage):
            page.setEnabled(not busy)
        self.outputEdit.setEnabled(not busy)
        self.confirm.setEnabled(not busy)
        self.previewButton.setEnabled(not busy)
        for key in (QtWidgets.QWizard.WizardButton.BackButton, QtWidgets.QWizard.WizardButton.NextButton):
            self.button(key).setEnabled(not busy)
        self._update_finish()

    def inspect(self):
        if self.controller.is_running:
            return
        try:
            request = self._request("inspect")
            self._checked = request
            self._operation = "inspect"
            self.progress.setValue(0)
            self.progress.setFormat("Checking compatibility")
            if self.controller.start(request):
                self._set_busy(True)
            elif self._operation is not None:
                self._start_rejected()
        except Exception as exc:
            self.reportView.setPlainText(str(exc))

    def _start_rejected(self):
        self._operation, self._ready = None, False
        self._checked, self._expected_inputs = None, None
        self.progress.setValue(0)
        self.progress.setFormat("Operation did not start")
        self.reportView.setPlainText("The analysis engine is not available. Verify it on the Engine tab before trying again."
            if not self.dialog.runtime_controller.python else
            "Another task is running. Wait for it to finish before trying again.")
        self._set_busy(False)

    def _progress(self, percent, message):
        if self._operation:
            self.progress.setValue(percent)
            self.progress.setFormat(message)

    def _result(self, result):
        if not self._operation or result.get("operation") != self._operation:
            return
        operation, self._operation = self._operation, None
        self._set_busy(False)
        if self._close_pending:
            self._close_pending = False
            super().reject()
            return
        if not result.get("success"):
            self._ready = False
            self.progress.setValue(0)
            self.progress.setFormat("Operation did not complete")
            self.reportView.setPlainText(str(result.get("message", "Preparation failed")))
        else:
            report = result["report"]
            self._ready = report.get("ready") is True
            self.progress.setValue(100)
            self.progress.setFormat("Prepared project created" if operation == "prepare" else
                ("Compatibility check complete" if self._ready else "Check complete: inputs need attention"))
            if operation == "inspect":
                self._expected_inputs = report.get("inputs")
            lines = self._report_summary(report)
            for field, prefix in (("errors", "ERROR"), ("warnings", "WARNING")):
                for record in report.get(field, [])[:20]:
                    lines.append(f"{prefix}: {record.get('message', record) if isinstance(record, dict) else record}")
            self.reportView.setPlainText("\n".join(lines))
            self.reportDetails.setPlainText(json.dumps(report, ensure_ascii=False, indent=2)[:20000])
            if operation == "prepare":
                self._prepared_project = Path(result["output_dir"])
                self.setButtonText(QtWidgets.QWizard.WizardButton.FinishButton, "Open prepared project")
                self.reportView.appendPlainText("\nPrepared successfully. Click Open prepared project to switch; the previous project is preserved.")
        self._update_finish()

    @staticmethod
    def _report_summary(report):
        lines = ["Inputs are compatible." if report.get("ready") else "Some inputs need attention before preparation."]
        grid = report.get("reference_grid", {})
        if isinstance(grid, dict) and grid:
            lines.append(f"Reference grid: {grid.get('width', '?')} × {grid.get('height', '?')} cells · {grid.get('crs', 'CRS unavailable')}")
            transform = grid.get("transform")
            if isinstance(transform, list) and len(transform) >= 6:
                try:
                    x = math.hypot(float(transform[0]), float(transform[3]))
                    y = math.hypot(float(transform[1]), float(transform[4]))
                    lines.append(f"Pixel size: {x:,.6g} × {y:,.6g} CRS units. Reference values are not a support mask.")
                except (ValueError, TypeError):
                    pass
        coverage = report.get("coverage", {})
        zones = coverage.get("zones", {}) if isinstance(coverage, dict) else {}
        if isinstance(coverage, dict) and "zone_count" in coverage:
            lines.append(f"Census zones checked: {coverage['zone_count']}; unknown grid IDs: {coverage.get('unknown_id_count', 0)}")
        for raster in report.get("rasters", [])[:30]:
            name, quantity, method = raster.get("name", "Predictor"), raster.get("quantity"), raster.get("resampling")
            meaning = {"continuous": "continuous value", "categorical": "binary indicator (0/1)", "count": "aligned count; no redistribution"}.get(quantity, str(quantity))
            line = f"{name}: {meaning}; {method} if alignment is required"
            if isinstance(zones, dict) and name not in {"mask", "constrain"}:
                ratios = [entry["features"][name] / entry["eligible"] for entry in zones.values()
                    if isinstance(entry, dict) and entry.get("eligible", 0) > 0
                    and isinstance(entry.get("features"), dict) and name in entry["features"]]
                if ratios:
                    qualifier = "in displayed zone sample" if coverage.get("zones_truncated") else "across zones"
                    line += f"; minimum valid eligible-cell coverage {min(ratios):.1%} {qualifier}"
            lines.append(line)
        lines.append(f"Diagnostics: {report.get('error_count', len(report.get('errors', [])))} errors; {report.get('warning_count', len(report.get('warnings', [])))} warnings.")
        lines.append("Source files are preserved. Preparation rechecks the reviewed file fingerprints before creating the new project.")
        return lines

    def validateCurrentPage(self):
        if self.currentPage() is not self.reviewPage:
            return True
        if self.controller.is_running:
            return False
        if self._prepared_project:
            self.prepared.emit(self._prepared_project)
            return True
        if not self._ready or not self.confirm.isChecked():
            return False
        try:
            if self._checked != self._request("inspect"):
                raise ValueError("Inputs changed since the compatibility check; check again")
            request = self._request("prepare")
            self._operation = "prepare"
            self.progress.setValue(0)
            self.progress.setFormat("Preparing new project")
            if self.controller.start(request):
                self._set_busy(True)
            elif self._operation is not None:
                self._start_rejected()
        except Exception as exc:
            self.reportView.setPlainText(str(exc))
        return False

    def reject(self):
        if self._operation and self.controller.is_running:
            self._close_pending = True
            self.controller.stop()
            return
        super().reject()

    def closeEvent(self, event):
        if self._operation and self.controller.is_running:
            self._close_pending = True
            self.controller.stop()
            event.ignore()
        else:
            super().closeEvent(event)
