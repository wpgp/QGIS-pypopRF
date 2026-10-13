"""Stdlib-only environment contract for owned numerical child processes.

Importing this module never mutates the caller's environment. Dedicated CLI
entrypoints apply the thread caps before importing numerical libraries; GUI
adapters use a separate sanitized child environment.
"""
import os
from pathlib import Path


NATIVE_THREAD_LIMITS = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}


def child_environment(python=None):
    """Return an independent environment, excluding host GIS/native overrides."""
    # -I is the first defense; also remove native QGIS/Qt/GDAL overrides.
    native_pools = set(NATIVE_THREAD_LIMITS)
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "QGIS", "QT_", "GDAL", "GEOS", "PROJ", "PIP_"))
           and key.upper() not in native_pools | {"VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
                                   "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"}}
    directories = [str(Path(python).resolve().parent)] if python else []
    if os.name == "nt":
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        directories += [str(system / "System32"), str(system)]
    else:
        directories += os.defpath.split(os.pathsep)
    env["PATH"] = os.pathsep.join(directories)
    env["PIP_CONFIG_FILE"] = os.devnull
    # Configured forest workers remain independent of each worker's native pool.
    env.update(NATIVE_THREAD_LIMITS)
    return env
