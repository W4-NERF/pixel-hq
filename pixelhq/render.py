#!/usr/bin/env python3
"""Render dist/pixel-hq.html — a static page with the data embedded.

    python3 render.py          # real data from this machine's Hermes installation
    python3 render.py --demo   # synthetic data (demo.py) — no Hermes fleet required
"""
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/render.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from .page import page_html

OUT = Path(__file__).resolve().parent.parent / "dist" / "pixel-hq.html"

if __name__ == "__main__":
    if "--demo" in sys.argv:
        from .demo import snapshot
        data = snapshot()
    else:
        from .collect import collect
        from .live import query as live
        data = collect()
        data["live"] = live()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page_html(data), encoding="utf-8")
    print(OUT)
