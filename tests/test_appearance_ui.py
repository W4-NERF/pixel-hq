"""Theme precedence and message-driven mode changes without a browser."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from pixelhq import page
from pixelhq.demo import snapshot
from tests.test_review_ui import run_ui

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("setting,host,expected", [
    ("auto", None, "dark"), ("auto", "light", "light"), ("auto", "dark", "dark"),
    ("dark", None, "dark"), ("dark", "light", "dark"), ("dark", "dark", "dark"),
    ("light", None, "light"), ("light", "dark", "light"), ("light", "light", "light"),
    (None, "light", "light"), ("invalid", None, "dark"),
])
@pytest.mark.parametrize("theme_first", [False, True])
def test_frame_setting_host_default_precedence_in_either_arrival_order(tmp_path, setting, host, expected, theme_first):
    run_ui(tmp_path, """
assert.equal(document.documentElement.dataset.mode,'dark');
const onMsg=listeners.get('message'), data={...DATA,cfg:{...DATA.cfg,appearance:SETTING}};
const theme=()=>{if(HOST)onMsg({source:window.parent,data:{pixelhqTheme:{mode:HOST}}});};
if(THEME_FIRST)theme();
onMsg({source:window.parent,data:{pixelhq:data}});
if(!THEME_FIRST)theme();
assert.equal(document.documentElement.dataset.mode,EXPECTED);
""".replace("SETTING", json.dumps(setting)).replace("HOST", json.dumps(host))
           .replace("EXPECTED", json.dumps(expected)).replace("THEME_FIRST", json.dumps(theme_first)), iframe=True)


def test_theme_changes_and_settings_refresh_keep_user_drafts(tmp_path):
    run_ui(tmp_path, """
const onMsg=listeners.get('message'), send=data=>onMsg({source:window.parent,data});
send({pixelhq:DATA});
const bot=DATA.bots.find(b=>b.leader)||DATA.bots[0]; select(bot.id);
let widget=elements.get('detail').querySelector('[data-review]');
widget.querySelector('[data-rate="pass"]').onclick();
const ref=widget.querySelector('[data-review-ref]'); ref.value='Unsent sample'; ref.oninput();
send({pixelhqTheme:{mode:'light'}});
assert.equal(document.documentElement.dataset.mode,'light');
assert.equal(elements.get('detail').querySelector('[data-review-ref]').value,'Unsent sample');
send({pixelhqTheme:{mode:'dark'}});
assert.equal(document.documentElement.dataset.mode,'dark');
DATA.cfg.appearance='light'; send({pixelhq:DATA});
send({pixelhqTheme:{mode:'dark'}});
assert.equal(document.documentElement.dataset.mode,'light');
DATA.cfg.appearance='auto'; send({pixelhq:DATA});
assert.equal(document.documentElement.dataset.mode,'dark');
assert.equal(messages.filter(m=>m.pixelhqReview).length,0);
""", iframe=True)


@pytest.mark.parametrize("invalid", ["LIGHT", "auto", "unknown", "", None, 1, [], {}])
def test_theme_requires_parent_and_valid_mode_without_forgetting_last_host_mode(tmp_path, invalid):
    run_ui(tmp_path, """
const onMsg=listeners.get('message');
onMsg({source:window.parent,data:{pixelhq:DATA}});
onMsg({source:{},data:{pixelhqTheme:{mode:'light'}}});
assert.equal(document.documentElement.dataset.mode,'dark');
onMsg({source:window.parent,data:{pixelhqTheme:{mode:'light'}}});
onMsg({source:window.parent,data:{pixelhqTheme:{mode:INVALID}}});
assert.equal(document.documentElement.dataset.mode,'light');
""".replace("INVALID", json.dumps(invalid)), iframe=True)


@pytest.mark.parametrize("query,setting,iframe,expected", [
    ("?mode=light", "dark", False, "light"), ("?mode=dark", "light", False, "dark"),
    ("?mode=light&actions=1", "auto", False, "light"),
    ("?mode=invalid", "light", False, "light"), ("?mode=LIGHT", "dark", False, "dark"),
    ("?mode=light", "dark", True, "dark"), ("?mode=dark", "light", True, "light"),
])
def test_standalone_mode_query_overrides_setting_but_not_embedded(tmp_path, query, setting, iframe, expected):
    run_ui(tmp_path, """
DATA.cfg.appearance=SETTING;
listeners.get('message')({source:window.parent,data:{pixelhq:DATA}});
assert.equal(document.documentElement.dataset.mode,EXPECTED);
""".replace("SETTING", json.dumps(setting)).replace("EXPECTED", json.dumps(expected)), actions=query, iframe=iframe)


@pytest.mark.parametrize("setting,query,expected", [("light", "", "light"), ("dark", "?mode=light", "light")])
def test_initial_inlined_snapshot_sets_mode_without_waiting_for_a_message(tmp_path, setting, query, expected):
    data = snapshot()
    data["cfg"]["appearance"] = setting
    source = page.bundle_js().replace("/*PIXELHQ_DATA*/null", json.dumps(data))
    harness = (ROOT / "tests/ui_dom.cjs").read_text(encoding="utf-8")
    probe = f";\nassert.equal(document.documentElement.dataset.mode,{json.dumps(expected)});\n"
    path = tmp_path / "inlined-appearance.cjs"
    path.write_text(harness + source + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "ACTIONS": query, "IFRAME": "0"})
    assert result.returncode == 0, result.stdout + result.stderr
