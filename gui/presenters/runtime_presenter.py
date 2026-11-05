"""Stateful engine view without package installation in the QGIS host.

Discovery, interpreter choice, setup and maintenance are distinct states.
Readiness itself is owned by RuntimeController.python; this presenter only
derives which controls and wording to show from it.
"""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QUrl, QSignalBlocker
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsApplication

from ..widgets import visual_style
from ..widgets.workflow_status import (
    bounded_status, short_path, plain_tooltip, interpreter_label, engine_view_state, engine_next_step,
    ENGINE_CHECKING, ENGINE_NO_PYTHON, ENGINE_UNDISCOVERED, ENGINE_SELECTED, ENGINE_INSTALLING,
    ENGINE_READY, ENGINE_REPAIR_FAILED, ENGINE_FAILED)

SOURCE_LABELS = {"registry-user": "Installed for you", "registry-machine": "System installation",
                 "standard-install": "Installed Python", "py-launcher": "Python launcher",
                 "host-base": "QGIS Python", "host-prefix": "QGIS Python", "qgis-embedded": "QGIS Python",
                 "PATH": "On PATH", "verified": "Verified", "legacy": "Detected"}

TITLES = {
    ENGINE_CHECKING: "Checking the analysis engine…",
    ENGINE_NO_PYTHON: "No compatible Python found",
    ENGINE_UNDISCOVERED: "Engine not set up",
    ENGINE_SELECTED: "Engine not set up yet",
    ENGINE_INSTALLING: "Setting up the analysis engine…",
    ENGINE_READY: "Ready to calculate",
    ENGINE_REPAIR_FAILED: "Repair failed · previous engine still in use",
    ENGINE_FAILED: "Engine setup failed",
}

HELP = {
    ENGINE_CHECKING: "Checks run in the background. Existing project information can still be "
                     "inspected; creating or opening a project waits until the check finishes.",
    ENGINE_NO_PYTHON: "The engine needs an installed 64-bit CPython 3.12. Install it with "
                      "Get Python 3.12…, then choose Find Python again. The plugin never installs "
                      "or changes system Python.",
    ENGINE_UNDISCOVERED: "The search for Python did not finish, so no interpreter is listed yet. "
                         "Choose Find Python again.",
    ENGINE_SELECTED: "Choosing a Python installs nothing. Set up engine creates a separate environment "
                     "and downloads verified, hash-locked packages; this is needed once.",
    ENGINE_INSTALLING: "Package downloads show activity rather than a byte percentage. Existing project "
                       "information can still be inspected; creating or opening a project waits until "
                       "preparation finishes, and calculations until the engine is verified.",
    ENGINE_READY: "The engine is verified each time the plugin opens.",
    ENGINE_REPAIR_FAILED: "Calculations keep using the previously verified engine. Review the message "
                          "above; retry from Manage engine when ready. Full messages are in Details.",
    ENGINE_FAILED: "Review the message above, then try Set up engine again or choose another Python. "
                   "Full messages are in Details.",
}

ICONS = {
    ENGINE_CHECKING: ("style", QtWidgets.QStyle.StandardPixmap.SP_BrowserReload),
    ENGINE_NO_PYTHON: ("style", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning),
    ENGINE_UNDISCOVERED: ("style", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation),
    ENGINE_SELECTED: ("style", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation),
    ENGINE_INSTALLING: ("style", QtWidgets.QStyle.StandardPixmap.SP_BrowserReload),
    ENGINE_READY: ("theme", "/mIconSuccess.svg"),
    ENGINE_REPAIR_FAILED: ("style", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning),
    ENGINE_FAILED: ("style", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical),
}

ACCENTS = {ENGINE_READY: "success", ENGINE_REPAIR_FAILED: "warning", ENGINE_FAILED: "critical",
           ENGINE_NO_PYTHON: "warning", ENGINE_INSTALLING: "info", ENGINE_CHECKING: None,
           ENGINE_SELECTED: "info", ENGINE_UNDISCOVERED: None}


def is_fresh_discovery(operation, result):
    """Whether a completed result carries a fresh interpreter listing (possibly empty).

    An explicit search always discovers; a plain check discovers only when no
    engine was found. Setup, failed and cancelled results list nothing new.
    """
    return (operation not in {"setup", "inspect"} and not result.get("error")
            and not result.get("cancelled") and (operation == "discover" or not result.get("python")))


def manual_selection_verified(manual, text, verified):
    """A manual path counts only while it is exactly the path the last successful probe accepted."""
    return bool(manual and verified and str(text).strip() == verified)


class RuntimePresenter:
    def __init__(self, view):
        self.view = view
        self._filling = False
        self._closed = False
        # The dialog starts the first asynchronous check right after construction;
        # until a result arrives nothing about Python availability is known.
        self._operation = "check"
        self._has_result = False
        self._discovery_empty = False
        self._manual_verified = None  # manual path accepted by the latest successful probe
        self._failure = None  # (kind, message); kept until a newer attempt supersedes it
        self._choice_note = ""
        self.state = ENGINE_CHECKING
        self._styled_state = None
        self.error = view.runtimeErrorLabel
        for label in (view.runtimeStatusLabel, view.runtimeHelpLabel, view.engineSummaryLabel,
                      view.engineIntroLabel, view.engineAdvancedLabel, view.pythonChoiceHint):
            visual_style.wrap_label(label)
        visual_style.wrap_label(self.error, selectable=True)
        visual_style.wrap_label(view.engineStateTitle)
        view.runtimeStatusLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        view.engineSummaryLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        visual_style.set_font(view.engineStateTitle, delta=3, bold=True)
        self.error.hide()
        view.cancelSetupButton.hide()
        view.engineSummaryLabel.hide()
        view.engineAdvancedLabel.hide()
        view.engineAdvancedToggle.setArrowType(Qt.ArrowType.RightArrow)
        view.pythonComboBox.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        view.pythonComboBox.setMinimumContentsLength(18)
        view.pythonComboBox.setToolTip("Only verified CPython 3.12, 64-bit installations are listed.")
        view.pythonPathEdit.hide()
        view.browsePythonButton.hide()
        view.cancelSetupButton.setIcon(view.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCancelButton))
        view.manualPythonCheckBox.toggled.connect(self._manual_toggled)
        view.engineAdvancedToggle.toggled.connect(self._advanced_toggled)
        view.engineNextButton.clicked.connect(self._next)
        view.pythonComboBox.currentIndexChanged.connect(self.selected)
        view.pythonPathEdit.editingFinished.connect(self.manual_finished)
        view.pythonPathEdit.textChanged.connect(self._path_changed)
        view.refreshPythonButton.clicked.connect(self.discover)
        view.downloadPythonButton.clicked.connect(self.download)
        if hasattr(view.runtime_controller, "interpreterChecked"):
            view.runtime_controller.interpreterChecked.connect(self.inspected)
        self.render()

    # -- state -----------------------------------------------------------------
    def view_state(self):
        v = self.view
        operation = (self._operation or "check") if v.runtime_controller.is_running else None
        if not self._has_result and operation is None:
            operation = "check"
        failed = bool(self._failure) and self._failure[0] in {"setup", "check", "discover"}
        return engine_view_state(operation, bool(v.runtime_controller.python),
                                 v.pythonComboBox.count() > 0 or self.manual_verified(),
                                 self._discovery_empty, failed)

    def manual_verified(self):
        v = self.view
        return manual_selection_verified(v.manualPythonCheckBox.isChecked(), v.pythonPathEdit.text(),
                                         self._manual_verified)

    def render(self):
        """Show the controls of the current state only; text/status stay owned by events."""
        v = self.view
        state = self.state = self.view_state()
        ready = state in {ENGINE_READY, ENGINE_REPAIR_FAILED}
        manual = v.manualPythonCheckBox.isChecked()
        manual_ok = self.manual_verified()
        listed = v.pythonComboBox.count() > 0
        has_choices = listed or manual_ok
        advanced = ready and v.engineAdvancedToggle.isChecked()
        title = TITLES[state]
        if self._failure and self._failure[0] != "setup":
            # A failed check/discovery is not a failed repair; say which one happened.
            title = {ENGINE_REPAIR_FAILED: "Engine check failed · previous engine still in use",
                     ENGINE_FAILED: "Engine check failed"}.get(state, title)
        v.engineStateTitle.setText(title)
        v.runtimeHelpLabel.setText(HELP[state])
        if state != self._styled_state:
            self._styled_state = state
            self.apply_style()
        if state == ENGINE_CHECKING:
            v.runtimeProgressBar.setRange(0, 0)
            v.runtimeProgressBar.show()
        elif state != ENGINE_INSTALLING:
            v.runtimeProgressBar.hide()
        python = v.runtime_controller.python
        if ready and python:
            required = getattr(v.runtime_controller.manager, "PYTHON_VERSION", None)
            version = ("Python " + ".".join(map(str, required)) + " · ") if required else ""
            v.engineSummaryLabel.setText(f"Isolated engine · {version}verified against this plugin's "
                                         f"locked package list\n{short_path(python, 72)}")
            v.engineSummaryLabel.setToolTip(plain_tooltip(python))
        v.engineSummaryLabel.setVisible(bool(ready and python))
        key, caption = engine_next_step(getattr(v, "_home_state", {}))
        v.engineNextButton.setText(caption)
        v.engineNextButton.setVisible(ready)
        v.engineAdvancedToggle.setVisible(ready)
        v.engineAdvancedToggle.setArrowType(Qt.ArrowType.DownArrow if advanced else Qt.ArrowType.RightArrow)
        v.engineAdvancedLabel.setVisible(advanced)
        v.pythonChoiceGroup.setVisible(
            state in {ENGINE_NO_PYTHON, ENGINE_UNDISCOVERED, ENGINE_SELECTED, ENGINE_FAILED} or advanced)
        v.pythonChoiceGroup.setTitle("Python used for repair or rebuild" if ready else "Python for the engine")
        hint = ("Repair / update uses the Python selected here only if the engine must be rebuilt."
                if ready else
                "Only verified 64-bit CPython 3.12 installations are listed. Selecting one installs nothing.")
        v.pythonChoiceHint.setText(hint + ("\n" + self._choice_note if self._choice_note else ""))
        v.pythonComboBox.setVisible(listed)
        v.pythonPathEdit.setVisible(manual)
        v.browsePythonButton.setVisible(manual)
        v.setupRuntimeButton.setText("Repair / update engine" if ready else "Set up engine")
        v.setupRuntimeButton.setVisible(ready or has_choices or manual)
        # Get Python only when a completed search found nothing, or in manual recovery
        # while the typed path is not (or no longer) verified.
        v.downloadPythonButton.setVisible((self._discovery_empty and not has_choices) or (manual and not manual_ok))
        self.error.setVisible(bool(self._failure))
        if self._failure:
            self.error.setText(bounded_status(self._failure[1]))

    def apply_style(self):
        """Re-apply palette-derived appearance (state change or palette change)."""
        v = self.view
        state = self.state
        visual_style.card(v.runtimeGroup, ACCENTS.get(state))
        visual_style.message(self.error, "warning" if state == ENGINE_REPAIR_FAILED else "critical")
        for label in (v.runtimeHelpLabel, v.engineIntroLabel, v.engineAdvancedLabel, v.pythonChoiceHint):
            visual_style.muted(label)
        kind, name = ICONS[state]
        icon = QgsApplication.getThemeIcon(name) if kind == "theme" else v.style().standardIcon(name)
        v.engineStateIcon.setPixmap(icon.pixmap(32, 32))
        visual_style.action_button(v.engineNextButton, "primary")
        visual_style.action_button(v.setupRuntimeButton,
                                   "primary" if state in {ENGINE_SELECTED, ENGINE_FAILED} else "normal")

    def focus_target(self):
        v = self.view
        return {ENGINE_READY: v.engineNextButton, ENGINE_REPAIR_FAILED: v.engineNextButton,
                ENGINE_INSTALLING: v.cancelSetupButton, ENGINE_SELECTED: v.setupRuntimeButton,
                ENGINE_FAILED: v.setupRuntimeButton if v.setupRuntimeButton.isVisible() else v.refreshPythonButton,
                ENGINE_NO_PYTHON: v.refreshPythonButton, ENGINE_UNDISCOVERED: v.refreshPythonButton,
                }.get(self.view_state(), v.engineStateTitle)

    def _next(self):
        key, _ = engine_next_step(getattr(self.view, "_home_state", {}))
        self.view._go_to_step(key)

    def _manual_toggled(self, checked):
        self.render()

    def _path_changed(self, text):
        # Any other path than the probed one is unverified until probed again.
        if self._manual_verified is not None and text.strip() != self._manual_verified:
            self._manual_verified = None
            if not self._closed:
                self.render()

    def _advanced_toggled(self, checked):
        self.render()

    # -- actions ---------------------------------------------------------------
    def _controls(self, enabled):
        v = self.view
        for widget in (v.setupRuntimeButton, v.pythonComboBox, v.pythonPathEdit, v.browsePythonButton,
                       v.refreshPythonButton, v.manualPythonCheckBox):
            widget.setEnabled(enabled)

    def discover(self):
        if self.view.is_busy:
            return
        self._controls(False)
        self._operation = "discover"
        self.view.runtimeStatusLabel.setText("Finding compatible Python installations…")
        self.view.cancelSetupButton.show()
        self.view.runtime_controller.check(discover=True)
        self.view.begin_task("Finding compatible Python installations")
        self.view.set_task_status("Finding compatible Python installations…")
        self.view._refresh_readiness()

    def download(self):
        box = QtWidgets.QMessageBox(self.view)
        box.setWindowTitle("Install Python for the separate engine")
        box.setText("Install Python 3.12 (64-bit), then choose Find Python again. "
                    "The plugin will not install or change system Python automatically.")
        box.setInformativeText("Open the official Python download page in your browser? Choose a 3.12, 64-bit installer.")
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Open | QtWidgets.QMessageBox.StandardButton.Cancel)
        if box.exec() == QtWidgets.QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl("https://www.python.org/downloads/windows/"))

    def selected(self, index):
        if self._filling or index < 0 or self.view.is_busy:
            return
        candidate = self.view.pythonComboBox.itemData(index)
        if candidate:
            self._manual_verified = None  # a listed choice replaces the manual selection
            self.view.pythonPathEdit.setText(candidate["path"])
            if self._failure and self._failure[0] in {"inspect", "selection"}:
                self._failure = None
            if self.view.runtime_controller.python:
                self._choice_note = "Selected for a possible rebuild; the current engine is unchanged."
            else:
                self._choice_note = ""
                self.view.runtimeStatusLabel.setText("Compatible Python selected; choose Set up engine.")
            self.render()

    def changed(self, result):
        v = self.view
        operation = self._operation or "check"
        self._operation = None
        self._has_result = True
        ready = bool(result.get("python"))
        choices = result.get("interpreters") or [
            {"path": str(p), "version": "3.12", "bits": 64, "source": "verified", "recommended": i == 0}
            for i, p in enumerate(result.get("candidates", []))]
        if choices:
            previous = v.pythonPathEdit.text()
            self._filling = True
            blocker = QSignalBlocker(v.pythonComboBox)
            v.pythonComboBox.clear()
            wanted = 0
            for i, item in enumerate(choices):
                v.pythonComboBox.addItem(interpreter_label(item, SOURCE_LABELS), item)
                v.pythonComboBox.setItemData(i, plain_tooltip(item["path"]), Qt.ItemDataRole.ToolTipRole)
                if item["path"] == previous:
                    wanted = i
            v.pythonComboBox.setCurrentIndex(wanted)
            del blocker
            self._filling = False
            if not previous or not v.manualPythonCheckBox.isChecked():
                v.pythonPathEdit.setText(choices[wanted]["path"])
            self._discovery_empty = False
        elif is_fresh_discovery(operation, result):
            # Only a completed, error-free search that listed nothing proves "no Python".
            # Its listing supersedes earlier records; explicit manual text stays.
            self._discovery_empty = True
            self._filling = True
            blocker = QSignalBlocker(v.pythonComboBox)
            v.pythonComboBox.clear()
            del blocker
            self._filling = False
            if not v.manualPythonCheckBox.isChecked():
                v.pythonPathEdit.clear()
        self._choice_note = ""
        self._controls(True)
        v.runtimeProgressBar.hide()
        v.runtimeProgressBar.setRange(0, 100)
        v.cancelSetupButton.hide()
        error = result.get("error")
        if result.get("cancelled"):
            message = "Engine check cancelled; the previous verified engine remains available." if ready else (
                "Engine operation cancelled. Set up a compatible engine before calculating.")
            v.runtimeStatusLabel.setText(message)
            v.set_task_status(message)
            v.logger.info(message)
        elif error:
            if operation == "setup":
                prefix = ("Engine repair failed; the previous engine remains available: " if ready
                          else "Engine setup failed: ")
            else:
                prefix = ("Engine check failed; the previous engine remains available: " if ready
                          else "Engine check failed: ")
            self.show_error(prefix + str(error), kind="setup" if operation == "setup" else "check")
        else:
            # A newer success supersedes failures of the same kind; a failed repair stays
            # visible after later checks, because the repair itself still did not succeed.
            if self._failure and (operation == "setup" or self._failure[0] != "setup"):
                self._failure = None
            message = "Analysis engine ready" if ready else (
                "Choose a compatible Python below, then Set up engine." if choices else
                "Selected Python is compatible. Choose Set up engine." if self.manual_verified() else
                "No compatible Python found. Install Python 3.12 (64-bit), then Find Python again."
                if self._discovery_empty else
                "Python discovery did not complete. Choose Find Python again.")
            if result.get("reason") and not ready:
                message += " " + str(result["reason"])
            v.runtimeStatusLabel.setText(message)
            if not ready:
                v.set_task_status(message)
        v._refresh_readiness()

    def show_error(self, message, kind="selection"):
        v = self.view
        self._failure = (kind, message)
        self.error.setText(bounded_status(message))
        self.error.show()
        v.runtimeStatusLabel.setText(bounded_status(message))
        v.set_task_status(message)
        v.logger.error(message)

    def inspect(self, path):
        v = self.view
        if hasattr(v.runtime_controller, "inspect") and not v.is_busy:
            self._manual_verified = None  # only this probe's outcome may verify the path
            self._controls(False)
            if self._failure and self._failure[0] in {"inspect", "selection"}:
                self._failure = None
            self._operation = "inspect"
            v.runtimeStatusLabel.setText("Checking the selected Python…")
            v.cancelSetupButton.show()
            if not v.runtime_controller.inspect(path):
                self._operation = None
                self._controls(True)
                v.cancelSetupButton.hide()
                self.render()
            else:
                v.begin_task("Checking selected Python")
                v.set_task_status("Checking the selected Python…")
                v._refresh_readiness()

    def manual_finished(self):
        if not self._closed and self.view.manualPythonCheckBox.isChecked():
            path = self.view.pythonPathEdit.text().strip()
            if path:
                self.inspect(path)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.view.pythonPathEdit.editingFinished.disconnect(self.manual_finished)
        except (TypeError, RuntimeError):
            pass

    def inspected(self, result):
        self._operation = None
        self._controls(True)
        self.view.cancelSetupButton.hide()
        if self.view._dispose_pending:
            return
        ready = bool(self.view.runtime_controller.python)
        self._manual_verified = None
        if not result.get("error") and manual_selection_verified(
                self.view.manualPythonCheckBox.isChecked(), self.view.pythonPathEdit.text(), result.get("path")):
            self._manual_verified = str(result["path"]).strip()
        if result.get("error"):
            self.show_error("Selected Python cannot be used: " + str(result["error"]) +
                            ". Choose a listed compatible interpreter or install Python 3.12 (64-bit).",
                            kind="inspect")
            if ready:
                self.view.runtimeStatusLabel.setText("Analysis engine ready")
        else:
            if self._failure and self._failure[0] in {"inspect", "selection"}:
                self._failure = None
            if ready:
                self._choice_note = "Selected Python is compatible; the current engine is unchanged."
                self.view.runtimeStatusLabel.setText("Analysis engine ready")
            else:
                self.view.runtimeStatusLabel.setText("Selected Python is compatible. Choose Set up engine.")
        self.view._refresh_readiness()

    def browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.view, "Select installed Python 3.12 (64-bit)", "", "All files (*)")
        if path:
            self.view.manualPythonCheckBox.setChecked(True)
            self.view.pythonPathEdit.setText(path)
            self.inspect(path)

    def setup(self):
        v = self.view
        if v.is_busy:
            return
        python = v.pythonPathEdit.text().strip()
        if not python and v.runtime_controller.python:
            python = str(v.runtime_controller.python)
        if not python:
            self.show_error("No compatible Python selected. Choose a listed Python 3.12 (64-bit), "
                            "or Get Python and then Find Python again.")
            self.render()
            return
        # A new attempt supersedes the previous failure; its outcome replaces it.
        self._failure = None
        self.error.hide()
        self._choice_note = ""
        self._operation = "setup"
        self._controls(False)
        v.runtimeStatusLabel.setText("Preparing the separate analysis engine…")
        v.runtimeProgressBar.setRange(0, 100)
        v.runtimeProgressBar.setValue(0)
        v.runtimeProgressBar.show()
        v.cancelSetupButton.show()
        v.begin_task("Preparing the separate analysis engine")
        v.runtime_controller.setup(python)
        v._refresh_readiness()

    def progress(self, value, message):
        v = self.view
        # pip's milestone is not a byte/download percentage.
        v.runtimeProgressBar.setRange(0, 0 if 25 <= value < 85 else 100)
        if not 25 <= value < 85:
            v.runtimeProgressBar.setValue(value)
        shown = bounded_status(message, limit=350, lines=2)
        v.runtimeStatusLabel.setText(shown)
        v.set_task_status(message)
        v.logger.info(message)
