"""Explicit preparation and current-project layer import actions."""
from pathlib import Path
from qgis.PyQt import QtWidgets
from ...services.config_manager import ConfigManager
from ..dialogs.preparation_dialog import PreparationWizard
from ..layer_integration import choose_project_layer

class PreparationPresenter:
    """Open explicit, modal preparation; never mutate source scientific data."""
    def __init__(self, view):
        self.view = view

    def setup(self):
        view = self.view
        actions = QtWidgets.QHBoxLayout()
        view.prepareInputsButton = QtWidgets.QPushButton("Prepare / align inputs…")
        view.useLayerButton = QtWidgets.QPushButton("Use a QGIS layer…")
        view.prepareInputsButton.setToolTip("Check source data and create a separate, aligned project without changing the originals")
        actions.addWidget(view.prepareInputsButton)
        actions.addWidget(view.useLayerButton)
        actions.addStretch()
        view.inputLayout.insertLayout(0, actions)
        view.prepareInputsButton.clicked.connect(self._open_preparation)
        view.useLayerButton.clicked.connect(self._use_project_layer)

    def _open_preparation(self):
        view = self.view
        if view.is_busy or not view.runtime_controller.python:
            return
        try:
            if view._preparation_window is None:
                wizard = PreparationWizard(view)
                view._preparation_window = wizard
                wizard.prepared.connect(self._open_prepared_project)
                wizard.finished.connect(lambda: view._close_feature_window("_preparation_window"))
            view._preparation_window.show()
            view._preparation_window.raise_()
        except Exception as exc:
            view.logger.error(f"Could not open the preparation wizard: {exc}")

    def _open_prepared_project(self, root):
        view = self.view
        if view.is_busy:
            return
        try:
            # Validate without switching active paths before the explicit open.
            manager = ConfigManager(view.logger)
            manager.open_project(root)
            view.workingDirEdit.setFilePath(str(root))
            view.init_project()
        except Exception as exc:
            view.logger.error(f"Could not open the prepared project: {exc}")

    def _use_project_layer(self):
        view = self.view
        if view.is_busy or not view._project_ready:
            return
        roles = {"Zone ID grid": "mastergrid", "Predictor": "covariate",
                 "Excluded-area mask": "mask", "Allowed-area constraint": "constrain"}
        label, accepted = QtWidgets.QInputDialog.getItem(view, "Import a QGIS layer", "Use as", list(roles), 0, False)
        if not accepted:
            return
        try:
            record = choose_project_layer(view, "raster")
            if record:
                if Path(record["path"]).suffix.lower() not in {".tif", ".tiff"}:
                    raise ValueError("Export this input as a GeoTIFF first, or use the preparation wizard")
                view._begin_import([record["path"]], roles[label])
        except (ValueError, OSError) as exc:
            view.logger.warning(str(exc))
