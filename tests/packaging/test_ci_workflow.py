"""Actions' Python shell runs a temporary script, not a repository module."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_windows_clean_engine_step_imports_repo_from_external_script(tmp_path):
    workflow = yaml.load((ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["headless"]["steps"]
                if step.get("name") == "Verify clean isolated engine setup on Windows")
    tree = ast.parse(step["run"])
    boundary = next(index for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                        and target.id == "before" for target in node.targets))
    imports = ast.unparse(ast.Module(body=tree.body[:boundary], type_ignores=[]))
    script = tmp_path / "actions-python-shell.py"
    script.write_text(imports + "\nassert RuntimeManager.__module__ == 'services.runtime_manager'\n",
                      encoding="utf-8")
    env = {key:value for key,value in os.environ.items() if key.upper() != "PYTHONPATH"}
    result = subprocess.run([sys.executable, "-I", str(script)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_windows_clean_engine_step_compares_canonical_cache_paths(tmp_path, monkeypatch):
    workflow = yaml.load((ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["headless"]["steps"]
                if step.get("name") == "Verify clean isolated engine setup on Windows")
    (tmp_path / "alias").mkdir()
    actual = tmp_path / "actual"
    actual.mkdir()
    # Like Windows short-name aliases, lexical and canonical paths can differ.
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "alias" / ".." / "actual"))
    calls = []

    class RuntimeManager:
        def __init__(self, package_root, cache_root):
            self.cache_root = Path(cache_root).resolve()

        def setup(self, executable):
            calls.append(executable)
            return self.cache_root / "environments" / "test" / "Scripts" / "python.exe"

        def get_python(self):
            return self.cache_root / "environments" / "test" / "Scripts" / "python.exe"

    monkeypatch.setitem(sys.modules, "services.runtime_manager",
                        types.SimpleNamespace(RuntimeManager=RuntimeManager))
    monkeypatch.setattr(sys, "path", list(sys.path))
    exec(compile(step["run"], "<actions-python-shell>", "exec"), {})
    assert calls == [sys.executable]
