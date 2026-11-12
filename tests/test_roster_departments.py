"""Rooms and departments in the Roster tab (round 3, section 2).

Every operation runs in the DOM harness on the shared roster draft; the Save payload is compared with the roster that
operation must produce and is then accepted by the real backend validator (`pixelhq.roster.save`), so an operation
cannot leave an invalid roster behind. Invented names only.
"""
import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from pixelhq import config, page, roster
from pixelhq.demo import snapshot as demo_snapshot
from tests.test_scoring_collect import collector

ROOT = Path(__file__).resolve().parents[1]
BOT_KEYS = ("id", "cls", "title", "zone", "loc", "color", "leader", "remote", "sprite")

PRELUDE = """
const root=document.getElementById('roster-editor');
const q=(sel,scope=root)=>scope.querySelector(sel);
const room=id=>root.querySelectorAll('[data-roster-room]').find(r=>r.dataset.rosterRoom===id);
const zone=id=>root.querySelectorAll('[data-roster-zone]').find(z=>z.dataset.rosterZone===id);
const bot=id=>root.querySelectorAll('[data-roster-bot]').find(b=>q('[data-roster-id]',b).value===id);
const type=(el,value)=>{el.value=value;el.oninput()};
const choose=(el,value)=>{el.value=value;el.onchange()};
const addRoom=(id,label)=>{type(q('[data-roster-new-room]'),id);type(q('[data-roster-new-room-label]'),label);q('[data-roster-add-room]').onclick()};
const addDept=(id,label,inRoom)=>{
 type(q('[data-roster-new-zone]'),id);type(q('[data-roster-new-zone-label]'),label);
 if(inRoom)choose(q('[data-roster-new-zone-room]'),inRoom);
 q('[data-roster-add-zone]').onclick();
};
const draftOk=()=>{
 const d=rosterDraft,zones=d.rooms.flatMap(r=>r.zones);
 assert.equal(d.rooms.filter(r=>r.main===true).length,1,'exactly one main room');
 assert.equal(new Set(d.rooms.map(r=>r.id)).size,d.rooms.length,'room ids are unique');
 assert.equal(new Set(zones.map(z=>z.id)).size,zones.length,'department ids are unique');
 d.bots.forEach(b=>assert.ok(zones.some(z=>z.id===b.zone),'bot '+b.id+' has a department'));
 assert.ok(d.rooms.length<=8&&zones.length<=24);
};
const posted=()=>messages.filter(m=>m.pixelhqRoster).map(m=>m.pixelhqRoster);
const save=()=>{q('[data-roster-save]').onclick();assert.equal(posted().length,1,'one Save message');return posted()[0].roster};
tab('roster');
"""


def run_editor(tmp_path, probe, *, data=None):
    """Run `probe` in the harness against `data` (default: the demo snapshot); returns the harness stdout."""
    source = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8")
    markup = (ROOT / "pixelhq" / "ui" / "index.html").read_text(encoding="utf-8").split("<body>")[1].split("<script>")[0]
    source += "document.getElementById('test-root').innerHTML=" + json.dumps(markup) + ";\n"
    source += page.bundle_js().replace("/*PIXELHQ_DATA*/null", json.dumps(data or demo_snapshot()))
    source += ";\n(()=>{\n" + PRELUDE + probe + "\n})();\nconsole.log('editor probe: ok');\n"
    script = tmp_path / "roster-departments.cjs"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30,
                            env={**os.environ, "ACTIONS": "", "IFRAME": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def base(data=None) -> dict:
    """The roster the editor starts from: the snapshot's rooms and the schema keys of its bots."""
    snap = data or demo_snapshot()
    return {"rooms": copy.deepcopy(snap["cfg"]["rooms"]),
            "bots": [{k: b[k] for k in BOT_KEYS if k in b} for b in snap["bots"]]}


def accepted(tmp_path, payload: dict, snap=None) -> None:
    """The backend validator takes the payload (non-remote bots are existing profiles)."""
    bots = (snap or demo_snapshot())["bots"]
    profiles = {b["id"]: {} for b in bots if not b.get("remote")} | {b["id"]: {} for b in payload["bots"] if not b.get("remote")}
    result = roster.save({"roster": payload}, {"hermes_home": str(tmp_path / "backend-home")}, profiles)
    assert result == {"ok": True, "message": "Roster saved."}, result


def edit(tmp_path, ops: str, *, data=None) -> dict:
    """Run `ops`, then Save; returns the roster the page posted (already checked against the backend)."""
    out = run_editor(tmp_path, ops + "\ndraftOk();console.log('PAYLOAD:'+JSON.stringify(save()));", data=data)
    edit.stdout = out
    payload = json.loads(next(line[8:] for line in out.splitlines() if line.startswith("PAYLOAD:")))
    accepted(tmp_path, payload, data)
    return payload


def zones_of(rooms: list, room_id: str) -> list:
    return next(r for r in rooms if r["id"] == room_id)["zones"]


# ---- rooms ---------------------------------------------------------------------------------------------------------

def test_room_add(tmp_path):
    got = edit(tmp_path, "addRoom('annex','Annex <B> & Co');")
    want = base()
    want["rooms"].append({"id": "annex", "label": "Annex <B> & Co", "zones": []})
    assert got == want


def test_room_rename(tmp_path):
    got = edit(tmp_path, "type(q('[data-roster-room-label]',room('outpost')),'Remote site');")
    want = base()
    want["rooms"][1]["label"] = "Remote site"
    assert got == want


def test_room_reorder_up_and_down(tmp_path):
    got = edit(tmp_path, """
assert.equal(q('[data-roster-room-up]',room('hq')).disabled,true);
assert.equal(q('[data-roster-room-down]',room('outpost')).disabled,true);
q('[data-roster-room-down]',room('hq')).onclick();
assert.deepEqual(rosterDraft.rooms.map(r=>r.id),['outpost','hq']);
addRoom('annex','Annex');
q('[data-roster-room-up]',room('annex')).onclick();
""")
    want = base()
    hq, outpost = want["rooms"]
    want["rooms"] = [outpost, {"id": "annex", "label": "Annex", "zones": []}, hq]
    assert got == want


def test_room_set_main_is_a_radio_with_exactly_one_main(tmp_path):
    got = edit(tmp_path, """
assert.equal(q('[data-roster-room-main]',room('hq')).checked,true);
assert.equal(q('[data-roster-room-main]',room('outpost')).checked,false);
q('[data-roster-room-main]',room('outpost')).onchange();
assert.equal(q('[data-roster-room-main]',room('outpost')).checked,true);
assert.equal(q('[data-roster-room-main]',room('hq')).checked,false);
""")
    want = base()
    del want["rooms"][0]["main"]
    want["rooms"][1]["main"] = True
    assert got == want


def test_room_remove_when_empty_and_not_main(tmp_path):
    got = edit(tmp_path, """
addRoom('annex','Annex');
assert.equal(q('[data-roster-remove-room]',room('annex')).disabled,false);
q('[data-roster-remove-room]',room('annex')).onclick();
assert.equal(room('annex'),undefined);
""")
    assert got == base()


def test_room_remove_is_refused_for_the_main_room_and_for_a_room_with_departments(tmp_path):
    got = edit(tmp_path, """
for (const id of ['hq','outpost']) {
 const button=q('[data-roster-remove-room]',room(id));
 assert.equal(button.disabled,true,id);
 button.onclick();
 assert.ok(room(id),id+' stays');
}
rosterDraft.rooms[0].zones=[];rosterDraft.bots=[];renderRoster();
assert.equal(q('[data-roster-remove-room]',room('hq')).disabled,true,'an empty main room still cannot be removed');
""")
    assert [r["id"] for r in got["rooms"]] == ["hq", "outpost"]


def test_room_note_set_edit_and_clear(tmp_path):
    got = edit(tmp_path, """
type(q('[data-roster-room-note]',room('hq')),'Ground floor');
type(q('[data-roster-room-note]',room('outpost')),'');
""")
    want = base()
    want["rooms"][0]["note"] = "Ground floor"
    del want["rooms"][1]["note"]
    assert got == want


# ---- departments ---------------------------------------------------------------------------------------------------

def test_department_add_to_any_room_and_to_the_main_room_by_default(tmp_path):
    got = edit(tmp_path, """
assert.equal(q('[data-roster-new-zone-room]').value,'hq','the main room is the default');
addDept('bay','Bay');
addDept('depot','Depot <ok>','outpost');
assert.equal(q('[data-roster-new-zone-room]').value,'outpost','the choice survives the render');
""")
    want = base()
    zones_of(want["rooms"], "outpost").append({"id": "depot", "label": "Depot <ok>"})
    zones_of(want["rooms"], "hq").append({"id": "bay", "label": "Bay"})
    assert got == want


def test_department_rename(tmp_path):
    got = edit(tmp_path, "type(q('[data-roster-zone-label]',zone('lab')),'Workshop');")
    want = base()
    zones_of(want["rooms"], "hq")[2]["label"] = "Workshop"
    assert got == want


def test_department_move_to_another_room_keeps_its_bots(tmp_path):
    got = edit(tmp_path, """
choose(q('[data-roster-zone-room]',zone('lab')),'outpost');
assert.deepEqual(rosterDraft.rooms[1].zones.map(z=>z.id),['remote','lab']);
assert.equal(q('[data-roster-zone-room]',zone('lab')).value,'outpost');
assert.equal(q('[data-roster-field="zone"]',bot('dev-a')).value,'lab');
""")
    want = base()
    lab = zones_of(want["rooms"], "hq").pop(2)
    zones_of(want["rooms"], "outpost").append(lab)
    assert got == want
    assert [b["zone"] for b in got["bots"] if b["id"].startswith("dev-")] == ["lab", "lab"]


def test_department_reorder_up_and_down_inside_its_room(tmp_path):
    got = edit(tmp_path, """
assert.equal(q('[data-roster-zone-up]',zone('command')).disabled,true);
assert.equal(q('[data-roster-zone-down]',zone('quarantine')).disabled,true);
assert.equal(q('[data-roster-zone-up]',zone('remote')).disabled,true,'the only department of a room has no neighbour');
q('[data-roster-zone-down]',zone('ops')).onclick();
q('[data-roster-zone-up]',zone('quarantine')).onclick();
""")
    want = base()
    command, ops, lab, quarantine = zones_of(want["rooms"], "hq")
    want["rooms"][0]["zones"] = [command, lab, quarantine, ops]
    assert got == want


def test_department_quarantine_flag_on_and_off(tmp_path):
    got = edit(tmp_path, """
assert.equal(q('[data-roster-zone-quarantine]',zone('quarantine')).checked,true);
assert.equal(q('[data-roster-zone-quarantine]',zone('ops')).checked,false);
const on=q('[data-roster-zone-quarantine]',zone('ops'));on.checked=true;on.onchange();
const off=q('[data-roster-zone-quarantine]',zone('quarantine'));off.checked=false;off.onchange();
assert.equal(q('[data-roster-zone-quarantine]',zone('ops')).checked,true);
""")
    want = base()
    zones = zones_of(want["rooms"], "hq")
    zones[1]["quarantine"] = True
    del zones[3]["quarantine"]
    assert got == want


def test_department_remove_when_empty(tmp_path):
    got = edit(tmp_path, """
addDept('temp','Temporary');
assert.equal(q('[data-roster-remove-zone]',zone('temp')).disabled,false);
q('[data-roster-remove-zone]',zone('temp')).onclick();
assert.equal(zone('temp'),undefined);
q('[data-roster-remove-bot]',bot('remote-ops')).onclick();
assert.equal(q('[data-roster-remove-zone]',zone('remote')).disabled,false,'empty once its bot is gone');
q('[data-roster-remove-zone]',zone('remote')).onclick();
""")
    want = base()
    want["rooms"][1]["zones"] = []
    want["bots"] = [b for b in want["bots"] if b["id"] != "remote-ops"]
    assert got == want


def test_department_remove_is_refused_while_a_bot_belongs_to_it(tmp_path):
    got = edit(tmp_path, """
const button=q('[data-roster-remove-zone]',zone('ops'));
assert.equal(button.disabled,true);
button.onclick();
assert.ok(zone('ops'));
""")
    assert got == base()


# ---- bots ----------------------------------------------------------------------------------------------------------

def test_bot_department_select_is_grouped_by_room_and_assigns(tmp_path):
    got = edit(tmp_path, """
const select=q('[data-roster-field="zone"]',bot('dev-a'));
assert.deepEqual(select.children.map(g=>g.tag),['optgroup','optgroup']);
assert.deepEqual(select.children.map(g=>g.attrs.label),['HQ · MAIN HOST','OUTPOST · REMOTE HOST']);
assert.deepEqual(select.children.map(g=>g.children.map(o=>o.value)),[['command','ops','lab','quarantine'],['remote']]);
assert.equal(select.value,'lab');
choose(select,'remote');
assert.equal(q('[data-roster-field="zone"]',bot('dev-a')).value,'remote');
""")
    want = base()
    next(b for b in want["bots"] if b["id"] == "dev-a")["zone"] = "remote"
    assert got == want


def test_bot_select_follows_room_and_department_changes(tmp_path):
    run_editor(tmp_path, """
addRoom('annex','Annex');addDept('vault','Vault','annex');
choose(q('[data-roster-zone-room]',zone('ops')),'annex');
const select=q('[data-roster-field="zone"]',bot('sysadmin'));
assert.deepEqual(select.children.map(g=>g.attrs.label),['HQ · MAIN HOST','OUTPOST · REMOTE HOST','Annex']);
assert.deepEqual(select.children[2].children.map(o=>o.value),['vault','ops']);
assert.equal(select.value,'ops','the bot keeps its department');
""")


def test_compact_bot_rows_one_grid_row_per_bot_and_swatches_only_for_the_edited_row(tmp_path):
    run_editor(tmp_path, """
const rows=root.querySelectorAll('.roster-row'),bots=root.querySelectorAll('[data-roster-bot]');
assert.equal(rows.length,DATA.bots.length);assert.equal(bots.length,DATA.bots.length);
assert.deepEqual(q('.roster-head').children.map(s=>s.tag),Array(8).fill('span'));
const tokens=el=>el.attrs.class==='roster-color'?'colour':el.attrs.class==='roster-leader'?'leader':el.attrs.class==='roster-end'?'end'
 :el.dataset.rosterId!==undefined?'id':el.dataset.rosterField;
assert.deepEqual(rows[0].children.map(tokens),['id','title','cls','sprite','zone','colour','leader','end']);
assert.equal(root.querySelectorAll('[data-roster-swatch]').length,0);
q('[data-roster-edit]',bot('dev-a')).onclick();
assert.equal(bot('dev-a').querySelectorAll('[data-roster-swatch]').length,12);
assert.equal(q('[data-roster-edit]',bot('dev-a')).attrs['aria-expanded'],'true');
assert.ok(q('[data-roster-field="loc"]',bot('dev-a')),'location opens with the swatches');
q('[data-roster-edit]',bot('dev-b')).onclick();
assert.equal(bot('dev-a').querySelectorAll('[data-roster-swatch]').length,0,'one row at a time');
assert.equal(bot('dev-b').querySelectorAll('[data-roster-swatch]').length,12);
q('[data-roster-edit]',bot('dev-b')).onclick();
assert.equal(root.querySelectorAll('[data-roster-swatch]').length,0);
assert.equal(posted().length,0,'opening a row never writes');
""")


def test_edited_row_colour_and_location_reach_the_payload(tmp_path):
    got = edit(tmp_path, """
q('[data-roster-edit]',bot('dev-b')).onclick();
const pick=q('[data-roster-swatch]',bot('dev-b'));console.log('SWATCH:'+pick.dataset.rosterSwatch);pick.onclick();
type(q('[data-roster-field="loc"]',bot('dev-b')),'Annex desk');
""")
    want = base()
    row = next(b for b in want["bots"] if b["id"] == "dev-b")
    row["color"] = next(line[7:] for line in edit.stdout.splitlines() if line.startswith("SWATCH:"))
    row["loc"] = "Annex desk"
    assert got == want


def test_layout_minimum_widths_fit_1100px_and_narrow_widths_wrap():
    css = (ROOT / "pixelhq/ui/style.css").read_text(encoding="utf-8")
    chrome = 24 * 2 + 12 * 2 + 2   # #roster padding, fieldset padding and border
    for selector, extra in ((".roster-row", 2 * (8 + 1)), (".roster-room-head,.roster-zone", 20)):
        rule = re.search(re.escape(selector) + r"\{[^}]*grid-template-columns:([^;]+);gap:(\d+)px", css)
        assert rule, selector
        columns = re.findall(r"minmax\((\d+)px,[^)]*\)|(?<![\w(,])(\d+)px", rule[1])
        floor = sum(int(a or b) for a, b in columns) + int(rule[2]) * (len(columns) - 1)
        assert floor + extra + chrome <= 1100, (selector, floor)
    assert re.search(r"@media \(max-width:\d+px\)\{.*\.roster-row,.*repeat\(auto-fit", css)


# ---- invariants ----------------------------------------------------------------------------------------------------

def test_every_operation_keeps_one_main_room_and_every_bot_in_a_department(tmp_path):
    edit(tmp_path, """
const steps=[
 ()=>addRoom('annex','Annex'),
 ()=>addDept('vault','Vault','annex'),
 ()=>addDept('bay','Bay'),
 ()=>choose(q('[data-roster-zone-room]',zone('ops')),'annex'),
 ()=>choose(q('[data-roster-zone-room]',zone('ops')),'outpost'),
 ()=>q('[data-roster-room-main]',room('annex')).onchange(),
 ()=>q('[data-roster-room-down]',room('annex')).onclick(),
 ()=>q('[data-roster-room-up]',room('hq')).onclick(),
 ()=>q('[data-roster-zone-down]',zone('command')).onclick(),
 ()=>q('[data-roster-remove-room]',room('annex')).onclick(),
 ()=>q('[data-roster-remove-zone]',zone('vault')).onclick(),
 ()=>q('[data-roster-remove-room]',room('annex')).onclick(),
 ()=>q('[data-roster-remove-zone]',zone('ops')).onclick(),
 ()=>choose(q('[data-roster-field="zone"]',bot('sysadmin')),'bay'),
 ()=>q('[data-roster-room-main]',room('hq')).onchange(),
 ()=>q('[data-roster-remove-room]',room('annex')).onclick(),
 ()=>choose(q('[data-roster-zone-room]',zone('bay')),'hq'),
 ()=>q('[data-roster-remove-room]',room('annex')).onclick(),
 ()=>{const c=q('[data-roster-zone-quarantine]',zone('bay'));c.checked=true;c.onchange()},
 ()=>q('[data-roster-remove-bot]',bot('remote-ops')).onclick(),
];
steps.forEach((step,i)=>{step();draftOk();assert.equal(rosterDraft.rooms.some(r=>r.main===true),true,'step '+i)});
assert.equal(room('annex'),undefined,'the emptied room is gone');
assert.equal(posted().length,0,'editing never writes');
""")


def test_save_refuses_a_draft_without_a_main_room_and_a_bot_without_department(tmp_path):
    run_editor(tmp_path, """
rosterDirty=true;rosterDraft.rooms.forEach(r=>{delete r.main});renderRoster();
q('[data-roster-save]').onclick();
assert.ok(root.innerHTML.includes('Exactly one main room is required.'));assert.equal(posted().length,0);
q('[data-roster-room-main]',room('hq')).onchange();
rosterDraft.bots[1].zone='gone';renderRoster();
assert.equal(q('[data-roster-field="zone"]',bot('sysadmin')).value,'','the select shows an empty choice');
q('[data-roster-save]').onclick();
assert.ok(root.innerHTML.includes('Bot sysadmin needs a department.'));assert.equal(posted().length,0);
choose(q('[data-roster-field="zone"]',bot('sysadmin')),'ops');
q('[data-roster-save]').onclick();
assert.equal(posted().length,1);
""")


def test_editor_limits_hold_on_both_sides(tmp_path):
    run_editor(tmp_path, """
rosterDirty=true;
rosterDraft.rooms=Array.from({length:7},(_,i)=>({id:'r'+i,label:'R',main:i===0,zones:[]}));renderRoster();
addRoom('r7','Eighth');assert.equal(rosterDraft.rooms.length,8,'the 8th room is accepted');
addRoom('r8','Ninth');assert.equal(rosterDraft.rooms.length,8);
assert.ok(root.innerHTML.includes('At most 8 rooms are allowed.'));
rosterDraft.rooms[0].zones=Array.from({length:22},(_,i)=>({id:'z'+i,label:'Z'}));rosterDraft.bots=[];renderRoster();
addDept('z22','Z','r7');addDept('z23','Z','r7');assert.equal(rosterDraft.rooms.flatMap(r=>r.zones).length,24,'the 24th is accepted');
addDept('z24','Z','r7');assert.equal(rosterDraft.rooms.flatMap(r=>r.zones).length,24);
assert.ok(root.innerHTML.includes('At most 24 departments are allowed.'));
""")


@pytest.mark.parametrize("kind,value,message", [
    ("room", "", "Room id: use"), ("room", "../x", "Room id: use"), ("room", "a.b", "Room id: use"),
    ("room", "x" * 65, "Room id: use"), ("room", "hq", "Room id already exists."),
    ("zone", "", "Department id: use"), ("zone", "a.b", "Department id: use"), ("zone", "x" * 65, "Department id: use"),
    ("zone", "ops", "Department id already exists."),
])
def test_add_rejects_invalid_and_duplicate_ids_without_touching_the_draft(tmp_path, kind, value, message):
    run_editor(tmp_path, """
const before=JSON.stringify(rosterDraft);
type(q('[data-roster-new-KIND]'),VALUE);q('[data-roster-add-KIND]').onclick();
assert.equal(JSON.stringify(rosterDraft),before);assert.ok(root.innerHTML.includes(MESSAGE));assert.equal(posted().length,0);
""".replace("KIND", kind).replace("VALUE", json.dumps(value)).replace("MESSAGE", json.dumps(message)))


def test_room_and_department_names_follow_the_shared_text_rule(tmp_path):
    run_editor(tmp_path, """
const bad='bad'+String.fromCharCode(10)+'name';
addRoom('annex',bad);assert.ok(!room('annex'));assert.ok(root.innerHTML.includes('Room name: use at most 40 characters'));
addDept('vault',bad);assert.ok(!zone('vault'));assert.ok(root.innerHTML.includes('Department name: use at most 40 characters'));
type(q('[data-roster-room-note]',room('hq')),'n'.repeat(81));
q('[data-roster-save]').onclick();
assert.ok(root.innerHTML.includes('.note: use at most 80 characters'));assert.equal(posted().length,0);
""")


def test_editor_limits_equal_the_backend_limits():
    js = page.bundle_js()
    assert re.search(rf"const ROSTER_MAX_ROOMS = {roster.MAX_ROOMS};", js)
    assert re.search(rf"const ROSTER_MAX_ZONES = {roster.MAX_ZONES};", js)


# ---- generated roster ----------------------------------------------------------------------------------------------

def test_generated_roster_is_editable_and_the_first_save_writes_the_file(tmp_path, fleet, monkeypatch):
    module = collector(fleet, monkeypatch, orchestrator_profile="ops-bot")
    (fleet.root / "plugin-data" / "pixel-hq" / "roster.json").unlink()
    snap = json.loads(json.dumps(module.collect()))
    assert snap["cfg"]["rosterSource"] == "generated"
    ids = [b["id"] for b in snap["bots"]]
    got = edit(tmp_path, """
addRoom('annex','Annex');
addDept('vault','Vault','annex');
type(q('[data-roster-zone-label]',zone('crew')),'Crew pool');
choose(q('[data-roster-zone-room]',zone('command')),'annex');
choose(q('[data-roster-field="zone"]',bot('default')),'vault');
q('[data-roster-room-main]',room('annex')).onchange();
q('[data-roster-room-up]',room('annex')).onclick();
""", data=snap)
    want = base(snap)
    hq, annex = want["rooms"][0], {"id": "annex", "label": "Annex", "zones": []}
    command = hq["zones"].pop(0)
    annex["zones"] = [{"id": "vault", "label": "Vault"}, command]
    hq["zones"][0]["label"] = "Crew pool"
    del hq["main"]
    annex["main"] = True
    want["rooms"] = [annex, hq]
    next(b for b in want["bots"] if b["id"] == "default")["zone"] = "vault"
    assert got == want
    # the first Save wrote the file through the real backend; the loader now reads it back as a file roster
    result = roster.save({"roster": got}, {"hermes_home": str(fleet.root)}, {i: {} for i in ids})
    assert result["ok"], result
    loaded = config.load_roster()
    assert loaded["rosterSource"] == "file" and loaded["rooms"] == got["rooms"]
