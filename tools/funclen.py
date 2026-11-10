#!/usr/bin/env python3
"""Report functions over 80 physical lines in pixelhq/ and dashboard/.

Count from def/async def through the final statement, including comments and blank
lines inside that span but not decorators. Nested functions and methods are checked
as well. Exit 1 for violations, 0 (with no output) otherwise. An optional root path
supports offline fixture checks; the default is the repository containing this tool.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def oversized_functions(path: Path, limit: int = 80):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > limit:
                yield node.name, node.lineno, length


def main(root: Path = ROOT) -> int:
    failed = False
    for directory in ("pixelhq", "dashboard"):
        for path in sorted((root / directory).rglob("*.py")):
            for name, line, length in oversized_functions(path):
                print(f"{path.relative_to(root)}:{line}: {name}: {length} lines")
                failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT))
