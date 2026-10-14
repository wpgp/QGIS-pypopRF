"""Project activation and transactional input-import presentation."""
from pathlib import Path
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSignalBlocker
from qgis.gui import QgsFileWidget
from ..desktop import open_folder
from ..widgets.workflow_status import plain_tooltip, short_path
from ...services.project_location import ensure_project_location, ensure_project_paths
from ...services.config_manager import ConfigManager, DEFAULT_CONFIG

class ProjectInputsPresenter:
    """Coordinate a coherent project view; controllers retain worker ownership.

    The view owns Qt widgets and exposes the established dialog API. This
    presenter handles only project/input transitions and import registration.
    """
    def __init__(self, view):
        self.view = view
        self._conflict_dialog = None
        self._import_context = None
        self._closed = False
        self._edit_connections = []
        self._input_edit_roles = {}
        self.input_widgets = {
            "mastergrid": view.mastergridFileWidget,
            "mask": view.maskFileWidget,
            "constrain": view.constrainFileWidget,
            "census_data": view.populationCensusFileWidget,
            "agesex_data": view.agesexCensusFileWidget,
        }

    def connect_input_signals(self):
        """Treat typing as a draft, but preserve committed file-widget choices."""
        for kind, widget in self.input_widgets.items():
            widget.fileChanged.connect(
                lambda path, kind=kind: self._handle_file_change(kind, path))
            # QgsFileWidget exposes its QgsFilterLineEdit in both Qt bindings.
            edit = widget.lineEdit()
            self._input_edit_roles[edit] = kind
            edit.installEventFilter(self.view)
            callback = lambda kind=kind: self._commit_input_edit(kind)
            edit.editingFinished.connect(callback)
            self._edit_connections.append((edit.editingFinished, callback))

    def input_edit_kind(self, edit):
        return self._input_edit_roles.get(edit)

    def commit_pending_input_draft(self):
        if self._closed:
            return False
        for kind, widget in self.input_widgets.items():
            if widget.lineEdit().isModified():
                self._commit_input_edit(kind)
                return True
        return False

    def _commit_input_edit(self, kind):
        if self._closed:
            return
        widget = self.input_widgets[kind]
        edit = widget.lineEdit()
        if not edit.isModified():
            return
        edit.setModified(False)
        self._handle_file_change(kind, widget.filePath())

    def discard_input_edits(self):
        """Closing is not permission to start an import from a pending draft."""
        if self._closed:
            return
        for kind, widget in self.input_widgets.items():
            if widget.lineEdit().isModified():
                self._restore_file_widget(kind)
                widget.lineEdit().setModified(False)

    def close(self):
        if self._closed:
            return
        self._closed = True
        for signal, callback in self._edit_connections:
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass
        self._edit_connections.clear()

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

        if self._closed or view._loading_project or not view.config_manager.config_path:
            return
        # Old queued field signals must not write the previously open config.
        if not self.selection_is_active():
            return
        widget = self.input_widgets[file_type]
        if widget.lineEdit().isModified():
            # QLineEdit marks genuine key edits before fileChanged is emitted;
            # setFilePath/browse setText resets this flag and remains immediate.
            return
        if view.is_busy:
            self._restore_file_widget(file_type)
            return
        if path:
            self._begin_import([path], file_type)
        else:
            try:
                view.config_manager.clear_config_value(file_type)
                self._input_error(file_type, "")
            except Exception as exc:
                self._restore_file_widget(file_type)
                view.logger.error(f"Could not clear input selection: {exc}")
                view.set_task_status(f"Could not clear input selection: {exc}")
                self._input_error(file_type, str(exc))
        view._refresh_readiness()

    def on_working_dir_changed(self, path: str):
        """Selecting a different folder is not activation; repeating the active path is a no-op."""
        view = self.view
        if self.selection_is_active():
            view._refresh_readiness()
            return
        view._project_ready = False
        # A candidate directory is not the active project until Create/Open.
        view.mainStartButton.setEnabled(False)
        view.set_input_widgets_enabled(False)
        view.set_settings_widgets_enabled(False)
        view._refresh_readiness()

    def selection_is_active(self):
        view = self.view
        selected = view.workingDirEdit.filePath()
        if not (selected and view._project_ready and view.config_manager.config_path
                and view.config_manager.working_dir):
            return False
        try:
            return Path(selected).resolve() == Path(view.config_manager.working_dir).resolve()
        except (OSError, RuntimeError, ValueError):
            return False

    def refresh_project_action(self):
        """Present selected/open state after every readiness or worker transition."""
        view = self.view
        selected = view.workingDirEdit.filePath()
        active = self.selection_is_active()
        try:
            existing = bool(selected and (Path(selected) / "config.yaml").is_file())
        except (OSError, ValueError):
            existing = False
        view.initProjectButton.setText("Project open" if active else "Open project" if existing
                                       else "Create project" if selected else "Choose project folder")
        view.initProjectButton.setEnabled(bool(selected) and not active and not view.is_busy)
        view.openProjectFolder.setEnabled(active)
        if active:
            project = str(Path(view.config_manager.working_dir))
            view.currentProjectLabel.setText("Active project: " + short_path(project))
            view.currentProjectLabel.setToolTip(plain_tooltip(project))
            view.initProjectButton.setToolTip("This project is already open. Select another folder to switch projects.")
        else:
            view.currentProjectLabel.setText("Selected folder is not open yet. Choose " +
                ("Open project." if existing else "Create project.") if selected else
                "No project is open. Choose a project folder first.")
            view.currentProjectLabel.setToolTip(plain_tooltip(selected) if selected else "")
            view.initProjectButton.setToolTip("Open the selected project's saved inputs and settings (Alt+O)."
                if existing else "Create a project in the selected folder (Alt+O). Existing files are not overwritten.")

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
        if self.selection_is_active():
            # Direct callers and shortcuts must not reload settings or reopen log handlers.
            view._refresh_readiness()
            return
        working_dir = view.workingDirEdit.filePath()
        if not working_dir:
            view.logger.error("Please select working directory first")
            view.set_task_status("Please select working directory first")
            return

        try:
            protected = dict(plugin_root=view.plugin_root, job_cache=view.job_cache,
                runtime_cache=getattr(view.runtime_controller.manager, "cache_root", None))
            working_dir = str(ensure_project_location(
                working_dir, **protected))
            existing = (Path(working_dir) / "config.yaml").is_file()
            # Read/validate independently; never activate or initialize logging
            # for a candidate whose configured data/output lives in protected code.
            candidate_config = ConfigManager(view.logger).open_project(working_dir) if existing else DEFAULT_CONFIG
            ensure_project_paths(working_dir, candidate_config, **protected)
        except Exception as exc:
            view.logger.error(str(exc))
            view.set_task_status(str(exc))
            return
        view.logger.info("— Opening project —")
        view.mainProgressBar.setValue(0)

        try:
            view._project_ready = False
            view.set_input_widgets_enabled(False)
            view.set_settings_widgets_enabled(False)
            view.mainStartButton.setEnabled(False)
            # Create project structure and config
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
                view.refresh_results()
                view._refresh_readiness()
                view.set_task_status("Project opened. Saved inputs and settings restored." if existing else
                                     "Project created. Add the required inputs in Input data.")

                # Show next steps
                view.logger.info("Project initialized successfully!")
                view.logger.info("Select mastergrid, census and covariate files in Input Data.")
                view.logger.info("Review processing settings, then start the analysis.")

        except Exception as e:
            view._project_ready = False
            view.logger.error(f"Error initializing project: {str(e)}")
            view.set_task_status(f"Error initializing project: {e}")
            view.set_input_widgets_enabled(False)
            view.set_settings_widgets_enabled(False)
            view.mainStartButton.setEnabled(False)
        finally:
            view._loading_project = False
            view._refresh_readiness()

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
            view.set_task_status(str(exc))

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
            view.set_task_status(f"Could not read project settings: {exc}")
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
        try:
            config = view.config_manager.get_config()
            ensure_project_paths(view.config_manager.working_dir, config,
                plugin_root=view.plugin_root, job_cache=view.job_cache,
                runtime_cache=getattr(view.runtime_controller.manager, "cache_root", None))
        except Exception as exc:
            # Fail before UI changes or worker creation; never restore a widget
            # by rereading the same unsafe config, or rewrite a user's edit.
            view.logger.error(f"Import blocked: {exc}")
            view.set_task_status(f"Import blocked: {exc}")
            self._input_error(kind, str(exc))
            return
        self._input_error(kind, "")
        self._import_context = (str(view.config_manager.working_dir), config.get("data_dir", "data"), kind)
        view.set_input_widgets_enabled(False)
        view.set_settings_widgets_enabled(False)
        view.workingDirEdit.setEnabled(False)
        view.initProjectButton.setEnabled(False)
        view.setupRuntimeButton.setEnabled(False)
        view.mainStartButton.setEnabled(True)
        view.mainStartButton.setText("Cancel import")
        view.set_task_status("Importing input data…", 0)
        view.import_controller.start(view.config_manager.working_dir,
            config.get("data_dir", "data"), paths, kind, view.logger,
            options={"id_column": config.get("census_id_column", "id")})

    def _import_progress(self, percent, name):
        self.view.set_task_status(f"Importing {name}…", percent)

    def _imports_finished(self, result):
        view = self.view
        kind = result["kind"]
        problem = result["errors"][0] if result["errors"] else None
        self._close_conflict_dialog()
        try:
            if result["filenames"]:
                self._assert_import_context(kind)
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
            problem = problem or f"Could not register imported files: {exc}"
            if kind != "covariate":
                self._restore_file_widget(kind)
        if result.get("conflicts"):
            if any(getattr(view, flag, False) for flag in ("_dispose_pending", "_disposed", "_close_pending")):
                view.import_controller.stop()
                return
            from ..dialogs.import_conflict_dialog import ImportConflictDialog
            conflict = result["conflicts"][0]
            self._conflict_dialog = ImportConflictDialog(conflict, view)
            self._conflict_dialog.choiceMade.connect(
                lambda action, name, conflict=conflict: self._resolve_conflict(conflict, action, name))
            popup = self._conflict_dialog
            popup.finished.connect(lambda *_args, popup=popup: self._forget_conflict_dialog(popup))
            popup.destroyed.connect(lambda *_args, popup=popup: self._forget_conflict_dialog(popup))
            self._conflict_dialog.open()
            view.set_task_status(f"Choose how to import {conflict['filename']}; originals will not be replaced")
            self._input_error(kind, "This filename already exists. Choose reuse, a separate copy, or cancel.")
            return
        self._import_context = None
        view.set_input_widgets_enabled(True)
        view.set_settings_widgets_enabled(True)
        view.workingDirEdit.setEnabled(True)
        view.initProjectButton.setEnabled(True)
        view.setupRuntimeButton.setEnabled(True)
        view.set_task_status("Import cancelled; existing files retained" if result.get("cancelled") else
                             "Import completed" if problem is None else
                             f"Import could not be completed: {problem}")
        self._input_error(kind, problem or "")
        view._refresh_readiness()

    def _input_error(self, kind, message):
        callback = getattr(self.view, "set_input_error", None)
        if callback:
            callback(kind, message)

    def _close_conflict_dialog(self):
        dialog, self._conflict_dialog = self._conflict_dialog, None
        if dialog is not None:
            dialog.choiceMade.disconnect()
            dialog.close()

    def _forget_conflict_dialog(self, dialog):
        if self._conflict_dialog is dialog:
            self._conflict_dialog = None

    def _resolve_conflict(self, conflict, action, name):
        view = self.view
        if view.import_controller.pending_conflict is not conflict:
            return
        if any(getattr(view, flag, False) for flag in ("_dispose_pending", "_disposed", "_close_pending")):
            view.import_controller.stop()
            return
        if action != "cancel":
            try:
                self._assert_import_context(conflict["kind"])
            except Exception as exc:
                view.import_controller.stop()
                view.set_task_status(f"Import blocked: {exc}")
                self._input_error(conflict["kind"], str(exc))
                return
        view.import_controller.resolve_conflict(action, name or None)

    def _assert_import_context(self, kind):
        view = self.view
        config = view.config_manager.get_config()
        context = (str(view.config_manager.working_dir), config.get("data_dir", "data"), kind)
        if context != self._import_context:
            raise ValueError("Project or data directory changed; select the input again. Imported files were retained.")
        ensure_project_paths(view.config_manager.working_dir, config,
            plugin_root=view.plugin_root, job_cache=view.job_cache,
            runtime_cache=getattr(view.runtime_controller.manager, "cache_root", None))
