import threading
from pathlib import Path
from typing import Tuple, Optional, List, Dict

import joblib
import numpy as np
import pandas as pd
import rasterio
from qgis.PyQt.QtCore import QThreadPool, QThread
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import cross_validate
from sklearn.preprocessing import RobustScaler

from ..config.settings import Settings
from ..utils.joblib_manager import joblib_resources
from ..utils.logger import get_logger
from ..utils.workers import PredictionWorker

logger = get_logger()


class Model:
    """
    Population prediction model handler.

    This class manages the training, feature selection, and prediction processes
    for population modeling using Random Forest regression.

    Attributes:
        settings (Settings): Configuration settings for the model
        model (RandomForestRegressor): Trained Random Forest model
        scaler (RobustScaler): Fitted feature scaler
        feature_names (np.ndarray): Names of selected features
        target_mean (float): Mean of target variable for normalization
        output_dir (Path): Directory for saving outputs
    """

    def __init__(self, settings: Settings):
        """
        Initialize model handler.

        Args:
            settings: pypopRF settings instance
        """
        self.settings = settings
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.selected_features = None
        self.target_mean = None
        self.feature_importances = None

        self.output_dir = Path(settings.work_dir) / "output"
        self.output_dir.mkdir(exist_ok=True)

    def train(
        self,
        data: pd.DataFrame,
        model_path: Optional[str] = None,
        scaler_path: Optional[str] = None,
        log_scale: bool = True,
        save_model: bool = True,
    ) -> None:
        """
        Train Random Forest model for population prediction.

        Args:
            data: DataFrame containing features and target variables
                 Must include 'id', 'pop', 'dens' columns
            model_path: Optional path to load pretrained model
            scaler_path: Optional path to load fitted scaler
            log_scale: Whether to train the model with log(dens)
            save_model: Whether to save model after training

        Raises:
            ValueError: If input data is invalid
            RuntimeError: If model loading fails
        """
        logger.info("Starting model training process")

        data = data.dropna()
        pop_column = self.settings.census["pop_column"]
        id_column = self.settings.census["id_column"]
        drop_cols = np.intersect1d(data.columns.values, [id_column, pop_column, "dens"])
        X = data.drop(columns=drop_cols).copy()
        y = data["dens"].values
        if log_scale:
            y = np.log(y + 0.1)
        self.target_mean = y.mean()
        self.feature_names = X.columns.values

        logger.debug(f"Features selected: {self.feature_names.tolist()}")
        logger.debug(f"Target mean: {self.target_mean:.4f}")

        if scaler_path is None:
            logger.info("Creating new scaler")
            self.scaler = RobustScaler()
            self.scaler.fit(X)
        else:
            logger.info(f"Loading scaler from: {scaler_path}")
            with joblib_resources():
                try:
                    self.scaler = joblib.load(scaler_path)
                    logger.debug("Scaler loaded successfully")
                except Exception as e:
                    logger.error(f"Failed to load scaler: {str(e)}")
                    raise

        if model_path is None:
            X_scaled = self.scaler.transform(X)
            self.model = RandomForestRegressor(n_estimators=500)
            logger.debug(
                f"Initialized RandomForestRegressor with {self.model.n_estimators} trees"
            )

            with joblib_resources():
                logger.info("Performing feature selection")
                importances, selected = self._select_features(X_scaled, y)
                logger.debug(f"Selected {len(selected)} features")

            X = X[selected]
            self.selected_features = selected
            self.scaler.fit(X)
            X_scaled = self.scaler.transform(X)

            logger.info("Fitting Random Forest model")
            self.model.fit(X_scaled, y)
            logger.debug("Model fitting completed")

            with joblib_resources():
                logger.info("Calculating cross-validation scores")
                self._calculate_cv_scores(X_scaled, y)
        else:
            logger.info(f"Loading model from: {model_path}")
            with joblib_resources():
                try:
                    self.model = joblib.load(model_path)
                    logger.debug("Model loaded successfully")
                    self.selected_features = self.feature_names
                except Exception as e:
                    logger.error(f"Failed to load model: {str(e)}")
                    raise

        if save_model:
            logger.info("Saving model and scaler")
            with joblib_resources():
                self._save_model()

        logger.info("Model training completed successfully")

    def _save_model(self) -> None:
        """Save model and scaler to disk."""
        model_path = self.output_dir / "model.pkl.gz"
        scaler_path = self.output_dir / "scaler.pkl.gz"

        try:
            joblib.dump(self.model, model_path)
            logger.debug(f"Model saved to: {model_path}")

            joblib.dump(self.scaler, scaler_path)
            logger.debug(f"Scaler saved to: {scaler_path}")

            logger.info("Model and scaler saved successfully")
        except Exception as e:
            logger.error(f"Failed to save model or scaler: {str(e)}")
            raise

    def load_model(self, model_path: str, scaler_path: str) -> None:
        """
        Load saved model and scaler.

        Args:
            model_path: Path to saved model
            scaler_path: Path to saved scaler
        """
        logger.info("Loading saved model and scaler")

        try:
            logger.debug(f"Loading model from: {model_path}")
            self.model = joblib.load(model_path)

            logger.debug(f"Loading scaler from: {scaler_path}")
            self.scaler = joblib.load(scaler_path)

            self.feature_names = self.scaler.get_feature_names_out()
            self.selected_features = self.feature_names
            logger.debug(f"Loaded feature names: {self.feature_names.tolist()}")

            logger.info("Model and scaler loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model or scaler: {str(e)}")
            raise

    def _select_features(
        self, X: np.ndarray, y: np.ndarray, limit: float = 0.01
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Select features based on importance using permutation importance.
        """
        logger.info("Starting feature selection")
        logger.debug(f"Selection threshold: {limit}")

        names = self.feature_names
        ymean = self.target_mean

        logger.debug("Fitting initial model for feature importance")
        model = self.model.fit(X, y)

        logger.info("Calculating permutation importance")
        result = permutation_importance(
            model, X, y, n_repeats=20, n_jobs=1, scoring="neg_root_mean_squared_error"
        )

        sorted_idx = result.importances_mean.argsort()
        importances = pd.DataFrame(
            result.importances[sorted_idx].T / ymean,
            columns=names[sorted_idx],
        )

        self.feature_importances = pd.DataFrame(
            {
                "feature": names,
                "importance": result.importances_mean / ymean,
                "std": result.importances_std / ymean,
            }
        ).sort_values("importance", ascending=False)

        importance_path = Path(self.settings.work_dir) / "output" / "feature_importance.csv"
        self.feature_importances.to_csv(importance_path, index=False)

        selected = importances.columns.values[np.median(importances, axis=0) > limit]
        self.selected_features = selected
        return importances, selected

    def _calculate_cv_scores(self, X_scaled: np.ndarray, y: np.ndarray, cv: int = 10) -> dict:
        """Calculate and print cross-validation scores."""

        logger.debug(f"Starting {cv}-fold cross-validation")
        logger.debug(f"Input shapes: X={X_scaled.shape}, y={y.shape}")

        scoring = {
            "r2": (100, "R2"),
            "neg_root_mean_squared_error": (-1, "RMSE"),
            "neg_mean_absolute_error": (-1, "MAE"),
        }

        logger.debug(f"Metrics to calculate: {list(scoring.keys())}")

        scores = cross_validate(
            self.model,
            X_scaled,
            y,
            cv=cv,
            scoring=list(scoring.keys()),
            return_train_score=True,
            n_jobs=1,
        )
        metrics = {}

        for k in ["neg_root_mean_squared_error", "neg_mean_absolute_error"]:
            scoring["n" + k] = (-100, "n" + scoring[k][1])
            scores["test_n" + k] = scores["test_" + k] / self.target_mean
            scores["train_n" + k] = scores["train_" + k] / self.target_mean

        logger.debug(f"Target mean for normalization: {self.target_mean:.4f}")

        for k in scoring:
            train = scoring[k][0] * scores[f"train_{k}"].mean()
            test = scoring[k][0] * scores[f"test_{k}"].mean()
            gap = abs(train - test)

            metrics[k] = {"train": train, "test": test, "gap": gap}
            if k in ["r2", "neg_root_mean_squared_error", "neg_mean_absolute_error"]:
                logger.info(f"{scoring[k][1]}: test={test:.2f}")
            logger.debug(f"{scoring[k][1]}: train={train:.2f}, test={test:.2f}, gap={gap:.2f}")

        logger.debug("Cross-validation completed")
        return metrics

    def _init_prediction(self) -> Tuple[Dict, rasterio.DatasetReader, Dict]:
        """Initialize resources for prediction."""
        logger.debug("Opening covariate rasters")
        src = {}

        for k in self.settings.covariate:
            src[k] = rasterio.open(self.settings.covariate[k], "r")
            logger.debug(f"Opened covariate: {k}")

        mst = rasterio.open(self.settings.mastergrid, "r")
        profile = mst.profile.copy()
        profile.update(
            {
                "dtype": "float32",
                "blockxsize": self.settings.block_size[0],
                "blockysize": self.settings.block_size[1],
            }
        )
        return src, mst, profile

    def _setup_thread_pool(self) -> QThreadPool:
        """Configure thread pool for parallel processing."""
        executor = QThreadPool.globalInstance()
        executor.setMaxThreadCount(self.settings.max_workers)
        logger.info(f"ThreadPool configuration:")
        logger.info(f"- Available CPU threads: {QThread.idealThreadCount()}")
        logger.info(f"- Using threads: {self.settings.max_workers}")
        return executor

    def _process_windows(self, dst, executor: QThreadPool, log_scale: bool = True) -> Tuple[List, List]:
        """Process raster windows in parallel."""
        windows = [window[1] for window in dst.block_windows()]
        workers = []

        logger.info(f"Creating {len(windows)} tasks")
        PredictionWorker.init_progress(len(windows), logger)

        for i, window in enumerate(windows):
            worker = PredictionWorker(
                window,
                self.settings.covariate,
                self.selected_features,
                self.model,
                self.scaler,
                log_scale=log_scale,
            )
            worker.idx = i
            worker.setAutoDelete(False)
            workers.append(worker)
            executor.start(worker)

        return windows, workers

    def _write_results(self, dst, windows: List, workers: List) -> int:
        """Write worker results to output file."""
        results_count = 0
        writing_lock = threading.Lock()

        for i, worker in enumerate(workers):
            if worker.result is not None:
                with writing_lock:
                    dst.write(worker.result, window=windows[i], indexes=1)
                    results_count += 1
            else:
                logger.warning(f"No result from worker {i}")

        return results_count

    def _cleanup_resources(self, src: Dict, mst: rasterio.DatasetReader) -> None:
        """Clean up opened raster resources"""
        logger.debug("Closing raster files")
        for s in src:
            try:
                src[s].close()
            except Exception as e:
                logger.warning(f"Failed to close source {s}: {str(e)}")

        try:
            mst.close()
        except Exception as e:
            logger.warning(f"Failed to close mastergrid: {str(e)}")

    def predict(self, log_scale: bool = True) -> str:
        """Main prediction method."""

        if self.model is None or self.scaler is None:
            logger.error("Model not trained. Call train() first")
            raise RuntimeError("Model not trained. Call train() first.")

        outfile = Path(self.settings.output_dir) / "prediction.tif"

        with joblib_resources():
            src, mst, profile = self._init_prediction()
            try:
                with rasterio.open(outfile, "w", **profile) as dst:
                    if self.settings.by_block:
                        executor = self._setup_thread_pool()
                        windows, workers = self._process_windows(dst, executor, log_scale=log_scale)

                        executor.waitForDone()
                        PredictionWorker.progress_bar.finish()

                        self._write_results(dst, windows, workers)

                        workers.clear()
                    else:
                        logger.info("Processing entire raster at once")
                        window = rasterio.windows.Window(0, 0, dst.width, dst.height)

                        worker = PredictionWorker(
                            window,
                            self.settings.covariate,
                            self.selected_features,
                            self.model,
                            self.scaler,
                            log_scale=log_scale,
                        )

                        worker.run()

                        if worker.result is not None:
                            dst.write(worker.result, indexes=1)
                        else:
                            logger.error("Failed to process raster")
                            raise RuntimeError("Failed to process raster")
            finally:
                self._cleanup_resources(src, mst)

        return str(outfile)
