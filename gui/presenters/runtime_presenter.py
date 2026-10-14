"""Discoverable engine setup without package installation in the QGIS host."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QUrl, QSignalBlocker
from qgis.PyQt.QtGui import QDesktopServices

from ..widgets.workflow_status import bounded_status, short_path, plain_tooltip


class RuntimePresenter:
    def __init__(self, view):
        self.view = view
        self._filling = False
        self.error = QtWidgets.QLabel(view.runtimeGroup)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error.hide()
        view.runtimeErrorLabel = self.error
        view.pythonComboBox = QtWidgets.QComboBox(view.runtimeGroup)
        view.pythonComboBox.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        view.pythonComboBox.setMinimumContentsLength(18)
        view.pythonComboBox.setToolTip("Only verified CPython 3.12, 64-bit installations are listed.")
        view.runtimeLayout.insertWidget(1, view.pythonComboBox)
        view.runtimeLayout.insertWidget(2, self.error)
        view.manualPythonCheckBox = QtWidgets.QCheckBox("Choose Python manually (advanced)", view.runtimeGroup)
        view.runtimeLayout.insertWidget(3, view.manualPythonCheckBox)
        view.pythonPathEdit.hide()
        view.browsePythonButton.hide()
        view.manualPythonCheckBox.toggled.connect(view.pythonPathEdit.setVisible)
        view.manualPythonCheckBox.toggled.connect(view.browsePythonButton.setVisible)
        actions = QtWidgets.QHBoxLayout()
        view.refreshPythonButton = QtWidgets.QPushButton("Find Python again", view.runtimeGroup)
        view.downloadPythonButton = QtWidgets.QPushButton("Get Python 3.12…", view.runtimeGroup)
        actions.addWidget(view.refreshPythonButton)
        actions.addWidget(view.downloadPythonButton)
        actions.addStretch()
        view.runtimeLayout.insertLayout(5, actions)
        view.runtimeHelpLabel.setText(
            "ZIP installation installs the interface only. Set up engine downloads verified packages "
            "into a separate environment; nothing is installed into QGIS Python. "
            "Project files can be opened without an engine.")
        view.pythonComboBox.currentIndexChanged.connect(self.selected)
        view.pythonPathEdit.editingFinished.connect(self.manual_finished)
        self._closed = False
        view.refreshPythonButton.clicked.connect(self.discover)
        view.downloadPythonButton.clicked.connect(self.download)
        if hasattr(view.runtime_controller, "interpreterChecked"):
            view.runtime_controller.interpreterChecked.connect(self.inspected)

    def _controls(self, enabled):
        v = self.view
        for widget in (v.setupRuntimeButton, v.pythonComboBox, v.pythonPathEdit, v.browsePythonButton,
                       v.refreshPythonButton, v.manualPythonCheckBox):
            widget.setEnabled(enabled)

    def discover(self):
        if self.view.is_busy:
            return
        self._controls(False)
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
            self.view.pythonPathEdit.setText(candidate["path"])
            self.error.hide()
            self.view.runtimeStatusLabel.setText("Compatible Python selected; choose Set up engine.")

    def changed(self, result):
        v = self.view
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
                source = {"registry-user": "Installed for you", "registry-machine": "System installation",
                          "standard-install": "Installed Python", "py-launcher": "Python launcher",
                          "host-base": "QGIS Python", "host-prefix": "QGIS Python"}.get(item["source"], item["source"])
                label = f"Python {item['version']} · {item['bits']}-bit · {source}"
                if item.get("recommended"):
                    label += " · Recommended"
                label += " · " + short_path(item["path"], 48)
                v.pythonComboBox.addItem(label, item)
                v.pythonComboBox.setItemData(i, plain_tooltip(item["path"]), Qt.ItemDataRole.ToolTipRole)
                if item["path"] == previous:
                    wanted = i
            v.pythonComboBox.setCurrentIndex(wanted)
            del blocker
            self._filling = False
            if not previous or not v.manualPythonCheckBox.isChecked():
                v.pythonPathEdit.setText(choices[wanted]["path"])
        v.setupRuntimeButton.setText("Update / repair engine" if ready else "Set up engine")
        self._controls(True)
        v.runtimeProgressBar.hide()
        v.runtimeProgressBar.setRange(0, 100)
        v.cancelSetupButton.hide()
        error = result.get("error")
        if result.get("cancelled"):
            self.error.hide()
            message = "Engine check cancelled; the previous verified engine remains available." if ready else (
                "Engine operation cancelled. Set up a compatible engine before calculating.")
            v.runtimeStatusLabel.setText(message)
            v.set_task_status(message)
            v.logger.info(message)
        elif error:
            message = ("Engine setup failed; the previous engine remains available: " if ready
                       else "Engine setup failed: ") + str(error)
            self.show_error(message)
        else:
            self.error.hide()
            message = "Analysis engine ready" if ready else (
                "Choose a compatible Python below, then Set up engine." if choices else
                "No compatible Python found. Install Python 3.12 (64-bit), then Find Python again.")
            if result.get("reason") and not ready:
                message += " " + str(result["reason"])
            v.runtimeStatusLabel.setText(message)
            if not ready:
                v.set_task_status(message)
        v._refresh_readiness()

    def show_error(self, message):
        v = self.view
        self.error.setText(bounded_status(message))
        self.error.show()
        v.runtimeStatusLabel.setText(bounded_status(message))
        v.set_task_status(message)
        v.logger.error(message)

    def inspect(self, path):
        v = self.view
        if hasattr(v.runtime_controller, "inspect") and not v.is_busy:
            self._controls(False)
            self.error.hide()
            v.runtimeStatusLabel.setText("Checking the selected Python…")
            v.cancelSetupButton.show()
            if not v.runtime_controller.inspect(path):
                self._controls(True)
                v.cancelSetupButton.hide()
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
        self._controls(True)
        self.view.cancelSetupButton.hide()
        if self.view._dispose_pending:
            return
        if result.get("error"):
            self.show_error("Selected Python cannot be used: " + str(result["error"]) +
                            ". Choose a listed compatible interpreter or install Python 3.12 (64-bit).")
        else:
            self.error.hide()
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
            return
        self.error.hide()
        self._controls(False)
        v.runtimeProgressBar.setRange(0, 100)
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
