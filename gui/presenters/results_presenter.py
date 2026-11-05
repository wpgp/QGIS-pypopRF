"""Run history, saved output actions and diagnostic presentation."""
from datetime import datetime, timezone
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from ...services.result_manifest import read_manifest, population_paths
from ..dialogs.population_summary_dialog import PopulationSummaryDialog
from ..widgets.quality_panel import QualityPanel
from ..widgets.workflow_status import plain_tooltip
from ..desktop import open_folder


def run_label(name):
    """Local start time for IDs like 20261013T210328Z-d1f333f7; otherwise the raw ID."""
    if len(name) != 25 or name[16] != "-":
        return name
    try:
        started = datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return started.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return name

class ResultsPresenter:
    """Present saved runs without owning or launching analysis workers."""
    def __init__(self, view):
        self.view = view
        self._history_root = None

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

    def refresh_results(self, select=None):
        """Keep the selected run by path; otherwise select ``select`` or the newest complete run."""
        view = self.view
        previous = self._selected_run()
        wanted = [str(Path(select).resolve())] if select else []
        wanted += [str(previous)] if previous else []
        view.resultsTree.clear()
        self._history_root = None
        self._result_selected()
        if not view.config_manager.config_path:
            return
        try:
            config = view.config_manager.get_config()
            root = (Path(view.config_manager.working_dir) / config.get("output_dir", "output") / "runs").resolve()
            self._history_root = root
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
        items, newest_complete = {}, None
        for directory in directories:
            try:
                safe = (directory.is_dir() and not directory.is_symlink()
                    and not (hasattr(directory, "is_junction") and directory.is_junction())
                    and directory.resolve().is_relative_to(root))
            except (OSError, RuntimeError) as exc:
                view.logger.warning(f"Could not inspect saved run folder {directory.name}: {exc}")
                continue
            if not safe:
                continue
            try:
                manifest = self._read_run_manifest(directory)
                status = manifest["status"]
                outputs = population_paths(directory, manifest)
                if status == "complete" and not outputs:
                    raise ValueError("Completed run has no published population maps")
                problem = ""
            except (OSError, ValueError, TypeError) as exc:
                status, outputs = "invalid", []
                problem = str(exc)
            item = QtWidgets.QTreeWidgetItem([run_label(directory.name), status.capitalize(), str(len(outputs))])
            item.setData(0, Qt.ItemDataRole.UserRole, str(directory))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, status)
            item.setToolTip(0, plain_tooltip(f"Run ID: {directory.name}\n{directory}"))
            if problem:
                item.setToolTip(1, plain_tooltip("Saved result is invalid: " + problem))
                view.logger.warning(f"Could not read saved run {directory.name}: {problem}")
            view.resultsTree.addTopLevelItem(item)
            items[str(directory)] = item
            if status == "complete":
                complete += 1
                if newest_complete is None:
                    newest_complete = item
        view.resultSummaryLabel.setText(
            f"{complete} completed analyses. Select a run to view its results." if complete else
            "No completed analyses yet. Failed, stopped or invalid runs are listed for diagnosis." if items else
            "No analyses yet. Add input data and run your first analysis.")
        target = next((items[path] for path in wanted if path in items), newest_complete)
        if target is not None:
            view.resultsTree.setCurrentItem(target)  # selection signal loads the run
        else:
            self._result_selected()

    def _selected_run(self):
        view = self.view
        selected = view.resultsTree.selectedItems()
        return Path(selected[0].data(0, Qt.ItemDataRole.UserRole)) if selected else None

    def _safe_run_directory(self, path):
        if path is None or self._history_root is None:
            return False
        try:
            config = self.view.config_manager.get_config()
            current = (Path(self.view.config_manager.working_dir) / config.get("output_dir", "output") / "runs").resolve()
            return (current == self._history_root and path.is_dir() and not path.is_symlink()
                and not (hasattr(path, "is_junction") and path.is_junction())
                and path.resolve().parent == self._history_root)
        except (OSError, ValueError, RuntimeError):
            return False

    @staticmethod
    def _read_run_manifest(root):
        marker = root / "manifest.json"
        if (root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction())
                or not root.is_dir() or marker.is_symlink()
                or (hasattr(marker, "is_junction") and marker.is_junction())
                or not marker.is_file() or marker.resolve().parent != root.resolve()):
            raise ValueError("Saved result metadata is missing, linked or outside its ordinary run directory")
        return read_manifest(marker)

    def _result_selected(self):
        view = self.view
        selected = view.resultsTree.selectedItems()
        view.openRunButton.setToolTip(plain_tooltip(self._selected_run()) if selected else "")
        complete, invalid = False, False
        safe_folder = bool(selected) and self._safe_run_directory(self._selected_run())
        if selected:
            root = self._selected_run()
            invalid = not safe_folder or selected[0].data(0, Qt.ItemDataRole.UserRole + 1) == "invalid"
            if safe_folder:
                try:
                    manifest = self._read_run_manifest(root)
                    complete = bool(population_paths(root, manifest))
                    invalid = invalid or (manifest["status"] == "complete" and not complete)
                except (OSError, ValueError, TypeError):
                    invalid = True
        view.openRunButton.setEnabled(safe_folder)
        complete = complete and not invalid and safe_folder
        view.addRunLayersButton.setEnabled(complete and view.iface is not None)
        view.summarizePopulationButton.setEnabled(complete and bool(view.runtime_controller.python) and not view.is_busy)
        try:
            view.quality_panel.load_run(None if invalid else self._selected_run())
        except Exception as exc:
            view.logger.warning(f"Could not display quality diagnostics: {exc}")

    def _open_selected_run(self):
        view = self.view
        path = self._selected_run()
        if path and self._safe_run_directory(path):
            try:
                open_folder(str(path))
            except Exception as exc:
                view.logger.error(str(exc))

    def _add_selected_run(self):
        view = self.view
        root = self._selected_run()
        if root is None or view.iface is None:
            return
        if not self._safe_run_directory(root):
            self._result_selected()
            view.set_task_status("The saved run folder changed or is unavailable. Refresh Results before loading maps.")
            return
        try:
            manifest = self._read_run_manifest(root)
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
            if not self._safe_run_directory(root):
                self._result_selected()
                view.set_task_status("The saved run folder changed or is unavailable. Refresh Results before summarizing population.")
                return
            manifest = self._read_run_manifest(root)
            maps = population_paths(root, manifest)
            if not maps:
                return
            if view._summary_window is None:
                inventory = manifest.get("artifacts", [])
                hashes = {}
                if isinstance(inventory, list):
                    for artifact in inventory:
                        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                            try:
                                candidates = population_paths(root, {"status": "complete",
                                    "outputs": [artifact["path"]]})
                            except (OSError, ValueError, TypeError):
                                continue
                            for candidate in candidates:
                                if candidate in maps:
                                    hashes[str(candidate)] = artifact.get("sha256")
                window = PopulationSummaryDialog(view, maps, hashes)
                view._summary_window = window
                window.finished.connect(lambda: view._close_feature_window("_summary_window"))
            view._summary_window.show()
            view._summary_window.raise_()
        except Exception as exc:
            view.logger.warning(f"Could not open the population summary: {exc}")
