# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.6] - Unreleased

### Fixed

- Validate census identifier spelling before floating-point parsing; reject
  fractional/out-of-range IDs instead of silently assigning a different zone.
  Preserve exact numeric API values and apply the same boundary to preparation,
  age-sex tables, feature extraction, validation and allocation.
- Verify source and staged-file hashes for every new copied input, not only
  filename conflicts. Refuse changed/mixed copies without publishing a destination.
- Treat manually typed input paths as drafts until committed; keep browse choices
  immediate. Prevent stale input clears from mutating an inactive previous project
  and detach owned edit callbacks before Qt child teardown. Keep input Enter and
  Run-with-draft confirmation separate from analysis and cancellation actions.
- Use shorter unique permanent engine directory names to reduce Windows path-length
  failures, retaining full UUID ownership and verified legacy environment reuse.
- Refuse aliased, shared or replaced configuration/setup lock files before writing
  their lock byte; preserve foreign files and existing locking behavior.
- Write portable relative run output paths and accept contained legacy Windows
  separators when reopening moved results; retain drive/traversal protections.
- Exclude inaccessible stale Windows process candidates only with proven foreign
  creation times. Keep real exit checks for retained children and fail closed
  when ownership/reaping cannot be established.

## [0.3.5] - Unreleased

### Fixed

- Distinguish a selected folder from an active project. Show Project open and
  disable repeated activation after success; keep an explicit active-path caption.
- Keep the active project on repeated same-path selection and prevent duplicate
  open calls from reloading settings or reopening log handlers. Restore correct
  project action state after owned work completes.
- Keep project activation unavailable after a late initialization failure instead
  of showing a false Project open state.

### Documentation

- Expand the first-run guide and project lifecycle/backups guide, modernize the
  documentation index and navigation, and document current input/import,
  processing, results and recovery workflows with native synthetic screenshots.

## [0.3.4] - Unreleased

### Changed

- Use one plugin-owned white/light color scheme independent of QGIS palette and
  application stylesheet, including preparation, About, import conflict and
  population-summary dialogs. Keep host and unrelated windows unchanged.
- Use consistent blue selections/actions, readable disabled/error states and
  packaged vector control indicators without changing fonts or display scaling.

### Fixed

- Keep the footer checklist caption and full readiness labels readable at 720px
  with larger native fonts; separate the caption from compact navigation chips.

## [0.3.3] - Unreleased

### Changed

- Separate Engine page from project-folder selection, with explicit discovery,
  selection, preparation, readiness and recoverable failure states.
- Replace routine ready-engine installation controls with a contextual next step;
  keep repair and manual selection under advanced maintenance.
- Group readiness, elapsed task status and a prominent run/cancel action below
  every tab. Preserve controller-owned action gates and scientific validation.
- Use scoped native-palette cards and actions, retaining project branding,
  About/citation and diagnostic history.

### Fixed

- Drop obsolete discovered Python choices after a successful empty refresh;
  retain them after failed or cancelled discovery.
- Distinguish verified manual interpreter selection from an unprobed path and
  from a prepared engine; invalidate selection verification on edits.

## [0.3.2] - Unreleased

### Added

- Optional guided Home screen with packaged logo, live next steps and nonmodal
  About/citation with explicit safe web links.
- Verified compatible-Python list and asynchronous manual selection checks;
  actionable engine errors beside controls and in task status.
- Worker-verified import reuse/separate-copy/cancel choices, preserving originals
  and rechecking changes before publication or registration.
- Elapsed task/stage history, indeterminate package-download progress and
  diagnostic messages retained across project and calculation transitions.

## [0.3.1] - Unreleased

### Fixed

- Freeze verified engine source and dependency contracts outside the installed
  plugin before launching an isolated child; record frozen-source provenance.
- Keep asynchronous cancellation/disposal owned by the living Qt dialog after
  QGIS removes the plugin instance. Close owned settings callbacks before hiding
  or destroying widgets, preventing the reproduced Qt 5 teardown crash.
- Restore public engine exports after the package-layout refactor.
- Refuse project/preparation locations inside plugin and engine/job-cache folders
  before activation or data creation; keep existing files and projects untouched.
- Recheck current configured paths before imports and logging; reject redirected
  GUI logs and linked log-file targets before opening or switching a file handler.

### Changed

- Add compact readiness navigation, bounded plain task status separate from numeric
  progress, and persistent run selection with success-only new-result selection.
- Document normal ZIP replacement and one-time legacy Windows DLL migration;
  include illustrated README guides and their exact assets in the verified ZIP.
- Qualify real installer replacement, owned-child cleanup and legacy migration
  in isolated native-QGIS test profiles, without claiming arbitrary ZIP rollback.

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
