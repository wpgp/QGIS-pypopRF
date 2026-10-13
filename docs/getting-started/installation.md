# Installation and updates

This is the development build (0.3.1), not a published stable release. Use a ZIP built from this checkout; earlier released ZIPs do not contain these changes.

## Two separate components

The interface runs inside QGIS. Numerical processing runs in a dedicated, per-user **64-bit CPython 3.12** virtual environment. Enabling the plugin never runs pip, modifies QGIS Python, or imports the numerical libraries.

The declared range is QGIS 3.44–4.x. Native acceptance targets Windows AMD64 and Linux glibc x86_64 QGIS 3.44 / Qt 5 and QGIS 4.2 / Qt 6, each with a separate engine. macOS, ARM and musl are not qualified by this build. The [development guide](../development.md) explains the reproducible checks; private local qualification reports are not published as repository files.

## Install the development ZIP

1. Build with `python scripts/build_plugin.py` from the repository root, using a development Python. The resulting ZIP excludes datasets, tests and developer environments.
2. In QGIS, choose **Plugins → Manage and Install Plugins → Install from ZIP** and select the generated ZIP.
3. Enable pypopRF and open its dialog.
4. On **Project**, wait for the engine readiness check. Choose an installed 64-bit CPython 3.12 executable if discovery does not find one, then choose **Set up engine**.
5. Wait for binary-wheel SHA-256 verification, exact package-version, native-import and dependency checks to finish. Start analysis only when the engine is ready.

Setup downloads the locked binary dependencies and needs network access, sufficient disk space and permission to write to the user's QGIS cache. It does not automatically download a Python interpreter. Install Python 3.12 separately from [python.org](https://www.python.org/downloads/) if necessary. On Windows, select `python.exe`, not `pythonw.exe` or the Microsoft Store alias.

The initial package installation can take several minutes. You can cancel it from the dialog. A failed or cancelled setup cannot replace a previously verified engine. The setup lock prevents two QGIS processes installing into the same cache concurrently.

## Update safely

1. Finish the current analysis, or cancel it and wait for the task to stop.
2. Use **Plugins → Manage and Install Plugins → Install from ZIP** to install the
   newly built ZIP. There is no need to uninstall the modern plugin first.
3. Reopen pypopRF and wait for the engine check. If the packaged dependency lock
   changed, choose **Update / repair engine** and wait for verification.

Analysis and preparation jobs use a private, verified source snapshot and working
directory outside the installation. Unloading the plugin requests cancellation;
owned resources are released asynchronously after the child actually exits.
This protects the installed folder from those jobs, but updating in the middle
of an analysis is not a way to preserve or resume that analysis.

The active engine environment switches only after successful verification; old
environments are retained for recovery, not recursively deleted. A plugin ZIP
replacement and an engine update are different operations. QGIS's ZIP installer
does not guarantee rollback for an arbitrary incomplete plugin archive. Use a
ZIP built and verified by this repository, and keep the preceding valid ZIP.

Keep analysis projects outside the plugin installation and engine-cache directories.
The interface refuses project and preparation destinations inside these protected
locations before creating or activating them. This is a location safeguard, not
a substitute for backing up an existing legacy installation's data.
QGIS manages the installed plugin folder; uninstalling/replacing a plugin is not a
project-backup mechanism. Back up the project configuration and important completed
runs before changing an installation.

### One-time migration from a legacy Windows installation

An older plugin may have loaded numerical DLLs from its installation folder into
the QGIS process. Disabling the plugin cannot safely unload those DLLs. If this
is the installation you are replacing:

1. In **Installed**, uncheck pypopRF to disable it; do not uninstall it first.
2. Save your QGIS project and close **all QGIS instances using that profile**.
3. Reopen QGIS with pypopRF still disabled.
4. Install the valid new ZIP using **Install from ZIP**, then enable pypopRF.
5. Set up the separate engine and reopen your analysis project.

Normal QGIS process exit releases the old DLL locks. Do not force-unload DLLs,
kill unrelated processes, or manually delete a folder while QGIS still uses it.
If replacement still fails, stop and follow the [recovery checks](../user-guide/troubleshooting.md#plugin-update-or-locked-folder).

Existing project input files and earlier run directories are not replaced by an engine update. Model bundles have a strict schema and environment contract; old separate model/scaler files are deliberately not loaded. Retrain when moving to the new engine.

This build does not claim publication in the QGIS repository, automatic self-updates, or offline first-time dependency installation. Do not install dependencies into the QGIS Python environment to work around a setup error; use [troubleshooting](../user-guide/troubleshooting.md).

Next: [Quick start](quickstart.md).
