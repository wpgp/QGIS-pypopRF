import os
import shutil
import time
import traceback
from pathlib import Path

import pandas as pd
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject

from ..core.pypoprf import Settings, FeatureExtractor, Model, DasymetricMapper
from ..core.pypoprf.utils.joblib_manager import joblib_resources
from ..core.pypoprf.utils.raster import remask_layer


class ProcessWorker(QThread):
    """Worker thread for running population analysis"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    ui_state = pyqtSignal(bool)
    layer_created = pyqtSignal(str, str)
    final_layers_ready = pyqtSignal(str, str)

    def __init__(self, config_path, logger, use_existing_model=False):
        super().__init__()
        self.config_path = config_path
        self.logger = logger
        self._is_running = True
        self.start_time = time.time()
        self.use_existing_model = use_existing_model

    def stop(self):
        """Stop the analysis process"""
        self._is_running = False

    def run(self):
        """Run the analysis process"""

        try:
            if not self._is_running:
                return

            self.ui_state.emit(False)

            self.progress.emit(0, "Loading settings...")
            settings = Settings.from_file(self.config_path)
            temp_dir = Path(settings.work_dir) / 'output' / 'temp'
            temp_dir.mkdir(exist_ok=True)

            model_path = Path(settings.work_dir) / 'output' / 'model.pkl.gz'
            scaler_path = Path(settings.work_dir) / 'output' / 'scaler.pkl.gz'

            # Re-mask mastergrid if requested
            if settings.mask:
                self.progress.emit(10, "Remasking mastergrid...")
                outfile = settings.mask.replace('.tif', '_remasked.tif')
                remask_layer(settings.mastergrid,
                             settings.mask,
                             1,
                             outfile=outfile,
                             block_size=settings.block_size)
                settings.mask = outfile

            # Constraining mastergrid if requested
            if settings.constrain:
                self.progress.emit(15, "Constraining mastergrid...")
                outfile = settings.constrain.replace('.tif', '_constrained.tif')
                remask_layer(settings.mastergrid,
                             settings.constrain,
                             0,
                             outfile=outfile,
                             block_size=settings.block_size)
                settings.constrain = outfile
            else:
                settings.constrain = settings.mastergrid

            # Feature extraction
            if not self._is_running:
                return

            with joblib_resources(qgis_mode=True, base_dir=str(temp_dir)):
                self.progress.emit(20, "Extracting features...")
                feature_extractor = FeatureExtractor(settings)
                features = feature_extractor.extract()

                # Model training
                if not self._is_running:
                    return

                model = Model(settings)

                if self.use_existing_model:
                    self.progress.emit(40, "Loading existing model...")
                    model.load_model(str(model_path), str(scaler_path))
                else:
                    self.progress.emit(40, "Training new model...")
                    model.train(features)

                self._print_feature_importance(settings)

                # Making predictions
                if not self._is_running:
                    return
                self.progress.emit(60, "Making predictions...")
                predictions = model.predict()

                # predictions = Path(settings.work_dir) / 'output' / 'prediction.tif'

                # Dasymetric mapping
                if not self._is_running:
                    return
                self.progress.emit(80, "Performing dasymetric mapping...")
                mapper = DasymetricMapper(settings)
                mapper.map(predictions)

                # Verification and cleanup
                if not self._is_running:
                    return
                self.progress.emit(95, "Verifying outputs...")
                self.verify_outputs(settings)

                duration = time.time() - self.start_time
                self.logger.info(f'All Process compute in {self.format_time(duration)}')

                self.progress.emit(100, "Completed successfully!")
                self.finished.emit(True, "Prediction and dasymetric "
                                         "mapping completed successfully!")

            self._cleanup_temp_dir(settings)

        except Exception as e:
            self.logger.error(f"Analysis failed: {str(e)}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            self.finished.emit(False, str(e))

    @staticmethod
    def format_time(seconds: float) -> str:
        """Convert seconds to minutes and seconds format."""
        minutes = int(seconds // 60)
        seconds = seconds % 60
        if minutes > 0:
            return f"{minutes}m {seconds:.0f}s"
        return f"{seconds:.0f}s"

    @staticmethod
    def verify_outputs(settings):
        """Verify that all required output files exist"""
        output_dir = Path(settings.work_dir) / 'output'
        required_files = [
            output_dir / 'prediction.tif',
            output_dir / 'normalized_census.tif',
            output_dir / 'dasymetric.tif',
            output_dir / 'features.csv'
        ]

        missing_files = [f for f in required_files if not f.exists()]
        if missing_files:
            raise FileNotFoundError(f"Missing output files: {missing_files}")

    def _cleanup_temp_dir(self, settings):
        """Clean up temporary directory"""
        temp_dir = Path(settings.work_dir) / 'output' / 'temp'
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                self.logger.debug(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to cleanup temp directory: {str(e)}")

    def _print_feature_importance(self, settings):
        """
        Print simple and clear feature importance information with aligned columns.

        Args:
            settings: Settings instance for paths
        """
        feature_importance_path = Path(settings.work_dir) / 'output' / 'feature_importance.csv'

        if not feature_importance_path.exists():
            self.logger.warning("Feature importance file not found")
            return

        importance_df = pd.read_csv(feature_importance_path)
        max_importance = importance_df['importance'].max()
        importance_df['importance_normalized'] = importance_df['importance'] / max_importance
        sorted_importance = importance_df.sort_values('importance', ascending=False)

        name_width = 25
        self.logger.info("=" * 60)
        self.logger.info("Most influential features for population prediction:")
        self.logger.info(f"Total features analyzed: {len(sorted_importance)}")

        def get_importance_color(importance_pct):
            """Return color based on importance percentage."""
            if importance_pct >= 70:
                return "#960303"
            elif importance_pct >= 30:
                return "#1307ed"
            elif importance_pct >= 10:
                return "#666666"
            else:
                return "#999999"

        for _, row in sorted_importance.iterrows():
            feature = row['feature'].replace('_avg', '')
            importance_rel = row['importance_normalized'] * 100
            std = row['std'] * 100

            if len(feature) > name_width - 3:
                feature = feature[:name_width - 3] + "..."

            formatted_name = f"{feature:<{name_width}}"
            formatted_values = f"{importance_rel:5.1f}% (±{std:4.1f}%)"

            color = get_importance_color(importance_rel)

            self.logger.info(
                f"<span style='color: #463ede'>{formatted_name}</span>"
                f"<span style='color: {color}'>{formatted_values}</span>"
            )

        self.logger.info("=" * 60)


class ProcessExecutor:
    """Manager for running population analysis process"""
    progress = pyqtSignal(int, str)

    def __init__(self, dialog, logger, iface=None):
        """
        Initialize ProcessExecutor.

        Args:
            dialog: Main dialog instance
            logger: Logger instance
        """
        self.dialog = dialog
        self.logger = logger
        self.iface = iface
        self.worker = None
        self.output_layers = []

    def start_analysis(self):
        """Start the analysis process"""
        # Validate inputs
        if not self._validate_all():
            return

        # Check output files
        output_dir = Path(self.dialog.workingDirEdit.filePath()) / 'output'
        if not self._check_and_clear_outputs(output_dir):
            return

        # Check existing model and get user choice
        proceed, use_existing_model = self._check_existing_model(output_dir)
        if not proceed:
            return

        # Clear console and reset progress
        self.dialog.console_handler.clear()
        self.dialog.mainProgressBar.setValue(0)

        # Disable UI during processing
        self._set_ui_enabled(False)

        try:
            # Create and start worker thread
            self.worker = ProcessWorker(
                self.dialog.config_manager.config_path,
                self.logger,
                use_existing_model=use_existing_model
            )

            # Connect signals
            self.worker.progress.connect(self.update_progress)
            self.worker.finished.connect(self.analysis_finished)

            self.worker.start()

        except Exception as e:
            self.logger.error(f"Failed to start analysis: {str(e)}")
            self._set_ui_enabled(True)

    def stop_analysis(self):
        """Stop the current analysis process"""
        if self.worker and self.worker.isRunning():
            self.logger.critical("Stopping analysis process...")
            self.worker.stop()
            self.worker.wait()
            self.logger.info("Analysis process stopped by user")

            # Reset progress bar
            self.dialog.mainProgressBar.setValue(0)
            self.dialog.mainProgressBar.setFormat("Stopped by user")

            self._set_ui_enabled(True)

    def _check_existing_model(self, output_dir):
        """
        Check for existing model and get user choice.

        Returns:
            Tuple[bool, bool]: (proceed_with_analysis, use_existing_model)
        """
        model_path = Path(output_dir) / 'model.pkl.gz'
        scaler_path = Path(output_dir) / 'scaler.pkl.gz'

        if not (model_path.exists() and scaler_path.exists()):
            return True, False

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("Previous model found")
        msg.setInformativeText(
            "A previously trained model was found in the output directory.\n\n"
            "IMPORTANT: If you have changed any input data (covariates, mastergrid, census),\n"
            "you should train a new model to ensure correct results.\n\n"
            "Would you like to:\n"
            "• Use the existing model (faster but may give incorrect results if inputs changed)\n"
            "• Train a new model (slower but ensures results match current inputs)\n"
            "• Cancel the operation"
        )
        msg.setWindowTitle("Model Selection")

        use_existing = msg.addButton("Use Existing", QMessageBox.AcceptRole)
        train_new = msg.addButton("Train New", QMessageBox.ActionRole)
        cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.setDefaultButton(train_new)

        msg.exec()
        clicked = msg.clickedButton()

        if clicked == cancel:
            self.logger.info("Analysis cancelled by user")
            return False, False

        return True, (clicked == use_existing)

    def update_progress(self, value, message):
        """Update progress bar and log message"""
        self.dialog.mainProgressBar.setValue(value)
        self.dialog.mainProgressBar.setFormat(f"{message} ({value}%)")
        if message:
            self.logger.info(message)

    def analysis_finished(self, success, message):
        """Handle analysis completion"""
        self._set_ui_enabled(True)

        if success:
            if self.dialog.addToQgisCheckBox.isChecked():
                self.add_output_layers()
            self.logger.info(f"Analysis completed successfully: {message}")
        else:
            self.logger.error(f"Analysis failed: {message}")

    def _validate_inputs(self):
        """Validate all required inputs"""
        return self.dialog.file_handler.validate_inputs(
            self.dialog.mastergridFileWidget.filePath(),
            self.dialog.censusFileWidget.filePath(),
            self.dialog.covariatesTable.rowCount()
        )

    def _set_ui_enabled(self, enabled):
        """Enable/disable UI elements during processing"""
        self.dialog.mainStartButton.setEnabled(True)
        self.dialog.set_input_widgets_enabled(enabled)
        self.dialog.workingDirEdit.setEnabled(enabled)
        self.dialog.initProjectButton.setEnabled(enabled)
        self.dialog.set_settings_widgets_enabled(enabled)

        if enabled:
            self.dialog.mainStartButton.setText("Start")
            self.dialog.mainStartButton.setStyleSheet(
                "QPushButton { background-color: #4CAF50; "
                "color: black; "
                "font-weight: bold; "
                "font-size: 10pt; }")
        else:
            self.dialog.mainStartButton.setText("Stop")
            self.dialog.mainStartButton.setStyleSheet(
                "QPushButton { background-color: #f44336; "
                "color: black; "
                "font-weight: bold; "
                "font-size: 10pt; }")

    def add_output_layers(self):
        """Add all output layers to QGIS"""
        try:
            output_dir = Path(self.dialog.workingDirEdit.filePath()) / 'output'
            filenames = ['prediction.tif', 'normalized_census.tif', 'dasymetric.tif']

            for filename in filenames:
                file_path = output_dir / filename
                if file_path.exists():
                    layer = self.iface.addRasterLayer(str(file_path), '')
                    if layer and layer.isValid():
                        self.output_layers.append(layer)
                        self.logger.info(f"Added layer from {filename}")

        except Exception as e:
            self.logger.error(f"Failed to add output layers: {str(e)}")

    def _validate_all(self):
        """Validate all settings and inputs before starting"""
        try:
            errors = []

            # Validate inputs
            if not self._validate_inputs():
                errors.append("Input validation failed.")

            # Validate population column name
            if not self.dialog.popColumnEdit.text().strip():
                errors.append("Population column name cannot be empty.")

            # Validate ID column name
            if not self.dialog.idColumnEdit.text().strip():
                errors.append("ID column name cannot be empty.")

            # Validate block processing settings
            if self.dialog.enableBlockProcessingCheckBox.isChecked():
                try:
                    w, h = map(int, self.dialog.blockSizeComboBox.currentText().split(','))
                    if w <= 0 or h <= 0:
                        errors.append("Block size dimensions must be positive.")
                except ValueError:
                    errors.append("Invalid block size format (should be width,height).")

            # Log all errors and return final status
            if errors:
                for error in errors:
                    self.logger.error(error)
                return False

            return True

        except Exception as e:
            self.logger.error(f"Validation failed: {str(e)}")
            return False

    def _check_and_clear_outputs(self, output_dir):
        """
        Check for existing output files and ask user confirmation for deletion.

        Args:
            output_dir: Path to output directory

        Returns:
            bool: True if files were deleted or don't exist, False if deletion cancelled or failed
        """
        output_files = [
            'prediction.tif',
            'normalized_census.tif',
            'dasymetric.tif',
            'features.csv'
        ]

        output_path = Path(output_dir)
        if not output_path.exists():
            return True

        # Check which files exist
        existing_files = []
        for filename in output_files:
            file_path = output_path / filename
            if file_path.exists():
                existing_files.append(file_path)

        if not existing_files:
            return True

        # Ask user confirmation
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("Previous analysis outputs found in working directory")
        existing_names = [f"• {file_path.name}" for file_path in existing_files]
        work_dir = str(output_path.parent)

        msg.setInformativeText(
            f"Found {len(existing_files)} output files in:\n"
            f"{work_dir}\n\n"
            "Files to be deleted:\n"
            f"{chr(10).join(existing_names)}\n\n"
            "Do you want to delete these files and start new analysis?"
        )
        msg.setWindowTitle("Confirm Delete Outputs")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)

        if msg.exec() == QMessageBox.No:
            self.logger.info("Analysis cancelled by user - keeping existing outputs")
            return False

        if self.iface:
            project = QgsProject.instance()
            layers_to_remove = []

            for layer in project.mapLayers().values():
                layer_path = Path(layer.source()).resolve()
                if any(file_path.resolve() == layer_path for file_path in existing_files):
                    layers_to_remove.append(layer.id())

            if layers_to_remove:
                project.removeMapLayers(layers_to_remove)
                self.logger.info(f"Removed {len(layers_to_remove)} layers from QGIS")

        # Delete files
        failed_deletes = []
        for file_path in existing_files:
            try:
                os.remove(file_path)
                self.logger.debug(f"Deleted: {file_path.name}")
            except Exception as e:
                failed_deletes.append(file_path.name)
                self.logger.error(f"Failed to delete {file_path.name}: {str(e)}")

        if failed_deletes:
            error_msg = QMessageBox()
            error_msg.setIcon(QMessageBox.Critical)
            error_msg.setText("Cannot delete some output files")
            error_msg.setInformativeText(
                f"The following files in:\n{work_dir}\ncannot be deleted:\n"
                f"{chr(10).join('• ' + name for name in failed_deletes)}\n\n"
                "This usually happens when files are:\n"
                "• Open in QGIS or other GIS software\n"
                "• Being used by another program\n"
                "• Opened in a text editor\n\n"
                "Please close any programs that might be using these files and try again."
            )
            error_msg.setWindowTitle("Delete Error")
            error_msg.exec()
            return False

        return True
