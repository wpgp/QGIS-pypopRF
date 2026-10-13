import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.pypoprf.utils.runtime import (
    CancelledError, CancellationToken, atomic_output, check_cancelled,
)


def test_cancellation_is_per_run_and_visible_across_threads():
    active = CancellationToken()
    other = CancellationToken()
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(active.cancel).result()
    assert active.cancelled
    with pytest.raises(CancelledError):
        active.check()
    other.check()
    check_cancelled()


def test_importing_lifecycle_helpers_does_not_load_qgis_or_numerical_stack():
    result = subprocess.run(
        [sys.executable, "-c", "import core.pypoprf.utils.runtime; import sys; "
         "assert not any(x in sys.modules for x in "
         "('qgis', 'rasterio', 'numpy', 'sklearn', 'pandas'))"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["exception", "cancel", "empty"])
def test_atomic_output_keeps_previous_artifact_on_failure(tmp_path, failure):
    target = tmp_path / "result.bin"
    target.write_bytes(b"previous trusted output")
    token = CancellationToken()
    with pytest.raises((RuntimeError, CancelledError)):
        with atomic_output(target, token) as staging:
            if failure != "empty":
                staging.write_bytes(b"unfinished")
            if failure == "exception":
                raise RuntimeError("injected write failure")
            if failure == "cancel":
                token.cancel()
    assert target.read_bytes() == b"previous trusted output"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_output_publishes_only_after_writer_finishes(tmp_path):
    target = tmp_path / "nested" / "result.bin"
    with atomic_output(target) as staging:
        staging.write_bytes(b"complete")
        assert not target.exists()
    assert target.read_bytes() == b"complete"
    assert list(target.parent.iterdir()) == [target]


def test_existing_raster_sidecar_is_never_silently_reused_or_removed(tmp_path):
    target = tmp_path / "result.tif"
    sidecar = tmp_path / "result.tif.msk"
    target.write_bytes(b"previous raster")
    sidecar.write_bytes(b"previous mask")
    with pytest.raises(ValueError, match="sidecars"):
        with atomic_output(target):
            pytest.fail("Must refuse before writing")
    assert target.read_bytes() == b"previous raster"
    assert sidecar.read_bytes() == b"previous mask"


def test_new_external_sidecars_abort_publication_and_clean_only_staging(tmp_path):
    from pathlib import Path

    target = tmp_path / "result.tif"
    with pytest.raises(ValueError, match="embedded"):
        with atomic_output(target) as staging:
            staging.write_bytes(b"raster")
            Path(str(staging) + ".msk").write_bytes(b"external mask")
    assert not target.exists()
    assert not list(tmp_path.iterdir())
