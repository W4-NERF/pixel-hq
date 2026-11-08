"""Build the Bot-HQ page: ui.html + self-hosted fonts (base64) + optionally embedded data.

Fonts: IBM Plex Mono and Silkscreen, both SIL OFL 1.1 (latin subset, licences in fonts/) — embedded so
the page looks identical inside the desktop app's sandboxed iframe without network or CSP exceptions.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = [("IBM Plex Mono", 400, "IBMPlexMono-400.woff2"),
         ("IBM Plex Mono", 600, "IBMPlexMono-600.woff2"),
         ("Silkscreen", 400, "Silkscreen-400.woff2")]
IMPORT_LINE = ("@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
               "&family=Silkscreen&display=swap');")


def font_faces() -> str:
    out = []
    for fam, weight, fn in FONTS:
        p = HERE / "fonts" / fn
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};"
                       f"font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "".join(out)


def page_html(data: dict | None = None) -> str:
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    html = html.replace(IMPORT_LINE, font_faces(), 1)
    if data is not None:
        blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # no </script> break-out
        html = html.replace("/*BOTHQ_DATA*/null", blob, 1)
    return html
