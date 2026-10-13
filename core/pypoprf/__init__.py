"""
pypopRF: Tools for geospatial modeling of population distribution.

Core components for QGIS plugin implementation.
"""

from importlib import import_module
import configparser
from pathlib import Path

_metadata = configparser.ConfigParser(interpolation=None)
_metadata.read(Path(__file__).resolve().parents[2] / "metadata.txt", encoding="utf-8")
__version__ = _metadata.get("general", "version", fallback="unknown")
__author__ = "WorldPop SDI"
__email__ = "b.nosatiuk@soton.ac.uk"

# Define public API
__all__ = [
    "FeatureExtractor",
    "Model",
    "DasymetricMapper",
    "Settings",
]

_PUBLIC_MODULES = {
    "FeatureExtractor": ".algorithms.feature_extraction",
    "Model": ".algorithms.model",
    "DasymetricMapper": ".algorithms.dasymetric",
    "Settings": ".config.settings",
}


def __getattr__(name):
    """Keep helpers importable without eagerly loading the numerical stack."""
    if name not in _PUBLIC_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_PUBLIC_MODULES[name], __name__), name)
    globals()[name] = value
    return value
