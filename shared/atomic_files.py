"""Atomic single-file publication with bounded Windows sharing-error retries."""
import errno
import os
import time


_IS_WINDOWS = os.name == "nt"
_RETRY_DELAYS = (0.02, 0.04, 0.08, 0.16, 0.32)


def atomic_replace(source, target, cancellation_check=None):
    """Replace without removing the old target or suppressing permanent errors.

    Windows antivirus/indexers and concurrent readers can briefly hold a file
    without delete sharing. Retry only those access/sharing errors, at most six
    attempts and 0.62 seconds of backoff. The caller owns staging-file cleanup.
    Cancellation is checked before each attempt and after each backoff; once
    replacement succeeds, publication is committed and no cancellation is raised.
    """
    for attempt in range(len(_RETRY_DELAYS) + 1):
        if cancellation_check is not None:
            cancellation_check()
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            sharing_error = (getattr(exc, "winerror", None) in {5, 32, 33}
                             or exc.errno in {errno.EACCES, errno.EPERM})
            if not _IS_WINDOWS or not sharing_error or attempt == len(_RETRY_DELAYS):
                raise
            time.sleep(_RETRY_DELAYS[attempt])
            if cancellation_check is not None:
                cancellation_check()
