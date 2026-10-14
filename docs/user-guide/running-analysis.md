# Run an analysis and interpret its results

Use an open external [project](projects.md), compatible [input data](input-data.md)
and reviewed [settings](settings.md). Every attempt creates a separate run; it
does not replace an earlier population map.

## From project to Run

1. On **Engine**, wait for the engine check to finish. If it is not prepared,
   choose a compatible Python and **Set up engine**. A ready engine needs no
   routine repair before each analysis. You can open a project without an
   installed engine once background work has finished, but cannot calculate yet.
2. On **Project**, create/open the intended folder. Selecting a different folder
   makes it a candidate and disables Run/input editing until you explicitly open
   it. The candidate is not activated and the previous saved project is not
   overwritten just by changing the selection.
3. On **Input data**, select a zone grid and population census, and use **Add
   raster files…** for at least one named covariate. Finish any copy/conflict
   dialog or preparation first. Optional masks and age-sex counts must obey
   their distinct [input contracts](input-data.md).
4. On **Settings**, check the CSV column mapping, tile/worker budget and target
   transform. On the footer, review **Selected for run**, then choose
   **Run analysis**. Run is disabled when required selections/engine are missing.
   While another task owns the interface, starting a new run is refused; the
   same main control may instead offer Stop/Cancel for that task.

The checklist describes selected inputs, not their numerical validity. The
separate engine checks CSV schema and values, full raster alignment, validity
masks and eligible census support before publishing population maps. Selecting
a raster does not cause an implicit reprojection/resampling; use **Prepare /
align inputs…** deliberately if needed.

Keep project configuration, CSVs, rasters and sidecars stable during import or
analysis. Fingerprints detect observed resource changes, not an adversarial
point-in-time snapshot of another process repeatedly replacing/restoring data.

## What runs, and how to stop it

The workflow applies water exclusion, derives any constrained zone grid,
extracts zonal covariate means, trains/validates the seeded Random Forest,
predicts nonnegative weights and redistributes census totals over eligible
pixels. The main map is always unconstrained; a supplied support mask adds a
separately normalized constrained map. Age-sex maps use ID-keyed totals for
each supported group, not CSV row positions.

While calculating, the main action becomes **Stop**. It requests cooperative
cancellation without blocking the GUI. The interface retains the owned child
and temporary files until actual process exit is verified. After the grace
period, an unresponsive owned process may be stopped forcibly; unrelated Python
or QGIS processes are not targeted. Closing/unloading follows the same ownership
rule. Engine setup has its own **Cancel setup** action on Engine; cancelling a
check is not the same as a failed engine verification.

The footer shows compact status and elapsed task time. Long messages are fitted
to a few painted lines; their complete caller-bounded text remains in the tooltip
and **Details**. The Details page holds full diagnostic messages and stage
history. Progress milestones are not an ETA, a download-byte percentage or an
accuracy score. Engine package downloads use an indeterminate activity bar.

Output files are published individually from temporary files after successful
close/validation. A stopped or failed run can retain intermediate files for
diagnosis, but that is **not** a complete result. Its terminal manifest records
failure/cancellation; an attempt rejected before creating a run may have no
history entry. Previous runs and source files are preserved.

## Find the saved run

Open **Results** and select a run. **Refresh** rereads history without discarding
your selection. **Open result folder** opens its files; **Add maps to QGIS**
loads population maps from a completed run. Failed/stopped attempts remain
available for diagnosis, not map loading. A newly verified successful run takes
selection; a failed attempt does not silently replace the selected earlier run.

Default location:

```text
<project>/output/runs/<timestamp-id>/
```

If `output_dir` differs, use `<output_dir>/runs/<timestamp-id>/`. Run IDs are
shown as local start times in Results; the exact ID/path is in the row tooltip.

| Product | Use |
| --- | --- |
| `manifest.json` | Status, displayable outputs, input/resource fingerprints, artifact inventory, runtime/source provenance and diagnostics. |
| `run_config.yaml` | All effective settings/defaults and resolved input paths. |
| `population_unconstrained.tif` | Final estimated persons per pixel on unconstrained valid support. |
| `population_constrained.tif` | Additional persons-per-pixel map when a support mask was supplied. |
| `prediction.tif` | Model allocation weights; **not final population counts**. |
| `normalized_census*.tif` | Zone normalization coefficients, not a population map. |
| `agesex/population_<group>*.tif` | Group-specific population maps, optionally constrained. |
| `agesex/age_sex_totals.csv` | ID-keyed demographic-sum versus main-census comparison. |
| `features.csv` | Derived zonal training table, not a rewritten source census. |
| `cv_metrics.json`, `cv_predictions.csv`, `cv_zone_geometry.csv` | Actual held-out validation, folds and spatial diagnostics. |
| `feature_importance.csv` | Final training procedure's permutation selection scores/spread. |
| `model_bundle.pkl.gz` | Model/preprocessing/schema bundle; executable serialization, trusted sources only. |
| Configured `.log` file | Engine diagnostics for this run, if file logging is enabled. |

The manifest's displayable `outputs` list differs from its complete immutable
artifact inventory. Mutable logs and the manifest itself are not included in
that inventory. A file being present does not establish that its run completed;
the GUI requires consistent terminal status and verified output metadata.

## Read the quality dashboard

Selecting a saved run loads the dashboard beneath history. Keep two questions
separate:

- **Conservation**: did redistribution match each supplied census zone/group
  total within numerical tolerances? This is a correctness check, not evidence
  that people were located correctly within the zone. The dashboard reports
  the engine's recorded conservation result; opening history does not rerun
  every per-zone raster sum.
- **Held-out density quality**: how well did the complete training procedure
  predict census-zone average density on held-out zones? The observed/predicted
  scatter uses out-of-fold predictions, not in-sample fitting or independent
  pixel observations.

Inspect RMSE, MAE, R² where available, the validation strategy/limits, high-error
zones and feature selection scores. A displayed mean baseline is derived from
the other folds' training targets, not the held-out target itself. Missing,
malformed or inconsistent saved artifacts make diagnostics unavailable rather
than producing invented points or trustworthy-looking scores.

**Show selected / top error zones in QGIS** adds diagnostic centroid markers
when saved spatial geometry/CRS is available. They are zone-centroid locations,
not zone-boundary polygons or a pixel-confidence surface. Inspect them alongside
your administrative boundaries and source data.

Default spatial validation divides the **full raster footprint** into a 4×4
grid and assigns eligible zone-pixel centroids to blocks. All zones within a
block stay together; preprocessing/selection/forest are freshly fitted inside
each outer training fold. There is no separation buffer: large zones may cross
block boundaries and adjacent blocks may remain dependent. Too few occupied
blocks makes metrics unavailable, with no hidden shuffled fallback. User groups
and shuffled-zone diagnostics are explicitly labelled. See [advanced validation
settings](settings.md#advanced-configuration) before comparing block designs.

The density target and RMSE/MAE use population per eligible mastergrid pixel,
not people/km²; R² and normalized errors are dimensionless. None validates
high-resolution accuracy. Changing blocks, support, grid resolution or target
transform can change the comparison. Use independent data and a justified
spatial design before making fine-pixel accuracy claims.

## Estimate population inside an AOI

1. Select a **completed** run in Results with the engine ready and no other task
   running, then choose **Population in an area…**.
2. Choose a published **population** map and local polygon file/QGIS layer.
   Do not use `prediction.tif`, coefficients or an unrelated density raster.
3. Choose **Calculate population** and read both the total and coverage warning.
   During calculation, **Stop** requests cancellation; closing also waits for
   the owned operation to stop.

The tool unions overlapping polygons so cells are counted once, transforms valid
polygon geometry into the raster CRS and sums finite supported cell counts.
A cell is included when its **center is inside or on the polygon boundary**.
There is no fractional boundary-cell allocation or area-weighted interpolation.

The displayed estimate is rounded to whole persons; it is still a model estimate.
Coverage is valid cells divided by selected raster cell centers, **not the
fraction of the AOI's physical area**. An AOI extending beyond the raster or
containing unsupported cells is reported as partial coverage, not an entire-AOI
total. No selected centers gives no evidence of zero population. Invalid/empty
geometry is rejected, not silently repaired.

When the selected run provides an artifact SHA-256, the tool checks the population
raster against it before summing. Legacy results without a saved fingerprint
carry an explicit integrity warning. The summary dialog displays the result;
it does not rewrite the raster or append an AOI total to the immutable run.

## Reproduce or diagnose a run

Keep `run_config.yaml`, `manifest.json`, inputs including GDAL sidecars, and the
runtime/source version information together. Input resources are fingerprinted
and rechecked before completion. The GUI launches a verified private **code**
snapshot in a separate job directory; replacing plugin files later does not
change that already-started child. This is not a copy/snapshot of all input data.
Direct engine CLI runs record `live_source` when no verified code snapshot is
supplied; the manifest distinguishes that origin explicitly.

Fixed seeds help repeat a given environment/input/validation design, but do not
promise bitwise equivalence across changed libraries, platforms or data. Recorded
effective defaults prevent silently adopting later defaults. The GUI does not
load/reuse model bundles; API reuse rejects incompatible environment/grid
contracts and accepts only trusted serialization. A compatible load is not a
scientific guarantee about transfer to another region.

For a failed run, read the final error in **Details** and inspect its manifest/log
before changing inputs. Positive-population zones without positive eligible
allocation weight fail; zero-population zones remain zero. Raster-only zones
without census records are excluded and diagnosed. Age-sex totals are conserved
per input group; their sum is compared with, not forcibly rescaled to, the main
census. Fix the underlying support/schema issue rather than treating missing
validation or a stopped run as success.

[Projects](projects.md) · [Input requirements](input-data.md) · [Settings](settings.md) · [Troubleshooting](troubleshooting.md)
