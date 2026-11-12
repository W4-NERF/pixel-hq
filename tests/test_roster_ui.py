"""Exercise roster UI event handlers in the shared plain-Node DOM, not a browser."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from pixelhq import page
from pixelhq.demo import snapshot

ROOT = Path(__file__).resolve().parents[1]


def run_roster(tmp_path, probe, *, actions="", iframe=False):
    source = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8")
    markup = (ROOT / "pixelhq" / "ui" / "index.html").read_text(encoding="utf-8").split("<body>")[1].split("<script>")[0]
    source += "document.getElementById('test-root').innerHTML=" + json.dumps(markup) + ";\n"
    app = page.bundle_js()
    source += app.replace("/*PIXELHQ_DATA*/null", json.dumps(snapshot())) + ";\n(()=>{\n" + probe + "\n})();\n"
    source += "\nconsole.log('roster UI behavior: ok');\n"
    script = tmp_path / "roster-ui.cjs"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "ACTIONS": actions, "IFRAME": "1" if iframe else "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("source", ["generated", "file", None])
@pytest.mark.parametrize("iframe,actions,forced", [(True, "", False), (True, "?firstrun=1", False),
                                                    (False, "", False), (False, "?firstrun=1", True),
                                                    (False, "?firstrun=10", False)])
def test_banner_only_generated_or_forced_standalone_demo(tmp_path, source, iframe, actions, forced):
    run_roster(tmp_path, """
DATA.cfg.rosterSource=SOURCE;
renderAll();
const banner=document.getElementById('first-run');
assert.equal(banner.style.display!=='none',VISIBLE);
if(VISIBLE){
 const n=DATA.bots.filter(b=>!b.remote).length;
 assert.ok(banner.innerHTML.includes('Roster generated from your '+n+' profiles. Give your bots roles, colours and rooms.'));
 assert.ok(banner.querySelector('[data-roster-customise]'));
 banner.querySelector('[data-roster-dismiss]').onclick();
 assert.equal(banner.style.display,'none');
 renderAll();assert.equal(banner.style.display,'none','dismiss lasts for this page load');
}
""".replace("SOURCE", json.dumps(source)).replace("VISIBLE", json.dumps(source == "generated" or forced)),
               iframe=iframe, actions=actions)


def test_editor_rows_fields_swatches_and_draft_survive_snapshot_and_theme(tmp_path):
    run_roster(tmp_path, """
tab('roster');
const editor=document.getElementById('roster-editor');
let rows=editor.querySelectorAll('[data-roster-bot]');
assert.equal(rows.length,DATA.bots.length);
rows.forEach((row,i)=>{
 const bot=DATA.bots[i];
 assert.equal(row.querySelector('[data-roster-id]').value,bot.id);
 assert.equal(row.querySelector('[data-roster-id]').readOnly,true);
 assert.equal(row.querySelector('[data-roster-field="title"]').value,bot.title);
 assert.equal(row.querySelector('[data-roster-field="cls"]').value,bot.cls);
 assert.equal(row.querySelector('[data-roster-field="zone"]').value,bot.zone);
 assert.equal(row.querySelectorAll('[data-roster-swatch]').length,0,'swatches only open for the row being edited');
 assert.equal(row.querySelector('[data-roster-field="color"]').attrs.type,'text');
 const spriteSelect=row.querySelector('[data-roster-field="sprite"]');
 assert.deepEqual(spriteSelect.children.map(o=>o.value),['',...SPRITE_VARIANTS]);
 assert.equal(spriteSelect.value,bot.sprite||'');
 assert.equal(!!row.querySelector('[data-roster-remove-bot]'),bot.remote===true);
});
const first=rows[0],title=first.querySelector('[data-roster-field="title"]');
title.value='Edited title';title.oninput();
first.querySelector('[data-roster-edit]').onclick();
let open=editor.querySelectorAll('[data-roster-bot]')[0];
assert.equal(open.querySelectorAll('[data-roster-swatch]').length,12);
assert.equal(new Set(open.querySelectorAll('[data-roster-swatch]').map(b=>b.dataset.rosterSwatch)).size,12);
assert.equal(editor.querySelectorAll('[data-roster-swatch]').length,12,'only one row is open');
open.querySelectorAll('[data-roster-swatch]')[5].onclick();
rows=editor.querySelectorAll('[data-roster-bot]');
const color=rows[0].querySelector('[data-roster-field="color"]');
assert.equal(color.value,PALETTE.dark.swatches[5]);
const custom=rows[0].querySelector('[data-roster-field="cls"]');custom.value='Custom role';custom.oninput();
const spriteSelect=rows[0].querySelector('[data-roster-field="sprite"]');spriteSelect.value='medic';spriteSelect.onchange();
listeners.get('message')({source:window.parent,data:{pixelhq:JSON.parse(JSON.stringify(DATA))}});
listeners.get('message')({source:window.parent,data:{pixelhqTheme:{mode:'light'}}});
rows=editor.querySelectorAll('[data-roster-bot]');
assert.equal(rows[0].querySelector('[data-roster-field="title"]').value,'Edited title');
assert.equal(rows[0].querySelector('[data-roster-field="cls"]').value,'Custom role');
assert.equal(rows[0].querySelector('[data-roster-field="sprite"]').value,'medic');
assert.equal(rows[0].querySelector('[data-roster-field="color"]').value,PALETTE.dark.swatches[5]);
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0,'editing never writes');
""", iframe=True)


def test_roster_labels_and_attribute_values_are_escaped(tmp_path):
    run_roster(tmp_path, """
const attack='<img src=x onerror="bad"> & \\'quoted\\'';
DATA.bots=DATA.bots.slice(0,1);
Object.assign(DATA.bots[0],{id:attack,title:attack,cls:attack,loc:attack,color:attack,zone:attack});
DATA.cfg.rooms=[{id:'hq',label:attack,main:true,zones:[{id:attack,label:attack}]}];
renderAll();tab('roster');
const editor=document.getElementById('roster-editor');
assert.ok(!editor.innerHTML.includes('<img'));
assert.ok(editor.innerHTML.includes('&lt;img'));
assert.ok(editor.innerHTML.includes('&quot;bad&quot;'));
assert.ok(editor.innerHTML.includes('&#39;quoted&#39;'));
assert.equal(editor.querySelectorAll('img').length,0);
assert.equal(editor.querySelector('[data-roster-id]').value,attack);
assert.equal(editor.querySelector('[data-roster-field="title"]').value,attack);
assert.equal(editor.querySelector('[data-roster-field="cls"]').value,attack);
assert.equal(editor.querySelector('[data-roster-field="color"]').value,attack);
""", iframe=True)


def test_standalone_firstrun_does_not_claim_a_non_demo_roster_is_generated(tmp_path):
    run_roster(tmp_path, """
DATA.demo=false;DATA.cfg.rosterSource='file';renderAll();
assert.equal(document.getElementById('first-run').style.display,'none');
""", actions="?firstrun=1")


@pytest.mark.parametrize("iframe,actions,visible", [(True, "", True), (False, "", False),
                                                    (False, "?actions=1", True), (False, "?firstrun=1", False)])
def test_roster_tab_requires_embed_or_actions_and_banner_opens_it(tmp_path, iframe, actions, visible):
    run_roster(tmp_path, """
const nav=document.getElementById('rostertab');
assert.equal(nav.style.display!=='none',VISIBLE);
if(VISIBLE){
 DATA.cfg.rosterSource='generated';renderAll();
 document.getElementById('first-run').querySelector('[data-roster-customise]').onclick();
 assert.ok(document.getElementById('roster').classList.contains('on'));
 assert.ok(nav.classList.contains('on'));
}else{
 tab('roster');assert.ok(!document.getElementById('roster').classList.contains('on'));
 assert.equal(document.getElementById('roster-editor').innerHTML,'');
 if(document.getElementById('first-run').style.display!=='none'){
  document.getElementById('first-run').querySelector('[data-roster-customise]').onclick();
  assert.ok(!document.getElementById('roster').classList.contains('on'));
 }
}
""".replace("VISIBLE", json.dumps(visible)), iframe=iframe, actions=actions)
