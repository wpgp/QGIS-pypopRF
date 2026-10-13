"""Entrypoint: python -m core.pypoprf --config project/config.yaml."""
import os

if __package__ == "core.pypoprf":
    from shared.runtime_environment import NATIVE_THREAD_LIMITS
else:
    from ...shared.runtime_environment import NATIVE_THREAD_LIMITS

# This is the dedicated CLI process, not a library import or the QGIS host.
# Set native pool limits before importing NumPy/scikit-learn; RF's configured
# private worker count remains independent and avoids nested oversubscription.
os.environ.update(NATIVE_THREAD_LIMITS)

from .cli import main

raise SystemExit(main())
