"""Optional onboarding and live readiness; never starts or mutates a project."""
from collections.abc import Mapping

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QEvent, pyqtSignal
from qgis.PyQt.QtGui import QImageReader, QPixmap
from qgis.core import QgsApplication, QgsSettings

from . import visual_style
from .workflow_status import bounded_status, plain_tooltip

STEPS = (("engine", "1 · Engine", "Set up / manage engine"),
         ("project", "2 · Project", "Create / open project"),
         ("inputs", "3 · Inputs", "Choose input data"),
         ("review", "4 · Review / run", "Review settings"))


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
        self._next_key = None
        self._styling = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        layout.addWidget(self.scroll)
        content = QtWidgets.QWidget()
        self.scroll.setWidget(content)
        body = QtWidgets.QVBoxLayout(content)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(12)

        # Identity: logo, name/version, explicit About.
        brand = QtWidgets.QHBoxLayout()
        brand.setSpacing(14)
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
                    brand.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignVCenter)
        identity = QtWidgets.QVBoxLayout()
        identity.setSpacing(0)
        self.title_label = self._label(plugin_info.name)
        visual_style.set_font(self.title_label, delta=5, bold=True)
        identity.addWidget(self.title_label)
        self.version_label = self._label(f"Version {plugin_info.version} · QGIS plugin for population mapping")
        identity.addWidget(self.version_label)
        brand.addLayout(identity, 1)
        self.about_button = QtWidgets.QPushButton("About / citation…")
        self.about_button.setToolTip("Authors, licence, links and the citation to use in publications")
        self.about_button.clicked.connect(self.requestedAbout.emit)
        brand.addWidget(self.about_button, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(brand)
        self.description_label = self._label(plugin_info.description)
        body.addWidget(self.description_label)
        self.citation_label = self._label(
            "Using results in research or reports? Please cite pypopRF; the reference is under About / citation."
            if plugin_info.citation else "")
        self.citation_label.setVisible(bool(plugin_info.citation))
        body.addWidget(self.citation_label)

        # The one next action, derived from live state only.
        self.next_card = QtWidgets.QFrame()
        self.next_card.setObjectName("homeNextCard")
        card = QtWidgets.QVBoxLayout(self.next_card)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(6)
        self.next_caption = self._label("Next step")
        visual_style.set_font(self.next_caption, bold=True)
        card.addWidget(self.next_caption)
        self.next_label = self._label("")
        visual_style.set_font(self.next_label, delta=2, bold=True)
        card.addWidget(self.next_label)
        actions = QtWidgets.QHBoxLayout()
        self.next_button = QtWidgets.QPushButton("")
        self.next_button.clicked.connect(self._next_clicked)
        actions.addWidget(self.next_button)
        actions.addStretch()
        card.addLayout(actions)
        body.addWidget(self.next_card)

        # Live step overview; each step navigates to its destination only.
        steps = QtWidgets.QGridLayout()
        steps.setHorizontalSpacing(12)
        steps.setVerticalSpacing(10)
        steps.setColumnMinimumWidth(0, 18)
        steps.setColumnMinimumWidth(1, 112)
        steps.setColumnStretch(2, 1)
        self.step_icons = {}
        self.step_titles = {}
        self.step_labels = {}
        self.step_buttons = {}
        signals = {"engine": self.requestedEngine, "project": self.requestedProject,
                   "inputs": self.requestedInputs, "review": self.requestedReview}
        for row, (key, title, caption) in enumerate(STEPS):
            icon = QtWidgets.QLabel()
            icon.setFixedSize(16, 16)
            title_label = self._label(title)
            title_label.setMinimumWidth(108)
            title_policy = title_label.sizePolicy()
            title_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Preferred)
            title_label.setSizePolicy(title_policy)
            label = self._label("")
            button = QtWidgets.QPushButton(caption)
            button.setMinimumWidth(170)
            button.clicked.connect(signals[key].emit)
            steps.addWidget(icon, row, 0, Qt.AlignmentFlag.AlignVCenter)
            steps.addWidget(title_label, row, 1)
            steps.addWidget(label, row, 2)
            steps.addWidget(button, row, 3)
            self.step_icons[key] = icon
            self.step_labels[key], self.step_buttons[key] = label, button
            self.step_titles[key] = title_label
        body.addLayout(steps)
        self.scope_label = self._label(
            "These checks describe the current selection. Starting an analysis still validates data "
            "compatibility and census support. Matching census totals is not proof of pixel accuracy.")
        body.addWidget(self.scope_label)

        self.guidance_toggle = QtWidgets.QToolButton()
        self.guidance_toggle.setText("How the two installation steps work")
        self.guidance_toggle.setCheckable(True)
        self.guidance_toggle.setAutoRaise(True)
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
        self.status_label = self._label("")
        body.addWidget(self.status_label)
        body.addStretch()
        self._icons = {"done": QgsApplication.getThemeIcon("/mIconSuccess.svg"),
                       "next": self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowRight)}
        self.apply_style()
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

    def apply_style(self):
        """Palette-derived scoped styles; safe to repeat on palette changes."""
        if self._styling:
            return
        self._styling = True
        try:
            for label in (self.version_label, self.citation_label, self.next_caption,
                          self.scope_label, self.guidance, self.status_label):
                visual_style.muted(label)
            visual_style.card(self.next_card, "info")
            visual_style.action_button(self.next_button, "primary")
        finally:
            self._styling = False

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "next_card"):
            self.apply_style()

    def _show_guidance(self, expanded):
        self.guidance.setVisible(expanded)
        self.guidance_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _guidance_toggled(self, expanded):
        self._show_guidance(expanded)
        self.settings.setValue(self.GUIDANCE_KEY, bool(expanded))

    def _next_clicked(self):
        signal = {"engine": self.requestedEngine, "project": self.requestedProject,
                  "inputs": self.requestedInputs, "review": self.requestedReview}.get(self._next_key)
        if signal is not None and not self.state.get("busy"):
            signal.emit()

    def refresh(self, info):
        """Recompute live state; a stored preference cannot make a step ready."""
        info = info if isinstance(info, Mapping) else {}
        engine = info.get("engine_ready") is True
        project = info.get("project_ready") is True
        inputs = project and info.get("inputs_ready") is True
        busy = info.get("busy") is True
        engine_state = info.get("engine_state")
        checking = not engine and engine_state == "checking"
        self.state = {"engine": engine, "project": project, "inputs": inputs,
                      "review": engine and project and inputs, "busy": busy}
        self.step_labels["engine"].setText(
            "Ready · isolated engine verified" + (" · last repair or check failed, see Engine"
                                                   if engine_state == "repair_failed" else "")
            if engine else "Checking the engine…" if checking else "Needed before calculation")
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
        # While the first engine check runs, nothing is known yet: point at the project instead.
        self._next_key = ("engine" if not engine and not checking else
                          "project" if not project else "inputs" if not inputs else "review")
        self.next_label.setText("A task is running. Follow its progress or stop it from the main controls." if busy else
            "Checking the analysis engine. Creating or opening a project waits until the check ends." if checking and not project else
            "Set up the analysis engine. Creating or opening a project first is also fine." if not engine and not checking else
            "Create or open a project." if not project else
            "Choose your input data." if not inputs else
            "Review the settings, then use Run analysis at the bottom of the window." if engine else
            "Review the settings; the engine is still being checked.")
        self.next_button.setText({"engine": "Set up engine", "project": "Create / open project",
                                  "inputs": "Choose input data", "review": "Review settings"}[self._next_key])
        self.next_button.setEnabled(not busy and self.step_buttons[self._next_key].isEnabled())
        done = {"engine": engine, "project": project, "inputs": inputs, "review": False}
        for key, icon in self.step_icons.items():
            kind = "done" if done[key] else "next" if key == self._next_key and not busy else None
            icon.setPixmap(self._icons[kind].pixmap(16, 16) if kind else QPixmap())
        path = str(info.get("project_path", ""))[:4096]
        self.step_labels["project"].setToolTip(plain_tooltip(path) if project and path else "")
        self.status_label.setText(bounded_status(info.get("status", "")))
