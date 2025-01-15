# src/pypoprf/utils/matplotlib_utils.py
import functools
from contextlib import contextmanager
import matplotlib
import matplotlib.pyplot as plt


@contextmanager
def non_interactive_backend():
    """Context manager for handling matplotlib in non-interactive mode.

    This ensures matplotlib uses a non-interactive backend and properly
    cleans up resources after plotting.

    Example:
        >>> with non_interactive_backend():
        ...     plt.figure()
        ...     plt.plot([1, 2, 3])
        ...     plt.savefig('plot.png')
    """
    # Store the current backend
    original_backend = matplotlib.get_backend()

    try:
        # Set Agg backend and turn off interactive mode
        matplotlib.use('Agg', force=True)
        plt.ioff()
        yield
    finally:
        # Clean up resources
        plt.close('all')
        # Restore original backend
        matplotlib.use(original_backend, force=True)


def with_non_interactive_matplotlib(func):
    """Decorator to ensure matplotlib runs in non-interactive mode.

    This decorator wraps functions that create matplotlib plots,
    ensuring they run in non-interactive mode and clean up properly.

    Example:
        >>> @with_non_interactive_matplotlib
        ... def create_plot():
        ...     plt.figure()
        ...     plt.plot([1, 2, 3])
        ...     plt.savefig('plot.png')
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with non_interactive_backend():
            return func(*args, **kwargs)

    return wrapper
