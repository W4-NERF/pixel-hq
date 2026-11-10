#!/usr/bin/env python3
"""Syntax-check the plain-JS files with node (strips ESM import/export lines so `node --check` accepts them)."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["pixelhq/ui/app.js", "desktop/plugin.js"]
rc = 0
for rel in FILES:
    p = ROOT / rel

    if not p.exists():
        print(f"missing {rel}")
        rc = 1
        continue
    src = p.read_text(encoding="utf-8")

    src = re.sub(r"^import .*?$", "", src, flags=re.M)
    src = re.sub(r"^export default", "const __default =", src, flags=re.M)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(src)
        tmp = f.name
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print(f"{rel}: {'ok' if r.returncode == 0 else 'SYNTAX ERROR'}")
    if r.returncode:
        print(r.stderr)
        rc = 1
sys.exit(rc)
