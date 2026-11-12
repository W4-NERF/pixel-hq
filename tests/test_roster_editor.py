"""Roster editor interactions, exact bridge payloads, pending guards and reset confirmation."""
import json
import re
from pathlib import Path

import pytest

from tests.test_roster_ui import run_roster

ROOT = Path(__file__).resolve().parents[1]


def test_editor_has_bounded_grid_fields_and_visible_keyboard_focus():
    css = (ROOT / 'pixelhq/ui/style.css').read_text(encoding='utf-8')
    for selector, declaration in (
        ('#roster', 'padding:'), ('.roster-row', 'grid-template-columns:'),
        ('#roster-editor input', 'min-width:0'), ('.swatches button', 'width:'),
        ('#roster-editor :focus-visible', 'outline:'),
    ):
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', css)
        assert rule and declaration in rule[1], selector


def test_editor_rejects_duplicate_ids_and_local_count_limits(tmp_path):
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');
const attempt=(kind,value)=>{root.querySelector('[data-roster-new-'+kind+']').value=value;root.querySelector('[data-roster-add-'+kind+']').onclick()};
attempt('bot',DATA.bots[0].id);assert.ok(root.innerHTML.includes('Bot id already exists.'));
attempt('zone',DATA.cfg.rooms[0].zones[0].id);assert.ok(root.innerHTML.includes('Department id already exists.'));
rosterDraft.bots=Array.from({length:200},(_,i)=>({...DATA.bots[0],id:'bot-'+i}));rosterDirty=true;
attempt('bot','one-too-many');assert.ok(root.innerHTML.includes('At most 200 bots'));assert.equal(rosterDraft.bots.length,200);
rosterDraft.rooms=[{id:'hq',label:'Main',main:true,zones:Array.from({length:24},(_,i)=>({id:'zone-'+i,label:'Zone'}))}];
attempt('zone','one-too-many');assert.ok(root.innerHTML.includes('At most 24 departments'));assert.equal(rosterDraft.rooms[0].zones.length,24);
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0);
""", iframe=True)


def test_save_payload_single_leader_and_result_lifecycle(tmp_path):
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');
let rows=root.querySelectorAll('[data-roster-bot]');
const chosen=rows[1].querySelector('[data-roster-leader]');chosen.checked=true;chosen.onchange();
rows=root.querySelectorAll('[data-roster-bot]');
assert.equal(rows.filter(row=>row.querySelector('[data-roster-leader]').checked).length,1);
const title=rows[1].querySelector('[data-roster-field="title"]');title.value='Custom title';title.oninput();
const color=rows[1].querySelector('[data-roster-field="color"]');color.value='#abcdef';color.oninput();
const sprite=rows[1].querySelector('[data-roster-field="sprite"]');sprite.value='';sprite.onchange();
const zone=rows[1].querySelector('[data-roster-field="zone"]');zone.value=DATA.cfg.rooms[0].zones[0].id;zone.onchange();
const expected=JSON.parse(JSON.stringify(rosterDraft));
const save=root.querySelector('[data-roster-save]');save.onclick();save.onclick();
root.querySelector('[data-roster-save]').onclick();
assert.equal(messages.filter(m=>m.pixelhqRoster).length,1);
const body=messages.find(m=>m.pixelhqRoster).pixelhqRoster;
assert.deepEqual(body,{roster:expected});
assert.deepEqual(Object.keys(body.roster).sort(),['bots','rooms']);
body.roster.bots.forEach(bot=>{
 assert.ok(!Object.hasOwn(bot,'xp')&&!Object.hasOwn(bot,'model')&&!Object.hasOwn(bot,'auto'));
 assert.ok(!Object.hasOwn(bot,'sprite')||SPRITE_VARIANTS.includes(bot.sprite));
});
assert.equal(body.roster.bots.filter(b=>b.leader).length,1);
assert.equal(body.roster.bots[1].title,'Custom title');
assert.equal(body.roster.bots[1].color,'#abcdef');
assert.equal(root.querySelector('[data-roster-controls]').disabled,true);
assert.ok(root.innerHTML.includes('Saving roster'));
listeners.get('message')({source:{},data:{pixelhqRosterResult:{ok:true,message:'spoof'}}});
assert.ok(root.innerHTML.includes('Saving roster'));
listeners.get('message')({source:window.parent,data:{pixelhqRosterResult:{ok:false,message:'<invalid> & value'}}});
assert.ok(root.innerHTML.includes('res bad'));assert.ok(root.innerHTML.includes('&lt;invalid&gt; &amp; value'));
assert.equal(root.querySelector('[data-roster-controls]').disabled,false);
assert.equal(root.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]').value,'Custom title');
root.querySelector('[data-roster-save]').onclick();
listeners.get('message')({source:window.parent,data:{pixelhqRosterResult:{ok:true,message:'Roster saved.'}}});
const fresh=JSON.parse(JSON.stringify(DATA));fresh.bots[1].title='Fresh saved title';fresh.cfg.rosterSource='file';
listeners.get('message')({source:window.parent,data:{pixelhq:fresh}});
assert.ok(root.innerHTML.includes('res ok'));
assert.equal(root.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]').value,'Fresh saved title');
assert.equal(document.getElementById('first-run').style.display,'none');
""", iframe=True)


def test_remote_add_remove_and_zone_add_rename_remove_empty(tmp_path):
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');
const start=DATA.bots.length,main=DATA.cfg.rooms.find(r=>r.main),count=DATA.cfg.rooms.flatMap(r=>r.zones||[]).length;
let id=root.querySelector('[data-roster-new-zone]');id.value='new-zone';
root.querySelector('[data-roster-new-zone-label]').value='New <zone> & room';
root.querySelector('[data-roster-add-zone]').onclick();
assert.equal(rosterDraft.rooms.flatMap(r=>r.zones).length,count+1);
assert.equal(rosterDraft.rooms.find(r=>r.main).zones.at(-1).id,'new-zone');
let zones=root.querySelectorAll('[data-roster-zone]');
let added=zones.find(z=>z.dataset.rosterZone==='new-zone');
assert.ok(root.innerHTML.includes('New &lt;zone&gt; &amp; room'));
let label=added.querySelector('[data-roster-zone-label]');label.value='Renamed zone';label.oninput();
id=root.querySelector('[data-roster-new-bot]');id.value='remote-new';
root.querySelector('[data-roster-add-bot]').onclick();
let rows=root.querySelectorAll('[data-roster-bot]');assert.equal(rows.length,start+1);
let remote=rows.at(-1);assert.equal(remote.querySelector('[data-roster-id]').value,'remote-new');
assert.equal(rosterDraft.bots.at(-1).remote,true);
let zone=remote.querySelector('[data-roster-field="zone"]');zone.value='new-zone';zone.onchange();
renderRoster();
added=root.querySelectorAll('[data-roster-zone]').find(z=>z.dataset.rosterZone==='new-zone');
assert.equal(added.querySelector('[data-roster-zone-label]').value,'Renamed zone');
assert.equal(added.querySelector('[data-roster-remove-zone]').disabled,true);
added.querySelector('[data-roster-remove-zone]').onclick();
assert.ok(rosterDraft.rooms.flatMap(r=>r.zones).some(z=>z.id==='new-zone'),'occupied zones cannot be removed');
rows=root.querySelectorAll('[data-roster-bot]');rows.at(-1).querySelector('[data-roster-remove-bot]').onclick();
assert.equal(root.querySelectorAll('[data-roster-bot]').length,start);
added=root.querySelectorAll('[data-roster-zone]').find(z=>z.dataset.rosterZone==='new-zone');
assert.equal(added.querySelector('[data-roster-remove-zone]').disabled,false);
added.querySelector('[data-roster-remove-zone]').onclick();
assert.ok(!rosterDraft.rooms.flatMap(r=>r.zones).some(z=>z.id==='new-zone'));
assert.equal(rosterDraft.rooms.find(r=>r.main).id,main.id);
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0);
""", iframe=True)


@pytest.mark.parametrize("kind,value", [("bot", "../bad"), ("bot", "x" * 65), ("bot", ""),
                                        ("zone", "../bad"), ("zone", "x" * 65), ("zone", "")])
def test_add_controls_reject_invalid_ids_without_changing_draft(tmp_path, kind, value):
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor'),before=JSON.stringify(rosterDraft);
root.querySelector('[data-roster-new-KIND]').value=VALUE;
root.querySelector('[data-roster-add-KIND]').onclick();
assert.equal(JSON.stringify(rosterDraft),before);
assert.ok(root.innerHTML.includes('res bad'));
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0);
""".replace("KIND", kind).replace("VALUE", json.dumps(value)), iframe=True)


def test_reset_two_clicks_expiry_and_standalone_no_host_result(tmp_path):
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');
let reset=root.querySelector('[data-roster-reset]');reset.onclick();
assert.equal(reset.dataset.armed,'1');assert.ok(reset.textContent.includes('Confirm:'));
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0);
timers.at(-1)();assert.notEqual(reset.dataset.armed,'1');
reset.onclick();reset.onclick();
assert.equal(root.querySelector('[data-roster-controls]').disabled,true);
assert.deepEqual(messages.filter(m=>m.pixelhqRoster).map(m=>m.pixelhqRoster),[{reset:true}]);
listeners.get('message')({source:window.parent,data:{pixelhqRosterResult:{ok:true,message:'Roster reset to generated.'}}});
const fresh=JSON.parse(JSON.stringify(DATA));fresh.cfg.rosterSource='generated';
listeners.get('message')({source:window.parent,data:{pixelhq:fresh}});
assert.ok(root.innerHTML.includes('Roster reset to generated.'));
assert.notEqual(document.getElementById('first-run').style.display,'none');
""", iframe=True)
    run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');root.querySelector('[data-roster-save]').onclick();
assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
assert.equal(root.querySelector('[data-roster-controls]').disabled,false);
let reset=root.querySelector('[data-roster-reset]');reset.onclick();reset.onclick();
assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0);
""", actions="?actions=1")
