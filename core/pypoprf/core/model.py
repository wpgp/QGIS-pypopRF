# src/pypoprf/core/model.py
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import joblib
import rasterio
import threading
import concurrent.futures
from typing import Tuple, Optional, List, Dict
from sklearn.preprocessing import RobustScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_validate
from sklearn.inspection import permutation_importance

from ..config.settings import Settings
from ..utils.joblib_manager import joblib_resources
from ..utils.logger import get_logger
from ..utils.matplotlib_utils import with_non_interactive_matplotlib
from ..utils.raster_processing import progress_bar

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
        self.target_mean = None

        # Create output directory
        self.output_dir = Path(settings.work_dir) / 'output'
        self.output_dir.mkdir(exist_ok=True)

    def train(self,
              data: pd.DataFrame,
              model_path: Optional[str] = None,
              scaler_path: Optional[str] = None,
              save_model: bool = True) -> None:
        """
        Train Random Forest model for population prediction.

        Args:
            data: DataFrame containing features and target variables
                 Must include 'id', 'pop', 'dens' columns
            model_path: Optional path to load pretrained model
            scaler_path: Optional path to load fitted scaler
            save_model: Whether to save model after training

        Raises:
            ValueError: If input data is invalid
            RuntimeError: If model loading fails
        """
        logger.info("Starting model training process")

        data = data.dropna()
        drop_cols = np.intersect1d(data.columns.values, ['id', 'pop', 'dens'])
        X = data.drop(columns=drop_cols).copy()
        y = data['dens'].values
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
            logger.info("Training new model")
            X_scaled = self.scaler.transform(X)
            self.model = RandomForestRegressor(n_estimators=500)
            logger.debug(f"Initialized RandomForestRegressor with {self.model.n_estimators} trees")

            with joblib_resources():
                logger.info("Performing feature selection")
                importances, selected = self._select_features(X_scaled, y)
                logger.debug(f"Selected {len(selected)} features")

            X = X[selected]
            self.scaler.fit(X)
            X_scaled = self.scaler.transform(X)

            logger.info("Fitting Random Forest model")
            self.model.fit(X_scaled, y)
            logger.debug("Model fitting completed")
        else:
            logger.info(f"Loading model from: {model_path}")
            with joblib_resources():
                try:
                    self.model = joblib.load(model_path)
                    logger.debug("Model loaded successfully")
                except Exception as e:
                    logger.error(f"Failed to load model: {str(e)}")
                    raise

        with joblib_resources():
            logger.info("Calculating cross-validation scores")
            self._calculate_cv_scores(X_scaled, y)

        if save_model:
            logger.info("Saving model and scaler")
            with joblib_resources():
                self._save_model()

        logger.info("Model training completed successfully")

    def _select_features(self,
                         X: np.ndarray,
                         y: np.ndarray,
                         limit: float = 0.05,
                         plot: bool = True) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Select features based on importance using permutation importance.
        """
        logger.info("Starting feature selection")
        logger.debug(f"Selection threshold: {limit}")

        names = self.feature_names
        ymean = self.target_mean

        logger.debug("Fitting initial model for feature importance")
        model = self.model.fit(X, y)

        try:
            from qgis.core import Qgis
            IN_QGIS = True
        except ImportError:
            IN_QGIS = False

        logger.info("Calculating permutation importance")
        if IN_QGIS:
            result = permutation_importance(
                model, X, y,
                n_repeats=10,
                n_jobs=1,
                scoring='neg_root_mean_squared_error'
            )
        else:
            result = permutation_importance(
                model, X, y,
                n_repeats=10,
                n_jobs=2,
                scoring='neg_root_mean_squared_error'
            )

        sorted_idx = result.importances_mean.argsort()

        importances = pd.DataFrame(
            result.importances[sorted_idx].T / ymean,
            columns=names,
        )

        selected = importances.columns.values[importances.mean(axis=0) > limit]

        if plot:
            logger.debug("Creating feature importance plot")
            self._plot_feature_importance(importances, limit)

        logger.info(f"Selected {len(selected)} features out of {len(names)} features")
        logger.debug(f"Selected features: {selected.tolist()}")

        return importances, selected

    @with_non_interactive_matplotlib
    def _plot_feature_importance(self,
                                 importance_df: pd.DataFrame,
                                 limit: float) -> None:
        """
        Create box plot visualization of feature importances.

        Args:
            importance_df: DataFrame with feature importances
            limit: Threshold line to display
        """
        logger.info("Creating feature importance plot")

        sy = importance_df.shape[1] * 0.25 + 0.5
        fig, ax = plt.subplots(1, 1, figsize=(4, sy), dpi=90)

        importance_df.plot.box(
            vert=False,
            whis=5,
            ax=ax,
            color='k',
            sym='.k'
        )

        ax.axvline(x=limit, color='k', linestyle='--', lw=0.5)
        ax.set_xlabel('Decrease in nRMSE')

        plt.tight_layout()
        save_path = Path(self.settings.work_dir) / 'output' / 'feature_selection.png'
        plt.savefig(save_path)
        plt.close()

        logger.info(f"Feature importance plot saved to: {save_path}")

    def _calculate_cv_scores(self,
                             X_scaled: np.ndarray,
                             y: np.ndarray,
                             cv: int = 10) -> None:
        """Calculate and print cross-validation scores."""

        logger.debug(f"CV folds: {cv}")

        scoring = {'r2': (100, 'R2'),
                   'neg_root_mean_squared_error': (-1, 'RMSE'),
                   'neg_mean_absolute_error': (-1, 'MAE')
                   }

        scores = cross_validate(
            self.model, X_scaled, y,
            cv=cv,
            scoring=list(scoring.keys()),
            return_train_score=True,
            n_jobs=1
        )

        for k in ['neg_root_mean_squared_error', 'neg_mean_absolute_error']:
            scoring['n' + k] = (-100, 'n' + scoring[k][1])
            scores['test_n' + k] = scores['test_' + k] / self.target_mean
            scores['train_n' + k] = scores['train_' + k] / self.target_mean

        for k in scoring:
            train = scoring[k][0] * scores[f'train_{k}'].mean()
            test = scoring[k][0] * scores[f'test_{k}'].mean()
            gap = abs(train - test)


    @with_non_interactive_matplotlib
    def predict(self) -> str:
        """
        Generate predictions using trained model.

        Returns:
            str: Path to output prediction raster file

        Raises:
            RuntimeError: If model is not trained
            FileNotFoundError: If input rasters are missing
        """
        logger.info("Starting prediction generation")

        if self.model is None or self.scaler is None:
            logger.error("Model not trained. Call train() first")
            raise RuntimeError("Model not trained. Call train() first.")

        from concurrent.futures import ThreadPoolExecutor
        default_executor = ThreadPoolExecutor

        try:
            from qgis.PyQt.QtCore import QThreadPool, QRunnable
            class RasterWorker(QRunnable):
                def __init__(self, window, process_func):
                    super().__init__()
                    self.window = window
                    self.process_func = process_func
                    self.result = None

                def run(self):
                    try:
                        self.process_func(self.window)
                    except Exception as e:
                        logger.error(f"Error in RasterWorker: {str(e)}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")

            qgis_executor = QThreadPool.globalInstance()
            IN_QGIS = True
        except ImportError:
            IN_QGIS = False

        with joblib_resources():
            logger.debug("Opening covariate rasters")
            src = {}
            try:
                for k in self.settings.covariate:
                    src[k] = rasterio.open(self.settings.covariate[k], 'r')
                    logger.debug(f"Opened covariate: {k}")

                # Open mastergrid
                logger.debug("Opening mastergrid")
                mst = rasterio.open(self.settings.mastergrid, 'r')

                # Get profile from mastergrid
                profile = mst.profile.copy()
                profile.update({
                    'dtype': 'float32',
                    'blockxsize': self.settings.block_size[0],
                    'blockysize': self.settings.block_size[1],
                })
                logger.debug("Profile created from mastergrid")

                # Setup locks
                reading_lock = threading.Lock()
                writing_lock = threading.Lock()
                names = self.feature_names
                outfile = Path(self.settings.output_dir) / 'prediction.tif'
                logger.info(f"Output will be saved to: {outfile}")

                with rasterio.open(outfile, 'w', **profile) as dst:
                    def process(window):
                        df = pd.DataFrame()
                        with reading_lock:
                            for s in src:
                                arr = src[s].read(window=window)[0, :, :]
                                df[s + '_avg'] = arr.flatten()

                        df = df[names]

                        # Make predictions
                        sx = self.scaler.transform(df)
                        yp = self.model.predict(sx)
                        res = yp.reshape(arr.shape)

                        with writing_lock:
                            dst.write(res, window=window, indexes=1)

                    if self.settings.by_block:
                        logger.info("Processing by blocks")
                        try:
                            logger.debug("Getting block windows...")
                            block_windows = list(dst.block_windows())
                            logger.debug(f"First block window type: {type(block_windows[0])}")
                            logger.debug(f"First block window content: {block_windows[0]}")

                            windows = []
                            for block_window in block_windows:
                                idx, window = block_window
                                windows.append(window)

                            if IN_QGIS:
                                logger.debug(f"Number of workers to create: {len(windows)}")
                                qgis_executor.setMaxThreadCount(self.settings.max_workers)
                                workers = []

                                for i, window in enumerate(windows):
                                    try:
                                        worker = RasterWorker(window, process)
                                        workers.append(worker)
                                        qgis_executor.start(worker)
                                    except Exception as e:
                                        import traceback
                                        logger.error(f"Full traceback: {traceback.format_exc()}")
                                        raise

                                logger.debug("Waiting for workers to complete...")
                                qgis_executor.waitForDone()
                                logger.debug("All workers completed")

                            else:
                                with default_executor(max_workers=self.settings.max_workers) as executor:
                                    list(progress_bar(
                                        executor.map(process, windows),
                                        self.settings.show_progress,
                                        len(windows),
                                        desc="Prediction"
                                    ))

                        except Exception as e:
                            logger.error(f"Error in block processing setup: {str(e)}")
                            import traceback
                            logger.error(f"Full traceback: {traceback.format_exc()}")
                            raise


            finally:
                logger.debug("Closing mastergrid")
                for s in src:
                    try:
                        s.close()
                    except Exception:
                        pass
                try:
                    mst.close()
                except Exception:
                    pass

        logger.info("Prediction completed successfully")
        return str(outfile)

    def _save_model(self) -> None:
        """Save model and scaler to disk."""
        model_path = self.output_dir / 'model.pkl.gz'
        scaler_path = self.output_dir / 'scaler.pkl.gz'

        try:
            joblib.dump(self.model, model_path)
            logger.debug(f"Model saved to: {model_path}")

            joblib.dump(self.scaler, scaler_path)
            logger.debug(f"Scaler saved to: {scaler_path}")

            logger.info("Model and scaler saved successfully")
        except Exception as e:
            logger.error(f"Failed to save model or scaler: {str(e)}")
            raise

    def load_model(self,
                   model_path: str,
                   scaler_path: str) -> None:
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
            logger.debug(f"Loaded feature names: {self.feature_names.tolist()}")

            logger.info("Model and scaler loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model or scaler: {str(e)}")
            raise