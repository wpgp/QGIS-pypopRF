# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - Unreleased

### Added

- Safe preparation tools and a guided workflow for census polygons/CSV, explicit
  reference grids, data diagnostics and new derived projects without input overwrite.
- A quality dashboard for held-out zone-density predictions, fold-training mean
  baseline, feature importance, validation limitations and error-centroid mapping.
- QGIS-native local layer selection, grouped/styled population results and an
  explicit cell-centre AOI population summary with coverage/NoData reporting.

The development guide documents the checks and execution boundaries. This
unpublished build does not claim calibrated pixel uncertainty or new platforms.

### Changed

- Separate native views, controllers, configuration/runtime services and
  lightweight shared contracts; keep the numerical engine independent of QGIS.
- Organize regression tests by area and keep local audit/experiment artifacts
  outside the versioned project and runtime archive.

## [0.2.0] - Unreleased modernization baseline

### Changed

- Run calculations in an isolated, locked CPython 3.12 engine; no pip or numerical
  library injection into QGIS Python when enabling the plugin.
- Refresh native-palette UI with engine setup, readiness, independent run history,
  accessible controls and bounded plain-text diagnostics; support Qt 5 and Qt 6.
- Default to spatial-block validation with fold-local preprocessing and feature
  selection, explicit target units and recorded split geometry.
- Store a single schema/version/grid-aware model bundle; legacy pairs need retraining.

### Fixed

- Join census/age-sex by ID, validate finite unique IDs, honor GDAL validity masks,
  enforce raster alignment, and make target support independent of covariate order.
- Correct log1p/expm1 inversion, propagate worker errors, preserve singleton and
  zero-population zones, verify actual per-zone population sums before publication.
- Replace destructive rerun/age-sex cleanup with new run directories and atomic
  output publication; preserve original CSVs, source files and previous results.
- Make cancellation asynchronous with scoped owned-process/thread cleanup,
  immutable input fingerprints and explicit failed/cancelled terminal states.

### Added

- Headless JSON-event CLI, full effective settings snapshot, input/artifact SHA-256
  provenance, deterministic ZIP builder, Windows/Linux regression and native QGIS tests.
- Runtime update verification/rollback, lock exclusivity and exact dependency checks.
- Maintained regression tests and documented native-QGIS qualification workflows.

Verification commands are described in docs/development.md. No external release has
been published; platform and licensing release gates must not be inferred closed.

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
