# Interface

The current interface has five tabs: **Project**, **Input data**, **Settings**,
**Results** and **Details**. Historical screenshots from earlier plugin versions
do not describe this layout.

## Project

Choose a project folder, then use **Create project** for a new folder or
**Open project** when `config.yaml` already exists. Opening restores the saved
inputs and settings rather than resetting the project. Merely selecting another
folder does not switch the active project; open it explicitly.

The **Analysis engine** area checks for the plugin's isolated Python runtime.
Select an installed 64-bit CPython 3.12 executable and use **Set up engine**
when needed. Setup downloads the locked wheel dependencies into a separate
per-user environment; plugin activation does not install packages into QGIS.
An update only switches to a verified new environment after its checks pass.

Setup and discovery run in a background worker. **Cancel setup** requests
cancellation of setup. Read the readiness message to see whether a project,
inputs or engine preparation is still needed. See the
[installation guide](../getting-started/installation.md) for platform details.

## Input data

Select the **Zone grid** and **Population census** and add at least one covariate
using **Add raster files…**. Optional fields are **Water mask (1 = exclude)**,
**Population support (1 = include)** and **Age and sex census**.

Imports run outside the GUI and report progress. The run button becomes
**Cancel import** while an import is active. Name collisions are rejected;
inputs are not overwritten. On a failed selection the field is restored to
the input actually configured in the project.

The covariate table shows name, size, path and actions. Its informational cells
are read-only. Use a row's **Delete** button or the Delete key to remove selected
covariates from configuration; their copied files remain in the data directory.
See [input requirements](input-data.md) for alignment, NoData and sidecar rules.

**Prepare / align inputs…** opens a guided workflow using the separate numerical
engine. Select a reference grid, an existing zone raster or census polygons, CSV
ID/population columns, and explicit predictor quantities/resampling methods.
Inspect the diagnostics and acknowledge the choices before creating a **new**
prepared project. Existing projects and source files are not overwritten. The
wizard opens the prepared project only after successful completion and your
confirmation. See [preparation rules](input-data.md#guided-preparation).

Local QGIS layers can be selected instead of browsing for supported raster/vector
files. These controls use the underlying local dataset, not rendered colors.
Remote, memory, virtual, filtered or edited layers must be explicitly exported
first; a selection is not silently substituted for the complete file.

## Settings

Map census column names, configure workers and tile size, choose the target
transform and feature-selection threshold, and set diagnostic logging. The
option **Add population maps to QGIS** applies after successful completion.
There is no model-import control or GUI control for advanced spatial-CV settings.

Full descriptions and supported advanced YAML fields are in
[Settings](settings.md).

## Running and stopping

**Run analysis** starts a separate engine process. Numerical preflight,
fingerprinting, fitting and raster computation occur outside the QGIS GUI.
The progress area names the current stage; numerical stage percentages are
milestones rather than an estimate of remaining wall-clock time.

**Stop** requests cooperative cancellation. If the owned calculation process
does not respond within the grace period, the adapter stops that process.
The GUI waits for native process completion before releasing job ownership or
presenting a terminal result. Closing or unloading during background work
requests cancellation and defers disposal until owned work has finished.
Earlier runs remain available.

## Results

Each attempt has its own directory beneath `<output_dir>/runs/`. The Results
tab lists recent runs with status and population-map count. Use **Refresh**,
**Open result folder**, or **Add maps to QGIS**. Only complete runs with valid,
present population-map paths can be added. Failed, running or cancelled
attempts can be inspected for diagnostics but are not treated as finished maps.

The raw `prediction.tif` contains model density weights and is not added as a
population-count result. The result folder also contains the effective config,
model bundle, extracted features, validation records and manifest.

The quality dashboard below the run history reads the saved held-out
zone-density predictions, not the final census-normalized map. It shows OOF
observed/predicted scatter, highest absolute zone-density errors, permutation
importance and explicit validation limitations. The training-mean baseline uses
the same outer folds and only the other folds' observations. Missing, changed or
unsupported diagnostic artifacts are reported rather than replaced by made-up
scores. Conservation remains a separate engine-reported check; this panel does
not independently recompute raster totals or establish pixel accuracy.

**Show selected / top error zones in QGIS** adds diagnostic zone-centre points
when saved centroids and CRS are available. Those points identify census zones,
not the location of pixel errors. Completed population maps are grouped by run
under **pypopRF**, with log-spaced display colors and **persons/pixel** labels;
styles do not alter values. Re-adding the same result does not duplicate it.

**Population in an area…** sums a selected completed population map inside a
local polygon AOI. The rule is **cell centre inside or on the polygon boundary**;
overlapping AOI polygons are unioned and counted once. Cells partly intersecting
the boundary are not fractionally allocated. Coverage is the fraction of selected
centres *within the raster* with valid values, not the fraction of the entire AOI
area. An AOI outside the raster or containing NoData yields a clearly labelled
partial supported-cell sum. This is a model-derived estimate, not a new census.

## Details

Details shows bounded plain-text setup and processing messages. **Clear view**
clears the displayed messages; **Copy diagnostics** copies them for a bug report.
Clearing the view does not delete saved logs or previous runs.

Verification of zone totals checks allocation arithmetic. It does not establish
where people actually live within a zone; reported model scores describe
held-out zone-average density rather than independent pixel-level accuracy.

[Quick start](../getting-started/quickstart.md) · [Running analysis](running-analysis.md)
