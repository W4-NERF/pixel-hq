"""Exercise the documented import command in a subprocess without Hermes paths."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_collect_imports_without_hermes_on_sys_path(fleet):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "HERMES_HOME": str(fleet.root)}
    presence = subprocess.run(
        ["python3", "-c", "import importlib.util, json; print(json.dumps({n: importlib.util.find_spec(n) is not None for n in ('hermes', 'hermes_cli')}))"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
    )
    assert presence.returncode == 0, presence.stderr
    assert json.loads(presence.stdout) == {"hermes": False, "hermes_cli": False}
    command = ["python3", "-c", "import pixelhq.collect"]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    print(f'python3 -c "import pixelhq.collect": exit {result.returncode}; hermes=False, hermes_cli=False')
