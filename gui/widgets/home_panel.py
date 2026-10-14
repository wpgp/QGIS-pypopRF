"""Optional onboarding and live readiness; never starts or mutates a project."""
from collections.abc import Mapping

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QImageReader, QPixmap
from qgis.core import QgsSettings

from .workflow_status import bounded_status, plain_tooltip


class HomePanel(QtWidgets.QWidget):
    requestedEngine = pyqtSignal()
    requestedProject = pyqtSignal()
    requestedInputs = pyqtSignal()
    requestedReview = pyqtSignal()
    requestedAbout = pyqtSignal()
    GUIDANCE_KEY = "pypopRF/onboarding/guidanceExpanded"

    def __init__(self, plugin_info, parent=None, settings=None):
        super().__init__(parent)
        self.plugin_info = plugin_info
        self.settings = settings if settings is not None else QgsSettings()
        self.state = {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        layout.addWidget(self.scroll)
        content = QtWidgets.QWidget()
        self.scroll.setWidget(content)
        body = QtWidgets.QVBoxLayout(content)
        body.setContentsMargins(16, 12, 16, 12)
        body.setSpacing(12)
        brand = QtWidgets.QHBoxLayout()
        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setAccessibleName("Packaged project logo")
        if plugin_info.logo_path:
            reader = QImageReader(str(plugin_info.logo_path))
            size = reader.size()
            if 0 < size.width() <= 4096 and 0 < size.height() <= 4096 and size.width() * size.height() <= 8_000_000:
                pixmap = QPixmap.fromImage(reader.read())
                if not pixmap.isNull():
                    self.logo_label.setPixmap(pixmap.scaled(150, 58, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    brand.addWidget(self.logo_label)
        self.title_label = self._label(f"{plugin_info.name}  {plugin_info.version}")
        font = self.title_label.font()
        font.setPointSizeF(max(10, font.pointSizeF()) + 3)
        font.setBold(True)
        self.title_label.setFont(font)
        brand.addWidget(self.title_label, 1)
        self.about_button = QtWidgets.QPushButton("About / citation…")
        self.about_button.clicked.connect(self.requestedAbout.emit)
        brand.addWidget(self.about_button)
        body.addLayout(brand)
        self.description_label = self._label(plugin_info.description)
        body.addWidget(self.description_label)
        self.guidance_toggle = QtWidgets.QToolButton()
        self.guidance_toggle.setText("How the two installation steps work")
        self.guidance_toggle.setCheckable(True)
        self.guidance_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        expanded = self.settings.value(self.GUIDANCE_KEY, True, type=bool)
        self.guidance_toggle.setChecked(expanded)
        body.addWidget(self.guidance_toggle)
        self.guidance = self._label(
            "1. Enable the QGIS plugin from its ZIP. You can create or open a project now.\n"
            "2. Set up the separate analysis engine before calculating. It uses an existing 64-bit "
            "Python 3.12 and a writable user cache; first setup downloads locked packages.\n"
            "The plugin does not install numerical packages into QGIS or download Python. "
            "Keep projects and input data outside the plugin and engine-cache folders.")
        body.addWidget(self.guidance)
        self._show_guidance(expanded)
        self.guidance_toggle.toggled.connect(self._guidance_toggled)
        self.next_label = self._label("")
        next_font = self.next_label.font()
        next_font.setBold(True)
        self.next_label.setFont(next_font)
        body.addWidget(self.next_label)
        steps = QtWidgets.QGridLayout()
        steps.setHorizontalSpacing(14)
        steps.setVerticalSpacing(12)
        steps.setColumnMinimumWidth(0, 120)
        steps.setColumnStretch(1, 1)
        self.step_titles = {}
        self.step_labels = {}
        self.step_buttons = {}
        for row, (key, title, caption, signal) in enumerate((
                ("engine", "1 · Engine", "Set up / manage engine", self.requestedEngine),
                ("project", "2 · Project", "Create / open project", self.requestedProject),
                ("inputs", "3 · Inputs", "Choose input data", self.requestedInputs),
                ("review", "4 · Review / run", "Review settings", self.requestedReview))):
            title_label = self._label(title)
            title_label.setMinimumWidth(108)
            title_policy = title_label.sizePolicy()
            title_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Preferred)
            title_label.setSizePolicy(title_policy)
            label = self._label("")
            button = QtWidgets.QPushButton(caption)
            button.setMinimumWidth(170)
            button.clicked.connect(signal.emit)
            steps.addWidget(title_label, row, 0)
            steps.addWidget(label, row, 1)
            steps.addWidget(button, row, 2)
            self.step_labels[key], self.step_buttons[key] = label, button
            self.step_titles[key] = title_label
        body.addLayout(steps)
        self.scope_label = self._label(
            "These checks describe the current selection. Starting an analysis still validates data "
            "compatibility and census support. Matching census totals is not proof of pixel accuracy.")
        body.addWidget(self.scope_label)
        self.status_label = self._label("")
        body.addWidget(self.status_label)
        body.addStretch()
        self.refresh({})

    @staticmethod
    def _label(text):
        label = QtWidgets.QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                      QtWidgets.QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        return label

    def _show_guidance(self, expanded):
        self.guidance.setVisible(expanded)
        self.guidance_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _guidance_toggled(self, expanded):
        self._show_guidance(expanded)
        self.settings.setValue(self.GUIDANCE_KEY, bool(expanded))

    def refresh(self, info):
        """Recompute live state; a stored preference cannot make a step ready."""
        info = info if isinstance(info, Mapping) else {}
        engine = info.get("engine_ready") is True
        project = info.get("project_ready") is True
        inputs = project and info.get("inputs_ready") is True
        busy = info.get("busy") is True
        self.state = {"engine": engine, "project": project, "inputs": inputs,
                      "review": engine and project and inputs, "busy": busy}
        self.step_labels["engine"].setText("Ready · isolated engine verified" if engine else "Needed before calculation")
        self.step_labels["project"].setText("Ready · current project is open" if project else "Create or open an external project folder")
        self.step_labels["inputs"].setText("Selected · grid, census and covariates" if inputs else "Add a zone grid, census CSV and covariates")
        self.step_labels["review"].setText("Ready to review and run" if self.state["review"] else
            "You can review now; engine setup is still needed" if project and inputs else "Available after project and input selection")
        self.step_buttons["engine"].setEnabled(not busy)
        self.step_buttons["project"].setEnabled(not busy)
        self.step_buttons["inputs"].setEnabled(project and not busy)
        self.step_buttons["review"].setEnabled(project and inputs and not busy)
        self.step_buttons["engine"].setText("Manage engine" if engine else "Set up engine")
        self.step_buttons["project"].setText("View / open project" if project else "Create / open project")
        self.next_label.setText("A task is running. Follow its progress or stop it from the main controls." if busy else
            "Next: set up the engine. Creating or opening a project first is also fine." if not engine else
            "Next: create or open a project." if not project else
            "Next: choose your input data." if not inputs else
            "Next: review the settings, then use Run analysis when you are ready.")
        path = str(info.get("project_path", ""))[:4096]
        self.step_labels["project"].setToolTip(plain_tooltip(path) if project and path else "")
        self.status_label.setText(bounded_status(info.get("status", "")))
