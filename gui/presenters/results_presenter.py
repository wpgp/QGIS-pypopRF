"""Run history, saved output actions and diagnostic presentation."""
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from ...services.result_manifest import read_manifest, population_paths
from ..dialogs.population_summary_dialog import PopulationSummaryDialog
from ..widgets.quality_panel import QualityPanel
from ..desktop import open_folder

class ResultsPresenter:
    """Present saved runs without owning or launching analysis workers."""
    def __init__(self, view):
        self.view = view

    def setup(self):
        view = self.view
        view.summarizePopulationButton = QtWidgets.QPushButton("Population in an area…")
        view.resultActions.addWidget(view.summarizePopulationButton)
        view.summarizePopulationButton.setEnabled(False)
        view.summarizePopulationButton.clicked.connect(self._open_population_summary)
        view.quality_panel = QualityPanel(view)
        view.quality_panel.showZonesRequested.connect(self._show_quality_zones)
        quality_scroll = QtWidgets.QScrollArea()
        quality_scroll.setWidgetResizable(True)
        quality_scroll.setWidget(view.quality_panel)
        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        view.resultsLayout.removeWidget(view.resultsTree)
        view.resultsTree.setMinimumHeight(110)
        splitter.addWidget(view.resultsTree)
        splitter.addWidget(quality_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        view.resultsLayout.insertWidget(1, splitter, 1)
        view.quality_panel.load_run(None)

    def refresh_results(self):
        view = self.view
        view.resultsTree.clear()
        self._result_selected()
        if not view.config_manager.config_path:
            return
        try:
            config = view.config_manager.get_config()
            root = (Path(view.config_manager.working_dir) / config.get("output_dir", "output") / "runs").resolve()
        except Exception as exc:
            view.resultSummaryLabel.setText("Project settings could not be read. See Details.")
            view.logger.error(str(exc))
            return
        if not root.is_dir():
            view.resultSummaryLabel.setText("No analyses yet. Add input data and run your first analysis.")
            return
        complete = 0
        try:
            directories = sorted(root.iterdir(), reverse=True)[:200]
        except OSError as exc:
            view.logger.error(f"Could not read result history: {exc}")
            return
        for directory in directories:
            if not directory.is_dir() or directory.is_symlink():
                continue
            path = directory / "manifest.json"
            try:
                manifest = read_manifest(path)
                status = manifest["status"]
                outputs = population_paths(directory, manifest)
                item = QtWidgets.QTreeWidgetItem([directory.name, status.capitalize(), str(len(outputs))])
                item.setData(0, Qt.ItemDataRole.UserRole, str(directory))
                view.resultsTree.addTopLevelItem(item)
                complete += status == "complete"
            except (OSError, ValueError, TypeError):
                continue
        view.resultSummaryLabel.setText(f"{complete} completed analyses. Select a run to view its results.")
        self._result_selected()

    def _selected_run(self):
        view = self.view
        selected = view.resultsTree.selectedItems()
        return Path(selected[0].data(0, Qt.ItemDataRole.UserRole)) if selected else None

    def _result_selected(self):
        view = self.view
        selected = view.resultsTree.selectedItems()
        view.openRunButton.setEnabled(bool(selected))
        complete = False
        if selected:
            root = self._selected_run()
            try:
                manifest = read_manifest(root / "manifest.json")
                complete = bool(population_paths(root, manifest))
            except (OSError, ValueError, TypeError):
                pass
        view.addRunLayersButton.setEnabled(complete and view.iface is not None)
        view.summarizePopulationButton.setEnabled(complete and bool(view.runtime_controller.python) and not view.is_busy)
        try:
            view.quality_panel.load_run(self._selected_run())
        except Exception as exc:
            view.logger.warning(f"Could not display quality diagnostics: {exc}")

    def _open_selected_run(self):
        view = self.view
        path = self._selected_run()
        if path:
            try:
                open_folder(str(path))
            except Exception as exc:
                view.logger.error(str(exc))

    def _add_selected_run(self):
        view = self.view
        root = self._selected_run()
        if root is None or view.iface is None:
            return
        try:
            manifest = read_manifest(root / "manifest.json")
            view.layer_integration.iface = view.iface
            view.layer_integration.add_run(root, population_paths(root, manifest))
        except (OSError, ValueError, TypeError) as exc:
            view.logger.error(f"Could not load this run: {exc}")

    def _show_quality_zones(self, payload):
        view = self.view
        try:
            view.layer_integration.show_zone_centroids(payload)
        except Exception as exc:
            view.logger.warning(f"Could not map diagnostic centroids: {exc}")

    def _open_population_summary(self):
        view = self.view
        if view.is_busy or not view.runtime_controller.python:
            return
        try:
            root = self._selected_run()
            if not root:
                return
            manifest = read_manifest(root / "manifest.json")
            maps = population_paths(root, manifest)
            if not maps:
                return
            if view._summary_window is None:
                inventory = manifest.get("artifacts", [])
                hashes = {}
                if isinstance(inventory, list):
                    for artifact in inventory:
                        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                            candidate = root / artifact["path"]
                            if candidate in maps:
                                hashes[str(candidate)] = artifact.get("sha256")
                window = PopulationSummaryDialog(view, maps, hashes)
                view._summary_window = window
                window.finished.connect(lambda: view._close_feature_window("_summary_window"))
            view._summary_window.show()
            view._summary_window.raise_()
        except Exception as exc:
            view.logger.warning(f"Could not open the population summary: {exc}")
