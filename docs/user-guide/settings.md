# Settings

Settings are saved in the project's `config.yaml`. Opening a project restores
its existing configuration. Every analysis also saves `run_config.yaml` with
all effective defaults and canonical input paths, so a later default change
does not silently change the recorded settings of an earlier run.

## Controls in the Settings tab

| Control | New project default | Meaning |
| --- | --- | --- |
| Zone identifier | `id` | Exact CSV column name containing zone IDs. |
| Population total | `pop` | Exact CSV column containing nonnegative population totals. |
| Use multiple CPU cores | Off | Off uses one worker; on uses the selected worker count. |
| CPU cores | `1` in the saved new-project configuration | Shared worker budget for supported raster operations and RF fitting. |
| Process raster tiles in parallel | On | Enables tile processing for zonal extraction and allocation. |
| Tile size | `512,512` | Width and height in pixels; GUI choices are 256, 512 and 1024 square tiles. |
| Use log-transformed population density | On | Fits `log1p(density)` and converts predictions with `expm1`. |
| Feature selection threshold | `0.01` | Threshold for normalized holdout permutation importance. |
| Add population maps to QGIS | On | Adds verified population maps after successful completion. |
| Detail level | `INFO` | Selects the amount of diagnostic logging. |
| Log filename | `logs_pypoprf.log` | A plain `.log` filename, without directories or reserved device names. |

The target density is population divided by the number of eligible mastergrid
pixels in each census zone. It does not depend on the ordering of covariates.
It is not a value in people/km² unless a separate unit conversion is performed.

Feature importance is an increase in validation RMSE, normalized by the larger
of the training target standard deviation and mean absolute target. It is not
a probability or a cumulative share of features. If the threshold excludes
every useful feature, the best positive feature is retained. With no credible
positive ranking, a constant target or a very small training subset, all
features are retained. Selection is fitted within each outer training fold.

Both processing modes read bounded raster tiles. Disabling parallel tile
processing selects serial execution; it does not request a full-grid read.
Prediction also writes tiled windows. Worker count and tile dimensions affect
resource usage. Using every CPU does not necessarily improve speed. The owned
engine child caps native BLAS/OpenMP pools to one thread each, preventing an
extra native pool per RF worker. This does not change the configured RF worker
budget or the QGIS host's environment; the run manifest records loaded native
pool counts.

## Advanced configuration

The following fields are supported in `config.yaml` but do not currently have
dedicated GUI controls. Close the dialog before editing the file, then reopen
the project to avoid competing writes.

```yaml
random_seed: 42
n_estimators: 500
cv_folds: 5
cv_strategy: spatial
spatial_grid: [4, 4]
cv_group_column: null
```

`spatial_grid` contains the number of columns and rows of spatial blocks over
the full mastergrid footprint. It is a subdivision count, not a distance in
metres. Valid-pixel zone centroids determine block membership. All zones in a
block remain together in external cross-validation; scaler, selection and
forest are refitted on training data only.

The default `spatial` strategy records CRS, pixel/native-unit block dimensions,
centroids and limitations. It uses no separation buffer. Large zones can cross
the boundaries of their centroid's block, and adjacent blocks can contain
dependent observations. Choose the subdivision scale for the study rather
than interpreting the default as an estimated autocorrelation distance.

`groups` uses a nonmissing census `cv_group_column` or groups supplied to the
Python API. Supplied groups are kept together but are not automatically called
spatial validation. `shuffled_zone` is an explicitly labelled diagnostic split
which ignores spatial dependence. When spatial CV has fewer than two occupied
blocks, or a training zone has no eligible centroid, metrics are unavailable
with an explanation; there is no automatic random fallback.

The run's `cv_metrics.json`, `cv_predictions.csv` and `cv_zone_geometry.csv`
record the actual validation. Scores describe held-out zone-average density,
not independent fine-pixel accuracy. The repository's `BENCHMARK.md` records
the fixed-fold Rwanda comparison and its limits.

## Paths, logs and model files

`data_dir` and `output_dir` are resolved against `work_dir`; absolute paths are
also supported. The GUI creates each run beneath `<output_dir>/runs/<run_id>/`.
Earlier runs are preserved.

The GUI has a separate diagnostic logger. The engine writes its log into the
current run. Logs append and rotate rather than truncating previous content.
The headless configuration accepts `logging.file: null` to disable engine file
logging; the GUI currently expects a filename.

The fitted model, scaler, feature order, target transform, versions and training
pixel-geometry contract are saved together in `model_bundle.pkl.gz`. The GUI
does not offer model reuse or import. The Python API rejects legacy standalone
model/scaler pairs and incompatible bundle environments or grids; retraining
is required. Joblib bundles are executable Python serialization and must only
be loaded from trusted sources.

[Run an analysis](running-analysis.md) · [Input requirements](input-data.md)
