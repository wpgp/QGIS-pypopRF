# Input data

An analysis needs one zone grid, a population CSV and at least one numeric
raster covariate. Optional inputs are a water mask, a population-support mask
and an age/sex CSV. Validation reads inputs and does not rename their columns
or rewrite source CSV files.

## Raster grid contract

Use single-band GeoTIFFs with a defined CRS. Mastergrid, covariates and optional
masks must have the same CRS, dimensions and complete affine pixel transform:
pixel size, origin and rotation all matter. A shifted grid is rejected even if
its dimensions match. Small floating-point transform roundoff is tolerated;
the engine does not automatically reproject or resample inputs.

For a new GUI import, use a self-contained GeoTIFF. Imports with external mask
or georeferencing sidecars such as `.msk`, `.aux.xml`, `.tfw`, `.tifw`, `.wld`
or `.prj` are rejected with export guidance rather than silently losing those
resources. A complete dataset already inside the project's data directory can
be selected in place, keeping its sidecars. The headless engine records GDAL's
input resource list, including available sidecars, in run provenance.

NoData and GDAL valid-data masks are respected. Ordinary numeric zero is valid
unless the raster declares it NoData. Mark missing data correctly rather than
using a finite sentinel as an undeclared measurement.

## Zone grid

Each valid pixel contains the integer ID of its census zone. An ID occurs in
many pixels; pixel values do not have to be globally unique. Gaps outside the
study area are allowed when marked NoData. IDs must match the population CSV.
IDs must be exactly representable integers within the supported numeric range
(absolute value no greater than `2**53`).

Every training census zone needs eligible grid pixels and a finite mean for
each configured covariate. Zones without that support are reported as errors,
including zones whose population is zero. Extra grid IDs without census totals
are excluded from population outputs and recorded in diagnostics.

## Population CSV

Use a CSV with unique, nonempty headers. Map the ID and population columns in
Settings; names are case-sensitive and must differ. For example:

| id | pop |
| ---: | ---: |
| 1 | 2500 |
| 2 | 3200 |
| 3 | 0 |

IDs must be unique, finite integers. Population totals must be numeric, finite
and nonnegative; zero and fractional totals are accepted. Empty tables,
duplicate IDs and missing values fail validation. Rows can appear in any order:
joins and output checks use zone IDs rather than row positions.

Additional columns are not automatically used as predictors. A nonmissing
group column may be retained for explicitly configured grouped validation.
Avoid derived column names such as `dens`, `eligible_pixel_count` and names
used for covariate statistics. A population column named `sum` is supported
without changing the source file.

## Covariates

Provide aligned single-band numeric rasters. The model trains on each
covariate's valid-pixel mean within a zone and predicts from selected covariate
values at individual pixels. Pixels lacking any selected predictor receive
NoData predictions; they are not filled with arbitrary sentinel values.

Continuous measurements, distances, counts and meaningful binary indicators
can be used. Categorical class codes are not encoded automatically: averaging
arbitrary land-use codes is not meaningful. Derive appropriate indicators or
other numeric representations before supplying categorical information.

Missing covariates can reduce allocation support. A zone with positive
population and no positive eligible prediction weight fails instead of losing
its population silently. Confirm that the remaining support is appropriate
for the study; conserved totals alone do not validate its geographic coverage.

## Optional masks

The water mask is binary: **1 excludes** a pixel and **0 retains** it. Masked or
NoData mask pixels are also excluded.

The population-support mask is binary: **1 includes** a pixel and **0 excludes**
it from constrained allocation. NoData support pixels are excluded. The engine
creates a temporary constrained zone-ID grid while preserving the original
zone identifiers. Do not supply a second, unrelated administrative-ID raster
as the GUI population-support mask.

An unconstrained population map is always produced. When a support mask is
provided, a separate constrained map is produced and checked against the same
census totals. The source masks and mastergrid are not modified.

## Age and sex CSV

Use the configured ID column and the same unique zone-ID set as the main
population CSV. Group columns must match the supported complete naming pattern,
for example `f0`, `m0`, `f_0_4`, `m_5_9`, `f65+` or `m65+`. Names are matched
case-insensitively; ambiguous duplicate group names are rejected. Unrelated
metadata columns are ignored.

Each group contains finite nonnegative totals and is joined by ID. Every group
map is checked against that group's supplied totals. The engine does not
require the sum of all group columns to equal the main population total. It
records a keyed comparison in `agesex/age_sex_totals.csv` and a bounded mismatch
summary in the run manifest. Check that consistency if the columns form a
complete demographic partition: a mismatch is diagnostic, not forced rescaling
or a hard error. Different row order does not change which zone receives a group.

## Import behaviour

### Guided preparation

The preparation wizard creates a separate new project. Its reference raster is
a **grid template** (CRS, extent, transform and dimensions), not an implicit
study-area mask. Zone validity comes from the original zone raster or explicitly
chosen census polygons. The tool does not silently clip a whole census polygon
to a smaller reference extent and allocate its full population into the remnant.

Choose predictor quantity and resampling explicitly (1–32 covariates in this
guided preparation version):

- **Continuous**: nearest, bilinear or average alignment. The choice changes
  predictor values and must be appropriate for the measurement.
- **Binary indicator / mask**: checked 0/1 values with nearest-neighbour alignment.
  Multiclass category codes must first be encoded as meaningful indicators;
  averaging arbitrary class numbers is not supported.
- **Count**: already-aligned nearest passthrough only. Changing cell size or CRS
  requires a separately justified conservative aggregation method; this wizard
  refuses to pretend ordinary interpolation preserves counts.

The derived GeoTIFFs embed the source validity in NaN NoData. Original GDAL
resources, CSV and vector resources are fingerprinted, rechecked, and retained
unchanged. Diagnostics include zone-ID matching, grid changes, missing support,
joint predictor coverage, warnings and a full coverage CSV. Review the report
before committing preparation. Unsupported or invalid data are not automatically
repaired. Census vectors and tables are materialized and must fit engine memory;
this is not a streaming vector ETL pipeline. Geographic coordinates and spans
that require antimeridian splitting are refused before or after reprojection.
Split/export them explicitly; the wizard does not guess a dateline repair.
The GUI binds preparation to the inspected source hashes. A changed CSV, raster
or sidecar requires a new compatibility check, not reuse of the old confirmation.

Existing project files with external masks can be prepared into self-contained
GeoTIFFs; direct GUI copy still rejects sidecars to avoid losing them. The prepared
project includes a compatible `config.yaml`, derived data, report and provenance.

Age-sex inputs are added after opening the prepared project; this first wizard
does not automatically copy a previously configured age-sex table. The original
project retains it. Preparation is deliberately conservative: lack of jointly
valid predictor support is diagnosed rather than resolved by implicit imputation.

### Direct file import

New files are copied in cancellable background jobs into the project's data
directory. Existing destination names are never overwritten; select an existing
project file in place or rename the new source before importing it. Incomplete
copies are staged and are not registered as inputs. Removing a covariate from
the table removes its configuration entry, not the physical input file.

[Settings](settings.md) · [Interface](interface.md)
