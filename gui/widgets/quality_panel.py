"""Native Qt diagnostics dashboard; saved OOF zones, never pixel-confidence maps."""
from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...services.quality_report import QualityReport, load_quality_report


def _number(value):
    return "unavailable" if value is None else f"{value:.4g}"


class OOFScatter(QWidget):
    """Palette-aware, bounded deterministic sample of recorded held-out zones."""
    MAX_PLOT_POINTS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = ()
        self.setMinimumHeight(210)
        self.setAccessibleName("Observed versus held-out predicted census-zone density")

    def set_points(self, points):
        self.points = points
        self.update()

    def _plot_sample(self):
        count = min(len(self.points), self.MAX_PLOT_POINTS)
        if count <= 1:
            return self.points
        # Spread the bounded sample across the entire saved order, including
        # both endpoints; do not silently discard its final geographic regions.
        return tuple(self.points[index * (len(self.points) - 1) // (count - 1)] for index in range(count))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        painter.setPen(palette.text().color())
        if not self.points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No validated held-out zone predictions available")
            return
        area = QRectF(70, 18, max(1, self.width() - 100), max(1, self.height() - 70))
        maximum = max(1e-12, max(max(point.observed, point.predicted) for point in self.points))
        painter.drawLine(area.bottomLeft(), area.bottomRight())
        painter.drawLine(area.bottomLeft(), area.topLeft())
        painter.drawText(QRectF(area.left(), area.bottom() + 12, area.width(), 20),
                         Qt.AlignmentFlag.AlignCenter, f"Observed zone density (0–{maximum:.3g})")
        painter.save()
        painter.translate(18, area.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-area.height() / 2, -12, area.height(), 20),
                         Qt.AlignmentFlag.AlignCenter, "OOF density")
        painter.restore()
        painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashLine))
        painter.drawLine(area.bottomLeft(), area.topRight())
        painter.setPen(QPen(palette.highlight().color(), 2))
        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        shown = self._plot_sample()
        for point in shown:
            painter.drawEllipse(QPointF(area.left() + (point.observed / maximum) * area.width(),
                                        area.bottom() - (point.predicted / maximum) * area.height()), 2, 2)
        painter.end()


class QualityPanel(QWidget):
    showZonesRequested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.report = QualityReport()
        self.status_label = self._label()
        self.conservation_label = self._label()
        self.metrics_label = self._label()
        self.plot_note = self._label()
        self.scatter = OOFScatter(self)
        self.error_table = self._table(["Zone ID", "Observed", "Held-out predicted", "Absolute error"])
        self.error_table.setAccessibleName("Highest held-out zone-density errors")
        self.feature_table = self._table(["Feature", "Importance", "Permutation spread"])
        self.feature_table.setAccessibleName("Training-only permutation feature importance")
        self.show_zones_button = QPushButton("Show selected / top error zones in QGIS", self)
        self.show_zones_button.clicked.connect(self._show_zones)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(135)
        self.details.document().setMaximumBlockCount(100)
        self.details.setAccessibleName("Validation limitations and artifact diagnostics")
        layout = QVBoxLayout(self)
        for widget in (self.status_label, self.conservation_label, self.metrics_label, self.scatter, self.plot_note):
            layout.addWidget(widget)
        tables = QHBoxLayout()
        for title, table in (("Highest-error census zones", self.error_table),
                             ("Feature impact (training holdout)", self.feature_table)):
            group = QGroupBox(title, self)
            box = QVBoxLayout(group)
            box.addWidget(table)
            tables.addWidget(group)
        self.error_table.setToolTip("Absolute held-out zone-density errors, not census-total mismatches")
        self.feature_table.setToolTip("Normalized permutation RMSE impact; spread across permutations is not population uncertainty")
        layout.addLayout(tables)
        layout.addWidget(self.show_zones_button)
        layout.addWidget(self.details)
        self.load_run(None)

    def _label(self):
        label = QLabel(self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _table(self, headers):
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(160)
        return table

    def load_run(self, run_dir):
        self.report = load_quality_report(run_dir)
        report = self.report
        scheme = {"spatial_blocks": "Spatial blocks", "group": "User-defined groups",
                  "shuffled_zone": "Shuffled-zone diagnostic"}.get(report.validation_scheme, report.validation_scheme)
        self.status_label.setText(f"Run: {report.run_status} · Validation: {report.cv_status} · Strategy: {scheme}")
        self.conservation_label.setText(f"Census conservation: {report.conservation_label}")
        scores = dict(report.metrics)
        text = f"Held-out zonal density · RMSE: {_number(scores.get('rmse'))} · MAE: {_number(scores.get('mae'))} · R²: {_number(scores.get('r2'))}"
        if report.baseline_metrics:
            baseline = dict(report.baseline_metrics)
            text += f"\nSame-fold training-mean baseline: {_number(baseline['rmse'])} RMSE · {_number(baseline['mae'])} MAE"
        units = "people per eligible mastergrid pixel" if report.target_units == "population_per_eligible_mastergrid_pixel" else report.target_units
        self.metrics_label.setText(text + f"\nUnits: {units}")
        self.scatter.set_points(report.points)
        self.plot_note.setText(f"OOF records: {len(report.points)} zones; plot shows up to {OOFScatter.MAX_PLOT_POINTS}. "
                               "Dashed line = observed equals predicted. No pixel-confidence claim.")
        errors = report.high_error_zones
        self.error_table.setRowCount(len(errors))
        for row, point in enumerate(errors):
            values = (str(point.zone_id), _number(point.observed), _number(point.predicted), _number(point.absolute_error))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, point.zone_id)
                self.error_table.setItem(row, column, item)
        self.feature_table.setRowCount(len(report.feature_importance))
        for row, feature in enumerate(report.feature_importance):
            for column, value in enumerate((feature.feature, _number(feature.importance), _number(feature.std))):
                self.feature_table.setItem(row, column, QTableWidgetItem(value))
        self.show_zones_button.setEnabled(bool(errors))
        self.details.setPlainText("\n".join((*report.limits, *report.errors)))
        return report

    def _show_zones(self):
        rows = {index.row() for index in self.error_table.selectionModel().selectedRows()}
        zone_ids = [self.error_table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in sorted(rows)] if rows else None
        request = self.report.zone_request(zone_ids)
        if request["zone_ids"]:
            self.showZonesRequested.emit(request)
