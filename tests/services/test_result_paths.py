"""Run output paths remain portable without permitting escapes or drive paths."""
import pytest

from services.result_manifest import population_paths


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_legacy_and_portable_age_output_paths_find_same_contained_file(tmp_path, separator):
    target = tmp_path / "agesex" / "population_f0.tif"
    target.parent.mkdir()
    target.write_bytes(b"owned-test-map")
    manifest = {"status": "complete", "outputs": [f"agesex{separator}population_f0.tif"]}
    assert population_paths(tmp_path, manifest) == [target.resolve()]


@pytest.mark.parametrize("name", ["../outside.tif", "..\\outside.tif", "/outside.tif",
                                 "C:/outside.tif", "C:\\outside.tif", "C:outside.tif",
                                 "\\\\server\\share\\outside.tif"])
def test_portable_reader_still_rejects_outside_and_windows_drive_paths(tmp_path, name):
    root = tmp_path / "run"
    root.mkdir()
    (tmp_path / "outside.tif").write_bytes(b"must-not-load")
    with pytest.raises(ValueError):
        population_paths(root, {"status": "complete", "outputs": [name]})


def test_portable_reader_keeps_prediction_exclusion_and_terminal_contract(tmp_path):
    prediction, population = tmp_path / "prediction.tif", tmp_path / "population_unconstrained.tif"
    for path in (prediction, population):
        path.write_bytes(b"owned-test-map")
    outputs = [path.name for path in (prediction, population)]
    assert population_paths(tmp_path, {"status": "complete", "outputs": outputs}) == [population.resolve()]
    assert population_paths(tmp_path, {"status": "cancelled", "outputs": outputs}) == []
