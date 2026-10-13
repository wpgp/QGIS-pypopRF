"""Run-local lifecycle primitives shared by the CLI and QGIS adapters."""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from threading import Event

if __package__ == "core.pypoprf.utils":
    from atomic_files import atomic_replace
else:
    from ....atomic_files import atomic_replace


class CancelledError(RuntimeError):
    """The caller requested cooperative cancellation of the current run."""


class CancellationToken:
    """Thread-safe cancellation with no Qt or process-wide state.

    A token belongs to one run. Check it before expensive operations and between
    raster windows. Cancellation never removes files while an operation uses them.
    """

    def __init__(self):
        self._event = Event()

    @property
    def cancelled(self):
        return self._event.is_set()

    def cancel(self):
        self._event.set()

    def check(self):
        if self.cancelled:
            raise CancelledError("Analysis cancelled by user")


def check_cancelled(token=None):
    """Check an optional token, keeping the standalone API convenient."""
    if token is not None:
        token.check()


@contextmanager
def atomic_output(target, cancellation_token=None):
    """Publish a completed single-file artifact from a sibling temporary path.

    The caller closes all writers before leaving the context. On error or
    cancellation, an existing target remains untouched. Formats with external
    sidecars must embed those resources or use a run-directory transaction.
    """
    check_cancelled(cancellation_token)
    target = Path(target)
    sidecar_suffixes = (".msk", ".aux.xml", ".ovr")
    if any(Path(str(target) + suffix).exists() for suffix in sidecar_suffixes):
        raise ValueError(f"Cannot replace {target.name} with existing external sidecars; use a fresh run")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=f".partial{target.suffix}", dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        check_cancelled(cancellation_token)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"No completed output was written for {target.name}")
        if any(Path(str(temporary) + suffix).exists() for suffix in sidecar_suffixes):
            raise ValueError("Atomic output requires embedded resources, not external sidecars")
        atomic_replace(temporary, target, lambda: check_cancelled(cancellation_token))
    finally:
        temporary.unlink(missing_ok=True)
        # These exact paths were generated for this unique owned staging file.
        for suffix in sidecar_suffixes:
            Path(str(temporary) + suffix).unlink(missing_ok=True)
