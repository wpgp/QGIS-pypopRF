"""Project activation and transactional input-import presentation."""
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSignalBlocker
from qgis.gui import QgsFileWidget
from ..desktop import open_folder

class ProjectInputsPresenter:
    """Coordinate a coherent project view; controllers retain worker ownership.

    The view owns Qt widgets and exposes the established dialog API. This
    presenter handles only project/input transitions and import registration.
    """
    def __init__(self, view):
        self.view = view
        self.input_widgets = {
            "mastergrid": view.mastergridFileWidget,
            "mask": view.maskFileWidget,
            "constrain": view.constrainFileWidget,
            "census_data": view.populationCensusFileWidget,
            "agesex_data": view.agesexCensusFileWidget,
        }

    def _setup_file_widgets(self):
        """Configure file widgets with appropriate filters and titles."""
        view = self.view

        try:
            mode = QgsFileWidget.StorageMode.GetDirectory
        except AttributeError:
            mode = QgsFileWidget.GetDirectory
        view.workingDirEdit.setStorageMode(mode)
        # Mastergrid
        view.mastergridFileWidget.setDialogTitle("Select Mastergrid File (Required)")
        view.mastergridFileWidget.setFilter("GeoTIFF files (*.tif *.tiff)")

        # Mask
        view.maskFileWidget.setDialogTitle("Select Mask File (Optional)")
        view.maskFileWidget.setFilter("GeoTIFF files (*.tif *.tiff)")

        # Constrain
        view.constrainFileWidget.setDialogTitle("Select Constrain File (Optional)")
        view.constrainFileWidget.setFilter("GeoTIFF files (*.tif *.tiff)")

        # Population Census
        view.populationCensusFileWidget.setDialogTitle("Select Population Census CSV File")
        view.populationCensusFileWidget.setFilter("CSV files (*.csv)")

        # Age-Sex Census
        view.agesexCensusFileWidget.setDialogTitle("Select Age-Sex Census CSV File (Optional)")
        view.agesexCensusFileWidget.setFilter("CSV files (*.csv)")

    def _handle_file_change(self, file_type: str, path: str):
        """Handle file selection changes for input files.

        Args:
            file_type: Type of file being changed ('mastergrid', 'mask', etc.)
            path: New file path
        """
        view = self.view

        if view._loading_project or not view.config_manager.config_path:
            return
        if view.is_busy:
            self._restore_file_widget(file_type)
            return
        if path:
            self._begin_import([path], file_type)
        else:
            view.config_manager.clear_config_value(file_type)
        view._refresh_readiness()

    def on_working_dir_changed(self, path: str):
        """Handle working directory change"""
        view = self.view
        view.initProjectButton.setEnabled(bool(path))
        view._project_ready = False
        view.initProjectButton.setText("Open Project" if (Path(path) / "config.yaml").is_file()
                                       else "Create Project")
        # A candidate directory is not the active project until Create/Open.
        view.mainStartButton.setEnabled(False)
        view.set_input_widgets_enabled(False)
        view.set_settings_widgets_enabled(False)

    def init_project(self):
        """Initialize new pypopRF project.

        Creates project directory structure, initializes configuration,
        and enables UI elements for further setup.

        Raises:
            Exception: If project initialization fails
        """
        view = self.view

        if view.is_busy:
            return
        view.console_handler.clear()
        view.mainProgressBar.setValue(0)

        working_dir = view.workingDirEdit.filePath()
        if not working_dir:
            view.logger.error("Please select working directory first")
            return

        try:
            view._project_ready = False
            view.set_input_widgets_enabled(False)
            view.set_settings_widgets_enabled(False)
            view.mainStartButton.setEnabled(False)
            # Create project structure and config
            existing = (Path(working_dir) / "config.yaml").is_file()
            if existing:
                view.config_manager.open_project(working_dir)
            else:
                view.config_manager.create_initial_config(working_dir)
            if view.config_manager.config_path:
                view.file_handler.set_working_dir(working_dir,
                    view.config_manager.get_config().get("data_dir", "data"))

                # Enable UI elements
                view.openProjectFolder.setEnabled(True)
                view.addToQgisCheckBox.setChecked(True)

                view._loading_project = True
                view._setup_cpu_cores_combo()
                self._load_project_inputs()

                # Load initial settings
                if not view.settings_handler.load_settings(view):
                    raise ValueError("Project settings could not be loaded")
                view._loading_project = False
                view._update_logging_settings(persist=False)
                view._project_ready = True
                view.set_input_widgets_enabled(True)
                view.set_settings_widgets_enabled(True)
                view.initProjectButton.setText("Open project")
                view.currentProjectLabel.setText(str(Path(view.config_manager.working_dir)))
                view.refresh_results()
                view._refresh_readiness()

                # Show next steps
                view.logger.info("Project initialized successfully!")
                view.logger.info("Select mastergrid, census and covariate files in Input Data.")
                view.logger.info("Review processing settings, then start the analysis.")

        except Exception as e:
            view.logger.error(f"Error initializing project: {str(e)}")
            view.set_input_widgets_enabled(False)
            view.set_settings_widgets_enabled(False)
            view.mainStartButton.setEnabled(False)
        finally:
            view._loading_project = False

    def add_covariate(self):
        """Add new covariate files to the project.

        Opens file dialog for selecting covariate files and adds them
        to the project data directory.
        """
        view = self.view

        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            view, "Select Covariate Files", "", "GeoTIFF files (*.tif *.tiff)"
        )
        paths, names = [], set()
        for path in file_paths:
            if view.covariate_handler.check_duplicate(path):
                view.logger.warning(f"Covariate already present: {path}")
                continue
            if Path(path).stem.casefold() in names:
                view.logger.warning(f"Duplicate covariate name: {path}")
                continue
            names.add(Path(path).stem.casefold())
            paths.append(path)
        if paths:
            self._begin_import(paths, "covariate")
        view._refresh_readiness()

    def open_project_folder(self):
        """Open project folder in system file explorer"""
        view = self.view
        try:
            open_folder(view.config_manager.working_dir)
        except Exception as exc:
            view.logger.error(str(exc))

    def _load_project_inputs(self):
        view = self.view
        config = view.config_manager.get_config()
        data = Path(view.config_manager.working_dir) / config.get("data_dir", "data")
        widgets = self.input_widgets
        for key, widget in widgets.items():
            value = config.get(key)
            widget.setFilePath(str(data / value) if value else "")
        view.covariatesTable.setRowCount(0)
        for name, filename in config.get("covariates", {}).items():
            view.covariate_handler._add_covariate_row(filename, data, name=name, update=False)

    def _restore_file_widget(self, key):
        view = self.view
        try:
            config = view.config_manager.get_config()
        except Exception as exc:
            view.logger.error(f"Could not read project settings: {exc}")
            view._project_ready = False
            config = {}
        data = Path(view.config_manager.working_dir) / config.get("data_dir", "data")
        widgets = self.input_widgets
        widget = widgets[key]
        blocker = QSignalBlocker(widget)
        widget.setFilePath(str(data / config[key]) if config.get(key) else "")
        del blocker

    def _begin_import(self, paths, kind):
        view = self.view
        if view.is_busy or not view._project_ready:
            return
        config = view.config_manager.get_config()
        view.set_input_widgets_enabled(False)
        view.set_settings_widgets_enabled(False)
        view.workingDirEdit.setEnabled(False)
        view.initProjectButton.setEnabled(False)
        view.setupRuntimeButton.setEnabled(False)
        view.mainStartButton.setEnabled(True)
        view.mainStartButton.setText("Cancel import")
        view.mainProgressBar.setValue(0)
        view.import_controller.start(view.config_manager.working_dir,
            config.get("data_dir", "data"), paths, kind, view.logger)

    def _import_progress(self, percent, name):
        view = self.view
        view.mainProgressBar.setValue(percent)
        view.mainProgressBar.setFormat(f"Importing {name}…")

    def _imports_finished(self, result):
        view = self.view
        kind = result["kind"]
        try:
            if kind == "covariate":
                view.covariate_handler.add_covariates(result["filenames"])
            else:
                if result["filenames"]:
                    view.config_manager.update_config(kind, result["filenames"][-1])
                self._restore_file_widget(kind)
            for error in result["errors"]:
                view.logger.error(error)
        except Exception as exc:
            view.logger.error(f"Could not register imported files: {exc}")
            if kind != "covariate":
                self._restore_file_widget(kind)
        view.set_input_widgets_enabled(True)
        view.set_settings_widgets_enabled(True)
        view.workingDirEdit.setEnabled(True)
        view.initProjectButton.setEnabled(True)
        view.setupRuntimeButton.setEnabled(True)
        view.mainProgressBar.setFormat("Import completed" if not result["errors"] else "Import could not be completed; see Details")
        view._refresh_readiness()
