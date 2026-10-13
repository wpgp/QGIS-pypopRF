import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def _load(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "bootstrap_test_plugin", root / "__init__.py", submodule_search_locations=[str(root)],
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_activation_uses_host_without_pythonhome_pip_or_path_injection(monkeypatch):
    import subprocess

    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.setattr(subprocess, "check_call", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Activation must not install packages")))
    plugin = _load(monkeypatch)
    child = ModuleType("bootstrap_test_plugin.qgis_pypoprf")
    iface = object()
    child.PyPopRF = lambda received: (received, "loaded")
    monkeypatch.setitem(sys.modules, child.__name__, child)
    original_path = list(sys.path)
    assert plugin.classFactory(iface) == (iface, "loaded")
    assert sys.path == original_path
