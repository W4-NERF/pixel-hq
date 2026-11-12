"""Keep the documented settings in sync with the manifest-generated Markdown."""
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_settings_tool_prints_all_manifest_keys_from_any_working_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "settings_table.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    schema = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))["config_schema"]
    lines = result.stdout.splitlines()
    assert lines[:2] == ["| Key | Type | Default | Meaning |", "|---|---|---|---|"]
    assert len(lines) == len(schema) + 2
    assert result.stdout.endswith("\n")
    for line, (key, entry) in zip(lines[2:], schema.items()):
        default = json.dumps(entry["default"], ensure_ascii=False)
        assert line == f"| `{key}` | `{entry['type']}` | `{default}` | {entry['description']} |"


def test_readme_settings_table_matches_tool_output():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "settings_table.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start, end = "<!-- settings-table:start -->", "<!-- settings-table:end -->"
    assert readme.count(start) == readme.count(end) == 1
    documented = readme.split(start + "\n", 1)[1].split(end, 1)[0]
    assert documented == result.stdout, "Regenerate the README table with python3 tools/settings_table.py"
