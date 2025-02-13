"""
pypopRF: Tools for geospatial modeling of population distribution.

Core components for QGIS plugin implementation.
"""

from .core.feature_extraction import FeatureExtractor
from .core.model import Model
from .core.dasymetric import DasymetricMapper
from .config.settings import Settings

__version__ = "0.1.0"
__author__ = "WorldPop SDI"
__email__ = "b.nosatiuk@soton.ac.uk"

# Define public API
__all__ = [
    "FeatureExtractor",
    "Model",
    "DasymetricMapper",
    "Settings",
]
