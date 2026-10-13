# Running and interpreting an analysis

## Before Start

The project, engine, mastergrid, census and named covariates must be ready. Full numerical validation happens in the isolated child process: CSV schema, finite values, raster alignment and eligible support. GUI readiness is not a substitute for this validation.

All rasters must share grid dimensions, CRS and affine geometry. The plugin does not automatically resample or reproject incompatible inputs. Preserve source NoData and validity masks.

Do not edit or regenerate project input files during import or analysis. Fingerprint
checks detect observed changes; they are not a point-in-time filesystem snapshot
against a separate process continuously replacing and restoring the same inputs.

## Processing and cancellation

The engine applies the water/constraint eligibility rules, extracts zonal covariate statistics, trains a deterministic Random Forest, predicts a nonnegative allocation surface, then redistributes each census zone's population over valid eligible pixels. Age-sex columns are joined by zone ID, never by row order.

Use **Stop** to request cooperative cancellation. The interface remains asynchronous and retains ownership of the child until it actually exits. If the child does not exit within the grace period, only that owned process is forcibly stopped. Closing or unloading follows the same ownership rule.

Files are published individually through temporary files and atomic replacement after successful close and validation. Cancellation can leave a partial run for diagnosis, but its manifest cannot be complete. Previous runs and source files are preserved. Progress is stage-based, not an accurate time estimate.

## Run products

Each run is under `output/runs/<timestamp-id>/`. Important files include:

- `manifest.json`: terminal status, effective engine source/version, input SHA-256 fingerprints, immutable artifact inventory, diagnostics and metrics.
- `run_config.yaml`: all effective settings, including defaults and resolved input paths.
- `prediction.tif`: model allocation weights; **not a population-count output**.
- `population_unconstrained.tif` and, when requested, `population_constrained.tif`: persons per pixel.
- `normalized_census*.tif`: zone normalization coefficients, not final population.
- `agesex/population_<group>*.tif`: independently conserved age-sex population maps.
- `model_bundle.pkl.gz`: one validated bundle with model, preprocessing and schema. Load only trusted bundles; pickle is not a safe interchange format.
- `cv_metrics.json`, `cv_predictions.csv`, `cv_zone_geometry.csv` and feature artifacts: inspect these to understand model evaluation.
- The configured log file, if enabled.

The manifest distinguishes raster outputs for display from the complete immutable artifact inventory. Input dataset resources, including external GDAL validity masks, are fingerprinted and rechecked before a run can be completed.

## Scientific limits

Per-zone conservation is a correctness check on redistribution, not an independent accuracy estimate. Training labels are zone population divided by eligible pixel count. A degree-based CRS does not turn that target into physical-area density.

Default spatial validation assigns zone centroids to a 4×4 grid over the valid mastergrid footprint and holds out blocks. It does not use a spatial buffer, prove independence, estimate pixel-level accuracy, or remove the modifiable areal unit problem. Too few occupied blocks makes validation unavailable; the engine does not silently fall back to a shuffled split.

User-supplied groups and shuffled-zone diagnostic validation are explicitly labelled. Feature selection and preprocessing are refitted inside each outer training fold. Changing block scale can change model rankings; use an explicitly chosen validation design rather than comparing scores from different splits as if they measured the same task.

Zones in the raster without census records are excluded and reported. A positive-population census zone without positive eligible allocation support fails the run. Zero-population zones remain zero. Age-sex totals are checked against each input group separately; the plugin does not infer that independently supplied groups sum to the main census.

Do not report prediction or aggregate cross-validation scores as validated high-resolution population accuracy without independent data and an appropriate spatial study design.
