# Development

The plugin has two deliberately separate execution environments: the QGIS/Qt
adapter and a locked CPython 3.12 numerical engine. Keep scientific imports and
calculation inside the engine. Plugin activation must not run pip, add binary
packages to the QGIS path, or select another interpreter implicitly for host
installation.

## Architecture

| Area | Responsibility |
| --- | --- |
| `__init__.py`, `qgis_pypoprf.py` | QGIS activation, toolbar action and dialog lifetime. |
| `qgis_pypoprf_dialog.py`, `.ui` | Project/input/settings/results/details interface. |
| `q_models/config_manager.py` | Project opening and atomic configuration updates. |
| `q_models/import_controller.py`, `file_handlers.py` | Background staged imports and collision protection. |
| `q_models/runtime_controller.py` | Background engine discovery, checks and setup. |
| `runtime_manager.py` | Permanent isolated venvs, exact dependency health and atomic activation pointer. |
| `q_models/process_executor.py` | Owned QProcess, JSON events, cancellation and terminal verification. |
| `q_models/result_manifest.py` | Bounded shared run-metadata/path validation for completion and history. |
| `q_models/tools_controller.py`, `preparation_dialog.py` | Owned JSON-request engine tools, guided preparation and AOI summary UI. |
| `q_models/quality_report.py`, `quality_panel.py` | Read-only hash/bounds-checked zonal diagnostics and native Qt plotting. |
| `q_models/layer_integration.py` | Safe local layer sources, result groups/styles and owned diagnostic centroids. |
| `q_models/process_exit_guard.py` | Read-only Windows launcher/descendant handle reaping before GUI cleanup. |
| `core/pypoprf/config/settings.py` | Read-only input/config validation and effective snapshots. |
| `core/pypoprf/pipeline.py`, `cli.py` | Shared headless workflow and structured process protocol. |
| `core/pypoprf/core/` | Feature extraction, RF validation/inference and conservative allocation. |
| `core/pypoprf/utils/` | Bounded raster tasks, cancellation and atomic artifact publication. |
| `core/pypoprf/tools.py`, `preparation.py`, `population_summary.py` | Safe derived projects and explicit cell-centre count estimates in the isolated engine. |

QProcess stdout carries newline-delimited JSON progress/result events; stderr
carries diagnostics. A successful result requires normal exit, a matching
complete result event, a complete manifest and present contained result paths.
Progress alone never establishes successful completion. Native process/thread
completion determines when a controller can release its owned resources.

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
.\.venv-dev\Scripts\python -m ruff check atomic_files.py core q_models qgis_pypoprf.py qgis_pypoprf_dialog.py __init__.py runtime_manager.py plugin_upload.py scripts tests
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
`tests/test_*native.py` in a genuine QGIS application/runtime with an
available separate engine. Offscreen container acceptance is useful, but it
does not replace an interactive operating-system smoke test. CI configuration
in `.github/workflows/test.yml` declares the actual current test matrix.

`scripts/run_native_tests.py` discovers all `test_*native.py` modules by default;
this includes the original adapter, preparation/layer/AOI workflow and quality
widget tests. Windows launcher termination is not itself proof that the redirected
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
python -m scripts.benchmark_models --output benchmarks/new_comparison --trees 100 --spatial-grid 4 4
```

It requires a fresh output directory and does not change the production model.
See the repository's `BENCHMARK.md` for measured results and limitations. Do
not turn an improvement on one block partition into a pixel-accuracy guarantee.

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
environments do not belong in the distributable. `plugin_upload.py` is an
explicit maintainer publishing command; normal builds and activation do not
upload anything.

When submitting a change, include the concrete before/after behaviour, meaningful
validation and material limits. Preserve unrelated user changes and historical
data. Keep source attribution, `CITATION.cff`, the repository
[LICENSE](https://github.com/wpgp/QGIS-pypopRF/blob/master/LICENSE) and individual
file notices intact. Report reproducible issues through
[GitHub Issues](https://github.com/wpgp/QGIS-pypopRF/issues).
