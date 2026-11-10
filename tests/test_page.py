"""No-build page composition and embedded-data safety."""
import json
import re
from pathlib import Path

from pixelhq import page

ROOT = Path(__file__).resolve().parents[1]


def test_page_inlines_markup_styles_script_and_data():
    ui = ROOT / "pixelhq" / "ui"
    assert sorted(p.name for p in ui.iterdir()) == ["app.js", "index.html", "style.css"]
    assert not (ROOT / "pixelhq" / "ui.html").exists()
    markup = (ui / "index.html").read_text(encoding="utf-8")
    css = (ui / "style.css").read_text(encoding="utf-8")
    js = (ui / "app.js").read_text(encoding="utf-8")
    assert markup.count("/*PIXELHQ_CSS*/") == markup.count("/*PIXELHQ_JS*/") == 1
    data = {"demo": True, "bots": [], "sample": "A sample <quest>"}
    expected = markup.replace("/*PIXELHQ_CSS*/", css).replace("/*PIXELHQ_JS*/", js)
    expected = expected.replace(page.IMPORT_LINE, page.font_faces(), 1)
    expected = expected.replace("/*PIXELHQ_DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"), 1)
    html = page.page_html(data)
    assert html == expected
    assert '"demo": true' in html
    assert 'id="detail"' in html and "function liveTab()" in html
    assert "@font-face" in html and "data:font/woff2;base64," in html
    assert "fonts.googleapis.com" not in html
    assert "?actions=1" in html
    assert "/*PIXELHQ_CSS*/" not in html and "/*PIXELHQ_JS*/" not in html


def test_page_without_data_keeps_host_loading_and_data_cannot_break_out():
    assert "/*PIXELHQ_DATA*/null" in page.page_html()
    data = {"ref": "</script><script>alert('sample')</script>"}
    html = page.page_html(data)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1
    assert json.dumps(data).replace("</", "<\\/") in scripts[0]


def test_review_form_has_local_styles_for_readable_controls():
    css = (ROOT / "pixelhq" / "ui" / "style.css").read_text(encoding="utf-8")
    assert ".review-dims" in css and ".review-ref" in css
    assert ".review fieldset" in css and ".review select" in css and ".review input" in css
