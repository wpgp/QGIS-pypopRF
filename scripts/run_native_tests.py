"""Run acceptance inside a genuine QGIS Python, with test-only deps outside QGIS.

OSGeo4W wrappers reset PYTHONPATH. PYPOPRF_TEST_DEPS points at a disposable
pytest --target directory rather than installing pytest into the host runtime.
"""
import os
from pathlib import Path
import sys


def main():
    test_deps = os.environ.get("PYPOPRF_TEST_DEPS")
    if test_deps:
        path = Path(test_deps).resolve(strict=True)
        if not path.is_dir():
            raise ValueError("PYPOPRF_TEST_DEPS must be a directory")
        sys.path.insert(0, str(path))
    import pytest
    targets = sorted(str(path) for path in (Path(__file__).resolve().parents[1] / "tests" / "native").glob("test_*.py"))
    if not targets:
        raise ValueError("No native acceptance tests found")
    return pytest.main(sys.argv[1:] or [*targets, "-q", "-p", "no:cacheprovider"])


if __name__ == "__main__":
    raise SystemExit(main())
