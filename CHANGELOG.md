# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.7] - 2026-10-15

This modernization consolidates the unpublished 0.2.0–0.3.7 development stages.
Publication to GitHub and the QGIS plugin repository is a separate maintainer
action; building this source does not publish a release.

### Added

- Guided Home with project identity, logo, About/citation and contextual next steps.
- Separate Engine page with compatible Python discovery, actionable inline errors,
  explicit preparation/readiness and advanced maintenance.
- Guided input preparation for census polygons/CSV, explicit reference grids,
  quantity/resampling choices and diagnostics in a new derived project.
- Per-run history, effective settings, input/artifact hashes, model bundles and
  source provenance; earlier results and original inputs are preserved.
- Held-out zone-density quality dashboard, fold-training baseline, feature
  importance and error-zone centroids, with explicit validation limitations.
- QGIS layer inputs, grouped/styled result maps and cell-centre area summaries
  with coverage and NoData reporting.
- Illustrated installation, updates, first-run, project, input and recovery guides.
- Deterministic ZIP builder, hashed package manifest, headless JSON-event CLI and
  maintained Windows/Linux headless and genuine QGIS Qt 5/Qt 6 tests.

### Changed

- Calculations run in a separate hash-locked 64-bit CPython 3.12 environment.
  Activation never installs packages or injects numerical libraries into QGIS.
- Each job uses a verified source snapshot outside the plugin directory, allowing
  normal ZIP replacement without loading the engine's DLLs into QGIS. Legacy
  Windows DLL installations have a documented one-time restart migration.
- One plugin-owned light color scheme remains independent of QGIS's theme.
  Readiness, elapsed task status and a prominent Run/Stop action stay below tabs.
- Folder selection is distinct from successful project activation; duplicate
  opens do not reload settings or logging. Manual input paths remain drafts
  until committed. Import conflicts offer verified reuse or a separate copy.
- Default model evaluation uses spatial blocks with fold-local preprocessing and
  feature selection. Complete model bundles record schema, grid and target units;
  incompatible legacy model/scaler pairs require retraining.
- Native views, controllers, runtime/configuration services and lightweight shared
  contracts are separated from the independent numerical engine.

### Fixed

- Exact census IDs and keyed age-sex joins; finite/unique ID validation, GDAL
  validity masks, raster alignment and covariate-order-independent target support.
- Correct target-transform inversion, propagated worker failures, singleton and
  zero-population zones, and read-back per-zone conservation before publication.
- New run directories and atomic output publication replace destructive reruns.
  Failed/cancelled work cannot become complete results or remove earlier runs.
- Verified source/staged hashes and role headers before copied-input publication;
  failed configuration writes cannot leave phantom covariate rows.
- Strict private-engine configuration, protected setup locks, shorter unique
  Windows engine paths and failed-update preservation of a healthy environment.
- Asynchronous task cancellation, scoped owned-process cleanup and safe plugin
  unload; rejected/failed preparation starts restore controls and allow retry.
- Damaged runs remain visible as Invalid diagnostics without map/quality actions.
  Contained legacy Windows output paths and available fingerprints remain readable.
- Bounded logical CSV-header decoding, stale-project diagnostic cleanup and truthful
  warnings about retained potentially incomplete preparation directories.
- Early actionable age-sex ID-column errors and missing/extra zone diagnostics;
  different identifier systems are never silently joined by row position.
- Package verification rejects aliased/nonportable archive members, inconsistent
  manifest identity and excessive expanded payloads before publication.

### Compatibility and limits

- Declared QGIS range: 3.44–4.x. Native qualification targets Windows AMD64 and
  Linux glibc x86_64, QGIS 3.44 / Qt 5 and QGIS 4.2 / Qt 6.
- The separate engine requires installed 64-bit CPython 3.12 and network access
  for initial setup. macOS, ARM and musl are not qualified.
- Census conservation does not establish pixel-level accuracy; held-out scores
  describe zone-average density, not calibrated pixel uncertainty.
- Repository LICENSE and existing file-specific copyright/license notices are
  retained without relicensing. See [README](README.md#help-and-licensing).

Verification and release commands are described in [Development](docs/development.md).

## [0.1.1] - 2025-04-02

### Added
- Logarithmic scale option for improved population density modeling
- Configurable selection threshold for feature importance (CCS Limit)

### Changed
- Optimized configuration updates to only log actual changes
- Improved plugin cleanup when restarting
- Enhanced UI layout in Settings tab

### Fixed
- Bug with PredictionWorker parameters
- Issues with model parameter passing for logarithmic transformations

## [0.1.0] - 2024-02-13

First release of the QGIS pypopRF Plugin.

### Added
- Create high-resolution population maps from census data
- Use building data and other geospatial covariates as predictive variables
- Automated machine learning workflow with Random Forest
- Support for age-sex population structure mapping
- Parallel processing for large datasets
- Real-time progress monitoring and logging
- Integration with QGIS layer system
- Support for constraining layers and water masks
- Detailed processing logs and model statistics
- Feature importance analysis
- Support for QGIS 3.0+
- Python 3.9 - 3.12 compatibility

### Dependencies
- numpy==1.26.4
- rasterio==1.4.3
- geopandas==1.0.1
- scikit-learn==1.4.2

### Documentation
- Installation instructions
- User guide with interface description
- Input data requirements
- Settings configuration guide
- Running analysis documentation
