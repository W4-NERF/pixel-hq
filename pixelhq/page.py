"""Build the Pixel HQ page: ui/ markup, CSS and JS + fonts + optionally embedded data.

Fonts: IBM Plex Mono and Silkscreen, both SIL OFL 1.1 (latin subset, licences in fonts/) — embedded so
the page looks identical inside the desktop app's sandboxed iframe without network or CSP exceptions.

The UI files and fonts are read once, when this module is imported: the page belongs to the loaded version
of the Python modules. Files updated on disk later take effect in a new process (for the backend: after the
gateway restart); ``render.py`` runs as a fresh process, so it always renders the files on disk.
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


def _font_faces() -> str:
    out = []
    for fam, weight, fn in FONTS:
        p = HERE / "fonts" / fn
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};"
                       f"font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "".join(out)


def _bundle() -> str:
    """The UI script: ``ui/js/*.js`` in file-name order, one shared scope, no build step."""
    files = sorted((HERE / "ui" / "js").glob("*.js"), key=lambda p: p.name)
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def _template() -> str:
    """The page with markup, styles, script and fonts inlined; only the data placeholder is left."""
    ui = HERE / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    html = html.replace("/*PIXELHQ_CSS*/", (ui / "style.css").read_text(encoding="utf-8"), 1)
    html = html.replace("/*PIXELHQ_JS*/", _BUNDLE, 1)
    return html.replace(IMPORT_LINE, _FONT_FACES, 1)


_FONT_FACES = _font_faces()
_BUNDLE = _bundle()
_TEMPLATE = _template()


def bundle_js() -> str:
    """The UI script (every ``ui/js/*.js`` file, concatenated in file-name order), as read at import."""
    return _BUNDLE


def font_faces() -> str:
    """The embedded ``@font-face`` rules, as read at import."""
    return _FONT_FACES


def script_json(data) -> str:
    """JSON that is inert inside an inline ``<script>``: every ``<``, ``>`` and ``&`` is a JSON escape.

    Escaping only ``</`` is not enough: a card title such as ``<!--<script>`` switches the HTML parser into the
    script's "double escaped" state, where the page's own ``</script>`` no longer ends the script.
    """
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def page_html(data: dict | None = None) -> str:
    """The page from the copy read at import, with ``data`` embedded when given."""
    html = _TEMPLATE
    if data is not None:
        html = html.replace("/*PIXELHQ_DATA*/null", script_json(data), 1)
    return html
