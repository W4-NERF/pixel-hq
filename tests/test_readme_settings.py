"""Keep the documented settings in sync with the manifest-generated Markdown."""
import json
import subprocess
import sys
from pathlib import Path

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
    for line, (key, entry) in zip(lines[2:], schema.items(), strict=True):
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


FORCED_COMMAND = (
    'command="python3 -B /path/to/pixelhq/export.py --label <name>",no-pty,no-port-forwarding,'
    "no-agent-forwarding,no-X11-forwarding,restrict"
)


def test_readme_documents_the_several_hosts_recipe_and_the_disclosure():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("\n## Several hosts\n", 1)[1].split("\n## ", 1)[0]
    assert FORCED_COMMAND in section
    assert "command=\"python3 /path" not in section, "every forced command line carries -B"
    flat = " ".join(section.split())
    for needle in ("python3 -B -m pixelhq.export", "equivalent", "without `-B`, `-m` imports the package", "`generated` time"):
        assert needle in flat, needle
    for needle in ("Host atlas-export", '"remote_sources": ["ssh:atlas-export"]', "--home", "--kanban-db", "Read permissions"):
        assert needle in section
    disclosure = readme.split("\n## What it reads and writes (disclosure)\n", 1)[1].split("\n## ", 1)[0]
    for needle in ("`remote_sources`", "BatchMode=yes", "only while a snapshot", "untrusted", "writes nothing"):
        assert needle in disclosure
    assert "`SSH_AUTH_SOCK`" in disclosure and "`LC_CTYPE`" in disclosure, "the explicit SSH environment is disclosed"
    assert "(#several-hosts)" in disclosure
