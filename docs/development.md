# Development

The plugin has two deliberately separate execution environments: the QGIS/Qt
adapter and a locked CPython 3.12 numerical engine. Keep scientific imports and
calculation inside the engine. Plugin activation must not run pip, add binary
packages to the QGIS path, or select another interpreter implicitly for host
installation.

## Architecture

```text
__init__.py, metadata.txt, qgis_pypoprf.py  QGIS plugin entrypoint
core/pypoprf/                            isolated numerical engine
  algorithms/                           extraction, RF and allocation
  config/, utils/                       engine validation and raster tasks
gui/
  dialogs/, forms/, widgets/             native Qt views and Designer form
  presenters/                           project, results and preparation views
controllers/                            owned asynchronous workflows
services/                               configuration, runtime and saved metadata
shared/                                 stdlib atomic/environment contracts
tests/
  engine/, services/, gui/               focused regression suites
  integration/, native/, packaging/     workflow, real QGIS and ZIP checks
scripts/                                build, test, translation and upload tools
docs/                                   maintained user/developer guides
.local/                                 ignored reports, experiments and legacy files
dist/                                   ignored generated plugin ZIPs
```

The required QGIS files remain at the plugin root. Internal modules are not
compatibility aliases: update their imports when developing against this layout.
The public engine commands remain `python -m core.pypoprf` and
`python -m core.pypoprf.tools`.

| Boundary | Rule |
| --- | --- |
| `core` | Numerical/geospatial computation; no Qt, GUI, controllers or provisioning services. |
| `gui` | Widgets, dialog composition, native layer presentation and desktop actions; no numerical imports. |
| `controllers` | Owned tasks and view coordination; no numerical imports. |
| `services` | Config files, runtime setup/process ownership and saved artifacts; no Qt or numerical imports. |
| `shared` | Standard library only; no engine, services or GUI dependencies. |

The main dialog composes project/input, result and preparation presenters rather
than mixing all tab behavior into one class. Dialogs and reusable widgets live
separately. Opening folders is a GUI desktop action, not a file-copy service.
Runtime provisioning uses the shared environment contract; importing that
contract does not start setup, mutate the parent environment or import numerical
libraries. `services/owned_process.py` implements platform process ownership;
`services/process_exit_guard.py` verifies actual Windows launch descendants.

QProcess stdout carries newline-delimited JSON progress/result events; stderr
carries diagnostics. A successful result requires normal exit, a matching
complete result event, a complete manifest and present contained result paths.
Progress alone never establishes successful completion. Native process/thread
completion determines when a controller can release its owned resources.

Before analysis or preparation starts, `services/engine_snapshot.py` freezes a
bounded, verified copy of engine/shared code, provenance resources and dependency
locks in the owned job cache. The child starts with `-I -B`, verifies the snapshot
manifest, exact file inventory and installed dependency versions before importing
the numerical engine, and uses an external job working directory. Replacing the
installed plugin cannot change that child's imports or recorded source hashes.
Analysis manifests distinguish `verified_snapshot` from direct CLI `live_source`
execution and retain the frozen-manifest digest. No snapshot is shared between
jobs or removed before the actual owned child exits.

Setup creates a venv at its permanent unique location. It does not move a venv
after creation. Installation accepts exact pinned requirements, uses binary
wheels, checks package consistency and native imports, and activates through a
small atomic pointer after health checks. A failed update preserves the previous
environment. Readiness and discovery belong in background workers as they run
subprocesses. Cancellation must reach those subprocess checks as well as setup.

## Engine development environment

Use an independent environment, not the QGIS interpreter:

```powershell
py -3.12 -m venv .venv-dev
.\.venv-dev\Scripts\python -m pip install -r requirements-dev.txt
.\.venv-dev\Scripts\python -m pytest -m "not qgis" -q
.\.venv-dev\Scripts\python -m ruff check core gui controllers services shared qgis_pypoprf.py __init__.py scripts tests
```

On Linux use an installed `python3.12`, then `.venv-dev/bin/python` for the
same commands. `requirements-dev.txt` includes the exact engine lock plus test
and lint tools. Dependency upgrades are a separate change: validate clean
installation and regression/artifact compatibility before replacing the lock.

For native development, build the plugin ZIP and install it into a dedicated
QGIS profile using its plugin manager. This avoids suggesting a hard-coded
profile directory or a module directory name containing a hyphen.

## Tests and acceptance

The headless suite tests production code with temporary GeoTIFF/CSV fixtures,
including keyed joins, NoData, alignment, singleton zones, population
conservation, target inversion, CV isolation, model reload, cancellation,
atomic failures and provenance. The bundled Rwanda test checks extraction and
416-zone allocation; it skips explicitly if the case-study data are absent.

Qt doubles exercise controller state and error paths; they do not validate
native Qt ownership or widget binding compatibility. Run
`tests/native/` in a genuine QGIS application/runtime with an
available separate engine. Offscreen container acceptance is useful, but it
does not replace an interactive operating-system smoke test. CI configuration
in `.github/workflows/test.yml` declares the actual current test matrix.

`scripts/run_native_tests.py` discovers all test modules in `tests/native/` by default;
this includes the original adapter, preparation/layer/AOI workflow and quality
widget tests plus isolated actual-installer replacement/recovery tests. Set
`PYPOPRF_TEST_PLUGIN_ROOT` to the freshly extracted plugin and
`PYPOPRF_TEST_PLUGIN_ZIP` to the same verified ZIP. On Windows,
`PYPOPRF_TEST_ENGINE` must name a standalone prepared engine, not the portable
QGIS host interpreter. The installer subprocess tests redirect home, cache,
profile and Qt INI settings into a nonce-owned temporary directory before any
settings write; they never use an existing desktop profile. They include a
Windows-only copied-DLL, normal-process-exit migration fixture, not forced DLL
unloading or manual deletion of a user installation.

Windows launcher termination is not itself proof that the redirected
Python child has exited: the adapter asynchronously checks held, birth-identified
Windows process handles before releasing metadata or deleting owned scratch.
Tracking failures remain explicit and do not falsely establish cleanup safety.

The extra tools protocol is
`python -m core.pypoprf.tools --request absolute-request.json --cancel-file marker`.
Schema1 requests choose `inspect`, `prepare` or `population_summary`; both progress
and final events carry an ownership nonce. Complete output requires an owned new
directory, fixed `report.json`, matching request ID and (for preparation) validated
`config.yaml`. GUI preparation additionally carries the inspected `expected_inputs`
fingerprint list. AOI summaries can bind a population map to its recorded artifact
SHA, and explain partial coverage separately. No tool imports QGIS into the engine
or numerical libraries into the QGIS host.

The research command compares predeclared candidates on identical spatial
outer folds and saves the predictions, source hashes and split provenance:

```powershell
python -m scripts.benchmark_models --output .local/benchmarks/new_comparison --trees 100 --spatial-grid 4 4
```

It requires a fresh output directory and does not change the production model.
Experiment results and qualification evidence belong under ignored `.local/`,
not in Git or the runtime ZIP. Do not turn an improvement on one block partition
into a pixel-accuracy guarantee. Old generated resources and historical
screenshots are archived locally; the live interface uses filesystem icons and
the maintained Designer form, not a PyQt5-only generated resources module.

`tests/packaging/test_architecture.py` checks import boundaries, canonical and
plugin-alias loading, and an extracted ZIP without repository paths. Tests,
maintained documentation, dependency locks, scripts and CI are project sources;
private audits/reviews, run outputs, caches, environments and experiments are not.
Commit a coherent tested stage with explicit paths; never force-add `.local/` or
`dist/`, and do not push without the owner's request.

## Numerical and lifecycle invariants

- Inputs are never rewritten by validation or replaced by output publication.
- Census joins are by unique ID; density support comes from eligible mastergrid pixels.
- Missing predictors remain distinct from numeric zero; errors propagate from every tile.
- A positive population without positive eligible prediction support fails explicitly.
- Every published population raster is read back and checked per zone.
- Every outer validation fit recomputes preprocessing and selection from training data only.
- Spatial grouping metadata states CRS, scale, centroid method and lack of buffers.
- Failed/cancelled attempts cannot become complete maps or remove earlier runs.
- Temporary files and process/thread resources belong to one run and are cleaned only after use ends.

Model bundles include feature order, target transform, version and training-grid
contracts. Treat joblib as trusted executable serialization; mismatched old
model/scaler pairs require retraining. Effective settings must be recorded using
`Settings.to_config()` rather than copying only explicit YAML fields.

## Packaging and contribution

```powershell
python scripts/build_plugin.py --output dist/pypopRF.zip
```

The builder uses an explicit runtime allowlist, deterministic ZIP metadata and
a hashed package manifest. User data, tests, benchmark outputs and local engine
environments do not belong in the distributable. `python -m scripts.plugin_upload` is an
explicit maintainer publishing command; normal builds and activation do not
upload anything.

When submitting a change, include the concrete before/after behaviour, meaningful
validation and material limits. Preserve unrelated user changes and historical
data. Keep source attribution, `CITATION.cff`, the repository
[LICENSE](https://github.com/wpgp/QGIS-pypopRF/blob/master/LICENSE) and individual
file notices intact. Report reproducible issues through
[GitHub Issues](https://github.com/wpgp/QGIS-pypopRF/issues).
