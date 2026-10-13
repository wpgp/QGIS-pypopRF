# Troubleshooting

Start with the status shown in the analysis window. Each attempt has its own
directory under `output/runs`; failed and cancelled attempts never replace a
previous completed result. Include the run's log and `manifest.json` when
reporting an issue. Avoid sending personal census data publicly.

## Engine setup

The interface does not need NumPy, pandas, rasterio or scikit-learn installed in
QGIS. Select a 64-bit CPython 3.12 executable and use Project → Set up engine.
QGIS 4 may use Python 3.13; that interpreter is not the calculation engine.
Setup uses a separate cache and exact packaged dependency lock. Check proxy,
network, free space and write permissions if package downloads fail. Setup output
is shown in Details. Do not run pip in the QGIS Python to work around the failure.
An earlier healthy engine remains active if a repair fails; an outdated lock
requires successful setup before the new plugin can run.

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

## Development diagnostics

Run `python -m pytest` in the development engine environment. Native QGIS tests
require genuine QGIS/Qt bindings and are marked `qgis`. Audit reproduction scripts
describe defects in the historical version and are not acceptance tests for the
updated implementation.
