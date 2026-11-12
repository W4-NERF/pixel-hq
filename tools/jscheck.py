#!/usr/bin/env python3
"""Syntax-check the plain-JS files with node (strips ESM import/export lines so `node --check` accepts them).

The UI is checked as the bundle the page serves (`pixelhq.page.bundle_js()`: every `pixelhq/ui/js/*.js` file
in file-name order, one shared scope); `desktop/plugin.js` is checked as a file.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, src: str) -> bool:
    src = re.sub(r"^import .*?$", "", src, flags=re.M)
    src = re.sub(r"^export default", "const __default =", src, flags=re.M)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(src)
        tmp = f.name
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print(f"{label}: {'ok' if r.returncode == 0 else 'SYNTAX ERROR'}")
    if r.returncode:
        print(r.stderr)
    return r.returncode == 0


def main() -> int:
    from pixelhq import page

    ok = check("pixelhq/ui/js (bundle)", page.bundle_js())
    plugin = ROOT / "desktop/plugin.js"
    if not plugin.exists():
        print("missing desktop/plugin.js")
        return 1
    ok = check("desktop/plugin.js", plugin.read_text(encoding="utf-8")) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
