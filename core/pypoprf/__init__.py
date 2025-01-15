# src/pypoprf/__init__.py
"""
pypopRF: Tools for geospatial modeling of population distribution.

This package provides tools for high-resolution population mapping using
machine learning and dasymetric techniques.

Classes:
    Settings: Configuration management for modeling parameters
    FeatureExtractor: Extract features from geospatial covariates
    Model: Random Forest-based population prediction
    DasymetricMapper: High-resolution population redistribution

Example:
    >>> from pypoprf import Settings, FeatureExtractor, Model, DasymetricMapper
    >>> settings = Settings.from_file('config.yaml')
    >>> model = Model(settings)
"""

from importlib.metadata import version

# Core components
from pypoprf.core.feature_extraction import FeatureExtractor
from pypoprf.core.model import Model
from pypoprf.core.dasymetric import DasymetricMapper
from pypoprf.config.settings import Settings

try:
    __version__ = version("pypoprf")
except ImportError:
    __version__ = "unknown"

__author__ = "WorldPop SDI"
__email__ = "b.nosatiuk@soton.ac.uk, rhorom.priyatikanto@soton.ac.uk"
__license__ = "MIT"
__docs__ = "https://pypoprf.readthedocs.io/"

# Define public API
__all__ = [
    "__version__",
    "FeatureExtractor",
    "Model",
    "DasymetricMapper",
    "Settings",
]

# src/pypoprf/core/__init__.py
"""
Core functionality for population modeling.

This module contains the main components for population modeling:
- Feature extraction from geospatial covariates
- Random Forest model training and prediction
- Dasymetric mapping for population redistribution
"""

from pypoprf.core.feature_extraction import FeatureExtractor
from pypoprf.core.model import Model
from pypoprf.core.dasymetric import DasymetricMapper

__all__ = ["FeatureExtractor", "Model", "DasymetricMapper"]

# src/pypoprf/utils/__init__.py
"""
Utility functions for raster and vector processing.

This module provides helper functions for:
- Raster processing and statistics
- Vector data handling
- Visualization tools
"""

from pypoprf.utils.raster import (
    raster_compare,
    raster_stat,
    raster_stat_stack,

)
from pypoprf.utils.visualization import (
    Visualizer,
)
from pypoprf.utils.matplotlib_utils import (
    with_non_interactive_matplotlib,
    non_interactive_backend
)

__all__ = [
    # Raster utilities
    "raster_compare",
    "raster_stat",
    "raster_stat_stack",
    # "create_norm_raster",
    # Visualization
    "Visualizer",
    # Matplotlib
    "with_non_interactive_matplotlib",
    "non_interactive_backend",
]