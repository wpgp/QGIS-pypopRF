# Troubleshooting

Start with the status shown in the analysis window. Each attempt has its own
directory under `output/runs`; failed and cancelled attempts never replace a
previous completed result. Include the run's log and `manifest.json` when
reporting an issue. Avoid sending personal census data publicly.

## Start with the symptom

| What you see | First safe action |
| --- | --- |
| Project shows Open/Create even though a folder was chosen | Selection is not activation. Click the action and look for Project open / Active project. |
| Project open is disabled | Normal: that folder is already active. Choose a different folder to switch, not repeatedly reopen it. |
| Run analysis is disabled | Use the bottom checklist to find the missing engine, active project or required input; green selection checks do not guarantee numerical validity. |
| No compatible Python / requires 64-bit CPython 3.12 | Follow Engine's compatible choices or Get Python instructions, then Find Python again. |
| Repair failed, previous engine remains available | Read the inline error and Details; do not delete the working environment. |
| Import would overwrite an existing input | Resolve the nonmodal reuse / separate-copy / cancel choice, not filesystem deletion. |
| An input field became empty or restored its old value | Read its inline error and Details; a rejected import is not registered as a new input. |
| Waiting / Stopping… | Wait for owned work to finish; no terminal result is accepted before process completion. |
| Existing folders cannot be opened | Check config.yaml, the selected location and configured data/output/log paths; do not create a replacement config over the original. |

## Project selection and activation

The folder picker is only a candidate. A successful **Create project** or **Open
project** changes the button to **Project open** (disabled) and shows **Active
project: …** below the picker. Changing the selected folder gates inputs/settings
and analysis until that selection is explicitly activated. Selecting the same
canonical active folder does not reset it. See [Projects](projects.md).

If opening fails, retain the original `config.yaml` and inputs. Read the exact
error before editing a backup copy. Malformed YAML, missing required saved
settings and protected/log-alias locations are refused, not silently repaired.
The plugin does not create a compatible project merely by selecting any old data
folder or replace a malformed configuration with defaults.

Before editing configuration externally, finish work, save your QGIS project,
close QGIS and back up the configuration. After editing, reopen QGIS and explicitly
open the analysis folder again. Closing only the plugin dialog hides and reuses
it; it does not reread YAML. **Project open** is a state indicator, not a reload
button. Do not change live configuration files while importing or calculating.

## Import conflicts and cleared references

An existing filename can refer to an earlier copied input even after its field
was cleared. Clearing a field or deleting a covariate row removes the saved
reference, not its file. The conflict dialog offers verified identical-file reuse
when eligible, a separate copy with a new name, or cancellation. A byte difference
or external raster resources can make reuse unavailable. Never delete an original
file just to dismiss the conflict; inspect the choice and [input rules](input-data.md).

## Appearance and lengthy messages

Plugin windows use an independent light scheme even when QGIS is dark. Operating
system file pickers/title bars remain operating-system controlled. At a small
window size, tab contents may need scrolling; the bottom checklist/status/actions
stay accessible. Increase the window size if you use large fonts.

Status text is fitted to three rendered lines; hover for caller-bounded text or
open **Details** for diagnostics. **Copy diagnostics** copies the displayed log,
and **Clear view** affects that view, not saved files or completed results.

## Engine setup

The interface does not need NumPy, pandas, rasterio or scikit-learn installed in
QGIS. Select a compatible 64-bit CPython 3.12 on **Engine** and use **Set up engine**.
QGIS 4 may use Python 3.13; that interpreter is not the calculation engine.
Setup uses a separate cache and exact packaged dependency lock. Check proxy,
network, free space and write permissions if package downloads fail. Setup output
is shown in Details. Do not run pip in the QGIS Python to work around the failure.
An earlier healthy engine remains active if a repair fails; an outdated lock
requires successful setup before the new plugin can run.

## Plugin update or locked folder

Keep a valid previous ZIP and keep projects outside the plugin installation and
engine cache. For a legacy plugin which loaded DLLs into QGIS, use the
[disable → close QGIS → reopen disabled → install ZIP migration](../getting-started/installation.md#one-time-migration-from-a-legacy-windows-installation).
Do not uninstall first or force-delete an active plugin folder.

If installation still fails, save your QGIS work, disable pypopRF and close all
instances using the affected profile. Check the exact installer error and ensure
the ZIP was successfully built and verified. Other QGIS instances, antivirus or
backup software can also retain a file handle; do not assume every lock comes
from this plugin. Retry the valid ZIP with the plugin disabled. If an incomplete
archive replaced files, reinstall the previous valid ZIP with the plugin disabled.
The QGIS installer is not a transactional plugin backup.

If this does not recover the plugin, report the QGIS/OS versions and installer
error without private data. Do not delete your project, engine cache or a broad
QGIS profile as a repair step. A surviving engine job is not a reason to kill
every Python process; cancellation and cleanup are scoped to the owned job.

## Input checks

All rasters must define a CRS, contain one band, and use the same pixel grid.
Matching CRS and pixel size alone do not establish alignment: origin, rotation,
extent and dimensions also matter. Prepare aligned rasters explicitly before
analysis; use nearest-neighbour resampling for zone IDs and binary masks.

Census IDs must be unique finite integers matching zone IDs in the mastergrid.
Population values must be finite and nonnegative. Repeated CSV column names are
rejected. Custom ID and population column names are supported; validation does
not rename columns in your original CSV.

Water masks use 1 for excluded water and 0 for land. Constraints use 1 for allowed
support and 0 for excluded cells. Unknown mask coverage is excluded. A zone with
positive population needs at least one eligible cell with a positive predicted
weight; otherwise the run fails with the affected zone IDs. A single valid cell
is supported. Zero-population zones receive zero within their eligible support.

Covariate NoData means unknown, unless the source dataset explicitly defines a
different meaning. It is not automatically replaced by zero. Selected predictor
rasters must provide usable values on cells where population is allocated.

New TIFF imports with external `.msk`, `.aux.xml` or world files are rejected
because copying only the TIFF would change its interpretation. Create a
self-contained aligned GeoTIFF with an internal validity mask before importing.
Existing canonical project TIFFs retain their sidecars; these dataset resources
are fingerprinted as inputs by the engine.

## Older model files

Old separate `model.pkl.gz` / `scaler.pkl.gz` files do not record a complete
prediction contract. Retrain the model to create `model_bundle.pkl.gz`. The bundle
records its target transformation, ordered feature schema, runtime versions and
grid geometry. Load only trusted local model files.

## A failed or cancelled analysis

Read the terminal message and the run log. Do not interpret intermediate TIFFs in
a failed run as completed population maps. Only a run with a complete manifest
has passed the population checks. Cancel requests are cooperative; the current
operation may need to finish before resources can be closed safely.

## Interpreting model quality

Preserving census totals is a calculation invariant. It does not prove that the
population is placed in the correct buildings or pixels. Validation metrics
describe held-out census zones in population-per-supported-pixel units. Grouped
or spatial validation must be interpreted according to its recorded split
strategy; random-zone diagnostics do not establish spatial independence.

## What to include in a useful report

1. Plugin build, QGIS version, operating system and whether this is installation,
   engine setup, project opening, importing or running.
2. Exact message from **Details → Copy diagnostics**, not only the final percent.
3. For a run, its `manifest.json` and run log; for opening, a redacted configuration
   and the distinction between selected and active paths.
4. Minimal reproduction with synthetic/public data when possible.

Redact personal paths, credentials, identifying census records and restricted
source data. A screenshot may show filenames or user names; check it before
posting to a public issue. Do not publish a whole project/cache/profile to obtain help.

## Development diagnostics

Run `python -m pytest` in the development engine environment. Native QGIS tests
require genuine QGIS/Qt bindings and are marked `qgis`. See the development guide
for the maintained regression suites, package checks and native-test commands.
