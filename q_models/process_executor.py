# -*- coding: utf-8 -*-
from pathlib import Path
from qgis.PyQt.QtCore import QThread, pyqtSignal, QTimer
from pypoprf import Settings, FeatureExtractor, Model, DasymetricMapper
from pypoprf.utils.joblib_manager import joblib_resources

from pypoprf.utils.raster import remask_layer


class ProcessWorker(QThread):
    """Worker thread for running population analysis"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    ui_state = pyqtSignal(bool)

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
                self.finished.emit(True, "Prediction and dasymetric mapping completed successfully!")

            self._cleanup_temp_dir(settings)

        except Exception as e:
            import traceback
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
            import shutil
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

    def start_analysis(self):
        """Start the analysis process"""
        # Validate inputs
        if not self._validate_all():
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
                self.add_layers_to_qgis()
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
        self.dialog._set_input_widgets_enabled(enabled)
        self.dialog.openProjectFolder.setEnabled(enabled)
        self.dialog._set_settings_widgets_enabled(enabled)
        if enabled:
            self.dialog.mainStartButton.setText("Start")
            self.dialog.mainStartButton.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: black; font-weight: bold; font-size: 10pt; }")
        else:
            self.dialog.mainStartButton.setText("Stop")
            self.dialog.mainStartButton.setStyleSheet(
                "QPushButton { background-color: #f44336; color: black; font-weight: bold; font-size: 10pt; }")

    def add_layers_to_qgis(self):
        """Add output layers to QGIS"""
        try:
            if not self.iface:
                self.logger.warning("QGIS interface not available")
                return

            output_dir = Path(self.dialog.workingDirEdit.filePath()) / 'output'
            layers = {
                'Prediction': output_dir / 'prediction.tif',
                'Normalized Census': output_dir / 'normalized_census.tif',
                'Population Distribution': output_dir / 'dasymetric.tif'
            }

            for name, path in layers.items():
                if path.exists():
                    self.iface.addRasterLayer(str(path), name)
                    self.logger.info(f"Added {name} layer to QGIS")

        except Exception as e:
            self.logger.error(f"Failed to add layers to QGIS: {str(e)}")


    def _validate_all(self):
        """Validate all settings and inputs before starting"""
        try:
            if not self._validate_inputs():
                return False

            if not self.dialog.popColumnEdit.text().strip():
                self.logger.error("Population column name cannot be empty")
                return False
            if not self.dialog.idColumnEdit.text().strip():
                self.logger.error("ID column name cannot be empty")
                return False

            if self.dialog.enableParallelCheckBox.isChecked():
                try:
                    cores = int(self.dialog.cpuCoresComboBox.currentText())
                    if cores <= 0:
                        self.logger.error("Number of CPU cores must be positive")
                        return False
                except ValueError:
                    self.logger.error("Invalid number of CPU cores")
                    return False

            if self.dialog.enableBlockProcessingCheckBox.isChecked():
                try:
                    w, h = map(int, self.dialog.blockSizeComboBox.currentText().split(','))
                    if w <= 0 or h <= 0:
                        self.logger.error("Block size dimensions must be positive")
                        return False
                except:
                    self.logger.error("Invalid block size format (should be width,height)")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Validation failed: {str(e)}")
            return False