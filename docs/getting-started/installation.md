# Installation and updates

This is the workflow development build (0.3.0), not a published stable release. Use a ZIP built from this checkout; earlier released ZIPs do not contain these changes.

## Two separate components

The interface runs inside QGIS. Numerical processing runs in a dedicated, per-user **64-bit CPython 3.12** virtual environment. Enabling the plugin never runs pip, modifies QGIS Python, or imports the numerical libraries.

The declared range is QGIS 3.44–4.x. Native acceptance covers Windows AMD64 and Linux glibc x86_64 QGIS 3.44 / Qt 5 and QGIS 4.2 / Qt 6, each with a separate engine. macOS, ARM and musl are not qualified by this build. See [IMPLEMENTATION.md](https://github.com/wpgp/QGIS-pypopRF/blob/master/IMPLEMENTATION.md) for the exact acceptance record.

## Install the development ZIP

1. Build with `python scripts/build_plugin.py` from the repository root, using a development Python. The resulting ZIP excludes datasets, tests and developer environments.
2. In QGIS, choose **Plugins → Manage and Install Plugins → Install from ZIP** and select the generated ZIP.
3. Enable pypopRF and open its dialog.
4. On **Project**, wait for the engine readiness check. Choose an installed 64-bit CPython 3.12 executable if discovery does not find one, then choose **Set up engine**.
5. Wait for binary-wheel SHA-256 verification, exact package-version, native-import and dependency checks to finish. Start analysis only when the engine is ready.

Setup downloads the locked binary dependencies and needs network access, sufficient disk space and permission to write to the user's QGIS cache. It does not automatically download a Python interpreter. Install Python 3.12 separately from [python.org](https://www.python.org/downloads/) if necessary. On Windows, select `python.exe`, not `pythonw.exe` or the Microsoft Store alias.

The initial package installation can take several minutes. You can cancel it from the dialog. A failed or cancelled setup cannot replace a previously verified engine. The setup lock prevents two QGIS processes installing into the same cache concurrently.

## Update safely

Finish or cancel the current analysis before updating the plugin. Install a newly built ZIP through QGIS, then reopen the dialog. If the packaged dependency lock changed, set up the new engine. The active environment switches only after successful verification; old environments are retained for recovery, not recursively deleted.

Keep analysis projects outside the plugin installation and engine-cache directories.
QGIS manages the installed plugin folder; uninstalling/replacing a plugin is not a
project-backup mechanism. Back up the project configuration and important completed
runs before changing an installation.

Existing project input files and earlier run directories are not replaced by an engine update. Model bundles have a strict schema and environment contract; old separate model/scaler files are deliberately not loaded. Retrain when moving to the new engine.

This build does not claim publication in the QGIS repository, automatic self-updates, or offline first-time dependency installation. Do not install dependencies into the QGIS Python environment to work around a setup error; use [troubleshooting](../user-guide/troubleshooting.md).

Next: [Quick start](quickstart.md).
