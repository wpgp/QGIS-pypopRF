import shutil
import traceback
from pathlib import Path

from ..core.pypoprf import Settings, FeatureExtractor, Model, DasymetricMapper
from ..core.pypoprf.utils.joblib_manager import joblib_resources
from pypoprf.utils.raster import remask_layer
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import QgsProject


class ProcessWorker(QThread):
    """Worker thread for running population analysis"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    ui_state = pyqtSignal(bool)
    layer_created = pyqtSignal(str, str)
    final_layers_ready = pyqtSignal(str, str)

    def __init__(self, config_path, logger):
        super().__init__()
        self.config_path = config_path
        self.logger = logger
        self._is_running = True

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
                self.progress.emit(40, "Training model...")
                model = Model(settings)
                model.train(features)

                # Making predictions
                if not self._is_running:
                    return
                self.progress.emit(60, "Making predictions...")
                predictions = model.predict()

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
                self._verify_outputs(settings)

                self.progress.emit(100, "Analysis completed successfully!")
                self.finished.emit(True, "Prediction and dasymetric "
                                         "mapping completed successfully!")

            self._cleanup_temp_dir(settings)

        except Exception as e:
            self.logger.error(f"Analysis failed: {str(e)}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            self.finished.emit(False, str(e))

    def _verify_outputs(self, settings):
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

        # Clear any existing output layers before starting
        self.remove_output_layers()

        # Clear console and reset progress
        self.dialog.console_handler.clear()
        self.dialog.mainProgressBar.setValue(0)

        # Disable UI during processing
        self._set_ui_enabled(False)

        try:
            # Create and start worker thread
            self.worker = ProcessWorker(
                self.dialog.config_manager.config_path,
                self.logger
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

    def remove_output_layers(self):
        """Remove any previously added output layers from QGIS"""
        if not self.iface:
            return

        # Get list of all layers
        layers = self.iface.mapCanvas().layers()
        project = QgsProject.instance()
        canvas = self.iface.mapCanvas()

        # Names of output layers we want to remove
        output_names = ['Prediction', 'Normalized Census', 'Population Distribution']

        removed_count = 0
        for layer in layers:
            layer_name = layer.name()
            if layer_name in output_names:
                try:
                    project.removeMapLayer(layer.id())
                    canvas.refresh()
                    self.logger.info(f"Removed layer: {layer_name}")
                    removed_count += 1
                except Exception as e:
                    self.logger.warning(f"Error removing layer {layer_name}: {str(e)}")

        self.logger.info(f"Total layers removed: {removed_count}")
        # Clear our tracking list
        self.output_layers.clear()

    def add_output_layers(self):
        """Add all output layers to QGIS"""
        try:
            output_dir = Path(self.dialog.workingDirEdit.filePath()) / 'output'
            layers = [
                ('prediction.tif', 'Prediction'),
                ('normalized_census.tif', 'Normalized Census'),
                ('dasymetric.tif', 'Population Distribution')
            ]

            for filename, layer_name in layers:
                file_path = output_dir / filename
                if file_path.exists():
                    layer = self.iface.addRasterLayer(str(file_path), layer_name)
                    if layer and layer.isValid():
                        self.output_layers.append(layer)
                        self.logger.info(f"Added {layer_name} layer to QGIS")
                    else:
                        self.logger.warning(f"Failed to add {layer_name} layer")
                else:
                    self.logger.warning(f"File not found: {filename}")

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

            # Validate parallel processing settings
            if self.dialog.enableParallelCheckBox.isChecked():
                try:
                    cores = int(self.dialog.cpuCoresComboBox.currentText())
                    if cores <= 0:
                        errors.append("Number of CPU cores must be positive.")
                except ValueError:
                    errors.append("Invalid number of CPU cores.")

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
