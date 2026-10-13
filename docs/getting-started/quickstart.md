# Quick start

1. [Install](installation.md) the development ZIP and prepare its separate calculation engine.
2. Choose a new working directory on **Project** and create the project. To inspect an existing project, open its directory; opening does not rewrite its configuration.
3. On **Input data**, select a mastergrid, population census CSV and at least one named covariate. Imports are staged and cancellable; a destination collision is not silently overwritten.
4. On **Settings**, enter the census ID and population column names exactly as written in the CSV. Choose conservative worker and tile sizes for the available memory.
5. Optionally select a water mask, constraint raster and age-sex census. Check the [input contract](../user-guide/input-data.md) first.
6. Start analysis. Watch the stage indicator and **Details**. Validation failures are errors, not completed results.
7. In **Results**, select a completed run and add its verified population maps to QGIS.

If your inputs are not aligned, use **Input data → Prepare / align inputs…**
instead of manually copying incompatible rasters. Choose a reference grid and
either census polygons or an existing zone grid, map the CSV columns, and declare
each predictor's measurement/resampling. Check compatibility, review the human
summary and warnings, then create a new prepared project. **Open prepared project**
is a separate confirmation; your previous project remains unchanged. If source
files change after inspection, recheck them before preparing.

After the run, the quality panel shows held-out zonal diagnostics and limitations.
Use **Show selected / top error zones in QGIS** for diagnostic centroids and
**Population in an area…** for an explicit cell-centre AOI estimate. See
[Interface](../user-guide/interface.md) for coverage and boundary caveats.

A project contains `config.yaml`, imported data under `data/`, and independent run directories under `output/runs/`. Each run stores its own effective configuration, input fingerprints, model/validation artifacts and status manifest. Re-running does not replace an earlier result.

Only a run whose manifest says `complete`, whose calculation process exited successfully, and whose returned outputs match the manifest is accepted as completed. Cancelled or failed runs may contain diagnostic artifacts; those are not final population products.

Population TIFF values are **persons per pixel**, not probabilities or persons per square kilometre. Their per-zone sums are checked against the census. The prediction surface is only a model-derived allocation weight. Conservation of census totals does not prove the within-zone distribution is accurate.

Default validation uses held-out spatial blocks with preprocessing and feature selection fitted separately within each training fold. Read `cv_metrics.json` and the scientific limitations in [running analysis](../user-guide/running-analysis.md), not just the completion message.

Next: [Interface](../user-guide/interface.md).
