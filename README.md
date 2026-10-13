[![DOI](https://zenodo.org/badge/913350629.svg)](https://doi.org/10.5281/zenodo.14867059)

# QGIS pypopRF

Census-conserving population redistribution using geospatial covariates, Random
Forest and dasymetric mapping, with optional water/support masks and age-sex maps.

This checkout is the **0.3.0 workflow development build**, not a published
stable release. The [development guide](docs/development.md) describes the
architecture, regression checks and packaging. Local audit/experiment evidence
is deliberately not versioned or included in the plugin archive.

![WorldPop SDI](wp_logo.png)

## What changed

- A headless numerical engine runs in its own Python process, separate from QGIS.
- Every analysis has a new run directory, manifest, effective settings and input
  fingerprints. Source files and earlier results are not overwritten.
- Population sums are verified against each census zone and demographic group
  before a map is published. Invalid grids or unsupported positive-population
  zones fail explicitly.
- Windowed raster processing, bounded task submission, cooperative cancellation
  and owned-process cleanup replace whole-raster and GUI-thread processing.
- Default evaluation holds out spatial blocks and refits selection/preprocessing
  inside each fold. Conservation is not proof of pixel-level accuracy; validation
  limitations are described in the [settings guide](docs/user-guide/settings.md).
- A native-palette interface provides Project, Input data, Settings, Results and
  Details tabs, engine setup, run history and actionable status messages.
- Guided data preparation creates a new derived project with explicit grid,
  quantity/resampling choices and diagnostics, preserving the original sources.
- A quality dashboard distinguishes held-out zone-density validation from census
  conservation, with OOF plots, a fold-training baseline and error-zone centroids.
- Local QGIS layers can be selected as inputs; completed maps receive run groups,
  a population style and an explicit cell-centre area-of-interest summary tool.

## Installation

QGIS 3.44–4.x is the declared range. Genuine Windows AMD64 and Linux glibc x86_64
QGIS 3.44 / Qt 5 and QGIS 4.2 / Qt 6 are the local native acceptance targets.
macOS, ARM and musl are not qualified by this build.

The calculation engine requires an installed **64-bit CPython 3.12**. QGIS itself
may use a different Python version. Enabling the plugin does not install packages
into QGIS or download an interpreter.

1. Build a development ZIP: `python scripts/build_plugin.py` → `dist/pypopRF.zip`.
2. In QGIS: Plugins → Manage and Install Plugins → Install from ZIP.
3. Open pypopRF, choose Python 3.12 if needed, then set up the isolated engine.
4. Create/open a project and follow the [quick start](docs/getting-started/quickstart.md).

First-time setup downloads SHA-256-verified binary wheels from the packaged lock. Failed/cancelled updates
cannot replace a healthy engine. ZIP packaging excludes case-study data, tests,
developer environments and audit files. See [installation and updates](docs/getting-started/installation.md).

## Inputs and outputs

Required: a single-band aligned zone GeoTIFF, a census CSV with unique integer IDs
and nonnegative population, and at least one named aligned covariate GeoTIFF.
Optional: water mask (1 excludes), support constraint (1 includes), and age-sex
CSV. See the strict [input contract](docs/user-guide/input-data.md).

Each `output/runs/<id>/` contains a status manifest, full effective configuration,
SHA-256 provenance, model bundle, feature/CV artifacts and verified TIFF maps.
Final population maps contain **persons per pixel**. `prediction.tif` is an
allocation-weight surface, not a population map. Only completed runs are offered
for adding population layers to QGIS.

## Development and verification

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -m "not qgis" -q
.venv\Scripts\python -m ruff check core gui controllers services shared qgis_pypoprf.py __init__.py scripts tests
.venv\Scripts\python scripts/build_plugin.py
```

Use Python 3.12. Native QGIS tests require genuine bindings and a separate prepared
engine; CI exercises both Qt generations. [Development guide](docs/development.md)
documents those commands and the JSON-event headless CLI.

## Help and licensing

- [Documentation](https://wpgp.github.io/QGIS-pypopRF/) and [local guides](docs/index.md).
- [Issues](https://github.com/wpgp/QGIS-pypopRF/issues); attach the run manifest and
  logs without disclosing private census data.
- [WorldPop SDI](https://sdi.worldpop.org).

The repository contains [MIT LICENSE](LICENSE) and GPL notices in generated
QGIS-plugin files. Those notices are retained. Reconciling copyright provenance
and distribution licensing is a release gate; this build does not silently
relicense third-party/generated code or claim that the conflict is resolved.

## Citation

```bibtex
@software{QGIS-pypopRF,
  author = {Nosatiuk B., Priyatikanto R., Zhang W., McKeen T., Vataga E., Tejedor-Garavito N, Bondarenko M.},
  title = {QGIS-pypopRF: Population Prediction and Dasymetric Mapping Tool},
  publisher = {GitHub},
  url = {https://github.com/wpgp/QGIS-pypopRF}
}
```

## Development team

Developed by the WorldPop SDI Team:

- Borys Nosatiuk (b.nosatiuk@soton.ac.uk) — Project Lead
- Rhorom Priyatikanto (rhorom.priyatikanto@soton.ac.uk)
- Maksym Bondarenko (m.bondarenko@soton.ac.uk)
- Wenbin Zhang (wb.zhang@soton.ac.uk)
- Tom McKeen (t.l.mckeen@soton.ac.uk)
- Elena Vataga (e.vataga@soton.ac.uk)
- Natalia Tejedor Garavito (n.tejedor-garavito@soton.ac.uk)
