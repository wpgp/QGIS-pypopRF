# Rwanda historical case study

These files were already present in the repository. This passport describes
measured contents, not verified original provenance or a newly licensed dataset.
Original download URLs, release identifiers and per-layer redistribution licences
were not supplied. Filenames suggesting a source/year do not establish either.
Do not publish a standalone dataset download until its owner supplies that record.

`DATA_MANIFEST.json` records byte sizes and SHA-256 for the nine original files.
Input files were not changed by the modernization. The deterministic plugin ZIP
does not include this directory (the TIFFs alone exceed the plugin package limit).

## Measured contract

All seven covariates and the mastergrid are single-band GeoTIFFs, 2444 columns ×
2150 rows, CRS EPSG:4326, approximately 100 m nominal resolution. Their nearly
identical affine transforms differ by insignificant floating-point roundoff;
the actual engine performs pixel-relative alignment checks.

The mastergrid is int32 with declared NoData 8888. It contains 417 valid IDs,
whereas `RWA_2026.csv` has 416 census zones. Extra ID 0 occupies 114464 valid
mastergrid cells and has no census record: the engine excludes it and records
that exclusion, not invents a population. Census total is 14731895.0003.
Covariate coverage is not identical; valid masks are retained and unknown cells
are not automatically zero-valued predictors.

The test/benchmark target is **persons per eligible pixel**, not persons per
square kilometre; degree-based pixels do not supply a constant physical area.
See [the benchmark](../../BENCHMARK.md) for spatial folds, limits and results.

## Reproduction

Use the isolated Python 3.12 development environment from the repository root:

```text
python -m pytest tests/test_core_rwa.py -q
python scripts/benchmark_models.py --help
```

The production regression tests use independent per-zone sums and source hashes.
Tiny synthetic fixtures in `tests/test_pipeline.py` and `tests/test_cli.py`
have known zone/group totals and do not depend on distribution rights for this
historical example. Test-generated age-sex fractions are artificial and are
never presented as supplied demographic evidence.

TODO before dataset publication: original URLs, source terms, retrieval dates,
methodology/units/NoData meaning for every layer, and census release provenance.
