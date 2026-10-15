"""Actions' Python shell runs a temporary script, not a repository module."""
import ast
import os
from pathlib import Path
import subprocess
import sys

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
