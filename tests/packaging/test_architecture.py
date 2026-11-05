"""Dependency boundaries and installed-layout checks, independent of Qt mocks."""
import ast
from importlib.util import resolve_name
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from scripts.build_plugin import PUBLIC_DOCUMENTATION, build_plugin, package_files, verify_package

ROOT = Path(__file__).resolve().parents[2]
SCIENTIFIC = {"numpy", "pandas", "scipy", "sklearn", "rasterio", "geopandas", "shapely",
              "joblib", "osgeo", "fiona", "pyogrio", "pyproj", "threadpoolctl", "numexpr",
              "matplotlib", "torch", "xgboost"}
QT = {"qgis", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy"}
HOST_DIRECTORIES = ("gui", "controllers", "services", "shared")


def imported_modules(source, relative_path):
    """Resolve relative imports as well as literal dynamic import requests.

    Child-process probe source strings are deliberately not traversed: importing
    scientific packages *in the separate engine* is a supported service contract.
    """
    package = Path(relative_path).parent.parts
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = package[:len(package) - node.level + 1]
                module = ".".join((*prefix, *(node.module or "").split("."))).rstrip(".")
            else:
                module = node.module or ""
            imports.append(module)
            imports.extend(f"{module}.{alias.name}".lstrip(".") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            target = node.func
            dynamic = (isinstance(target, ast.Name) and target.id == "__import__") or (
                isinstance(target, ast.Attribute) and target.attr == "import_module")
            if dynamic and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                imports.append(node.args[0].value.lstrip("."))
    return imports


def python_files(directory):
    return sorted(path for path in (ROOT / directory).rglob("*.py")
                  if "__pycache__" not in path.parts)


def assert_boundary(files, forbidden):
    violations = []
    for path in files:
        for module in imported_modules(path.read_text(encoding="utf-8-sig"), path.relative_to(ROOT)):
            if module.split(".", 1)[0] in forbidden:
                violations.append(f"{path.relative_to(ROOT).as_posix()}: {module}")
    assert not violations, "Forbidden runtime imports:\n" + "\n".join(violations)


def test_dependency_scanner_catches_nested_relative_and_literal_dynamic_imports():
    source = "def f():\n from ...services import runtime_manager\n import numpy as np\n __import__('qgis.core')\n"
    imports = imported_modules(source, "core/pypoprf/algorithms/example.py")
    assert "core.services.runtime_manager" in imports
    assert "numpy" in imports and "qgis.core" in imports
    assert "gui.widgets.quality_panel" in imported_modules(
        "importlib.import_module('gui.widgets.quality_panel')", "services/example.py")


def test_engine_is_qt_free_and_does_not_depend_on_host_or_provisioning_services():
    files = python_files("core")
    assert files
    assert_boundary(files, QT | {"gui", "controllers", "services", "q_models"})
    # Relative imports cannot hide a GUI dependency inside a core namespace.
    for path in files:
        imports = imported_modules(path.read_text(encoding="utf-8-sig"), path.relative_to(ROOT))
        assert not any(set(module.split(".")) & {"gui", "controllers", "services", "q_models"}
                       for module in imports), path


@pytest.mark.parametrize("directory", ["services", "shared"])
def test_services_and_shared_have_no_qt_scientific_or_engine_imports(directory):
    files = python_files(directory)
    assert files
    assert_boundary(files, QT | SCIENTIFIC | {"core", "gui", "controllers"})
    if directory == "shared":
        assert_boundary(files, {"services"})


def test_qgis_host_modules_do_not_import_numerical_engine_dependencies():
    files = [ROOT / "__init__.py", ROOT / "qgis_pypoprf.py"]
    files.extend(path for directory in HOST_DIRECTORIES for path in python_files(directory))
    assert_boundary(files, SCIENTIFIC | {"core"})


def test_shared_contracts_use_only_the_standard_library_and_each_other():
    for path in python_files("shared"):
        imports = imported_modules(path.read_text(encoding="utf-8-sig"), path.relative_to(ROOT))
        assert all(module.split(".", 1)[0] in sys.stdlib_module_names | {"shared"}
                   for module in imports), (path, imports)


def test_runtime_source_has_no_stale_import_names_or_old_package_directories():
    assert not (ROOT / "q_models").exists()
    assert not (ROOT / "core/pypoprf/core").exists()
    for directory in ("core", *HOST_DIRECTORIES):
        for path in python_files(directory):
            source = path.read_text(encoding="utf-8-sig")
            assert "q_models" not in source, path
            assert "core.pypoprf.core" not in source, path
            assert "core/pypoprf/core" not in source, path


def test_lazy_public_api_dictionary_resolves_to_existing_runtime_classes():
    # A dictionary-selected import cannot be covered by literal-call scanning.
    source = ROOT / "core/pypoprf/__init__.py"
    assignments = {node.targets[0].id: ast.literal_eval(node.value)
                   for node in ast.parse(source.read_text(encoding="utf-8-sig")).body
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id in {"_PUBLIC_MODULES", "__all__"}}
    exports, modules = assignments["__all__"], assignments["_PUBLIC_MODULES"]
    assert set(exports) == set(modules) == {"FeatureExtractor", "Model", "DasymetricMapper", "Settings"}
    for name, relative in modules.items():
        module = resolve_name(relative, "core.pypoprf")
        path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
        assert path.is_file(), (name, relative, path)
        definitions = ast.parse(path.read_text(encoding="utf-8-sig")).body
        assert any(isinstance(node, ast.ClassDef) and node.name == name for node in definitions), name


def test_public_engine_api_loads_all_exports_in_canonical_and_plugin_alias_packages():
    script = """
import importlib, importlib.util, pathlib, sys, types
dependencies = ('numpy', 'pandas', 'rasterio', 'sklearn', 'joblib', 'geopandas', 'scipy')
if any(importlib.util.find_spec(name) is None for name in dependencies):
    raise SystemExit(77)
root = pathlib.Path(sys.argv[1])
alias = 'public_api_installed_alias'
package = types.ModuleType(alias)
package.__path__ = [str(root)]
sys.modules[alias] = package
expected = {'FeatureExtractor': '.algorithms.feature_extraction', 'Model': '.algorithms.model',
            'DasymetricMapper': '.algorithms.dasymetric', 'Settings': '.config.settings'}
for package_name in ('core.pypoprf', alias + '.core.pypoprf'):
    module = importlib.import_module(package_name)
    for name, relative in expected.items():
        value = getattr(module, name)
        assert value is getattr(importlib.import_module(relative, package_name), name)
        assert getattr(module, name) is value
    try:
        getattr(module, 'MissingPublicAPI')
    except AttributeError:
        pass
    else:
        raise AssertionError('Unknown public names must raise AttributeError')
assert 'qgis' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script, str(ROOT)], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    if result.returncode == 77:
        pytest.skip("Public engine API requires the scientific engine; bare QGIS host tests cover lazy initialization only")
    assert result.returncode == 0, result.stderr


def test_imported_services_and_shared_do_not_load_qt_or_scientific_code():
    script = """
import importlib, importlib.abc, os, sys, types
from pathlib import Path
forbidden = set(sys.argv[2].split(','))
class NoHostPollution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in forbidden:
            raise AssertionError('Forbidden in host services: ' + fullname)
sys.meta_path.insert(0, NoHostPollution())
original_path, original_environment = list(sys.path), dict(os.environ)
root = Path(sys.argv[1])
alias = 'installed_layout_acceptance'
package = types.ModuleType(alias)
package.__path__ = [str(root)]
sys.modules[alias] = package
for directory in ('shared', 'services'):
    for path in (root / directory).glob('*.py'):
        if path.name != '__init__.py':
            importlib.import_module(alias + '.' + directory + '.' + path.stem)
            importlib.import_module(directory + '.' + path.stem)
importlib.import_module(alias + '.core.pypoprf')
assert sys.path == original_path
assert dict(os.environ) == original_environment
assert not forbidden.intersection(name.split('.')[0] for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script, str(ROOT),
                             ",".join(sorted(QT | SCIENTIFIC))], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_distribution_excludes_audits_tests_helpers_caches_and_development_artifacts(tmp_path):
    source = tmp_path / "source"
    for name, path in package_files(ROOT):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    decoys = ["AUDIT.md", "REVIEW_STRUCTURE_MODEL.md", ".local/reports/AUDIT.md",
              ".local/checkouts/old-source.py", "audit_results.json", "requirements-dev.lock",
              "tests/helpers/quality.py", "tests/test_secret.py", "docs/private.md",
              "case_study/fixture.tif", ".venv/pyvenv.cfg", "dist/previous.zip",
              "scripts/dev_helper.py", "services/__pycache__/leak.py", "core/__pycache__/leak.py"]
    for name in decoys:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"must not ship")
    destination = tmp_path / "plugin.zip"
    manifest = build_plugin(destination, root=source)
    verify_package(destination)
    assert not set(decoys).intersection(manifest["files"])
    with zipfile.ZipFile(destination) as package:
        assert all(name.startswith("pypopRF/") for name in package.namelist())
        assert not any(part in {"tests", "__pycache__", "case_study", ".venv", "dist", "scripts", ".local"}
                       for name in package.namelist() for part in Path(name).parts)
        assert {name for name in manifest["files"] if name.startswith("docs/")} == set(PUBLIC_DOCUMENTATION)
        for expected in ("services/quality_report.py", "services/result_manifest.py",
                         "gui/widgets/quality_panel.py", "shared/runtime_environment.py",
                         "core/pypoprf/algorithms/model.py"):
            assert expected in manifest["files"]


def test_extracted_distribution_services_work_without_repository_pythonpath(tmp_path):
    archive = tmp_path / "plugin.zip"
    build_plugin(archive)
    with zipfile.ZipFile(archive) as package:
        package.extractall(tmp_path / "installed")
    script = """
import importlib, os, sys
before = dict(os.environ)
sys.path.insert(0, sys.argv[1])
from pypopRF.services.quality_report import load_quality_report
from pypopRF.services.result_manifest import population_paths
from pypopRF.services.runtime_manager import RuntimeManager
from pypopRF.shared.runtime_environment import NATIVE_THREAD_LIMITS
from pypopRF.core.pypoprf import __version__
assert load_quality_report(None).run_status == 'not_selected'
assert NATIVE_THREAD_LIMITS['OMP_NUM_THREADS'] == '1'
assert dict(os.environ) == before
assert not any(name in sys.modules for name in ('qgis','numpy','pandas','sklearn','rasterio','joblib'))
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(tmp_path / "installed")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
