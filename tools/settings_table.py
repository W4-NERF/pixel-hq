#!/usr/bin/env python3
"""Print the README settings table from plugin.yaml, preserving manifest order."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def settings_table(manifest_path: Path = ROOT / "plugin.yaml") -> str:
    schema = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["config_schema"]
    rows = ["| Key | Type | Default | Meaning |", "|---|---|---|---|"]
    for key, entry in schema.items():
        default = json.dumps(entry["default"], ensure_ascii=False)
        rows.append(f"| `{key}` | `{entry['type']}` | `{default}` | {entry['description']} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    print(settings_table(), end="")
