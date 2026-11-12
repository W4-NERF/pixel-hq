"""Round 3 fixes after review R3-R (decisions R3-D1 to R3-D3): the recruit fallback never names a missing department, a
drag belongs to one pointer, and "unsaved changes" is a comparison evaluated after the mutation.

Backend checks use real files (`roster.save`, `config.load_roster`); UI checks run in the plain-Node DOM harness with its
pointer events. No browser was used. Invented names only.
"""
import json
from pathlib import Path

import pytest

from pixelhq import collect, config, roster
from tests.test_floor_edit import result, run_floor

ROOT = Path(__file__).resolve().parents[1]
CFG = {"orchestrator_profile": "default"}


def saved_roster(tmp_path, monkeypatch, rooms, bots):
    """Saves a file roster in a private home and loads it back like the collector does."""
    home = tmp_path / "home"
    profiles = {b["id"]: {} for b in bots if not b.get("remote")}
    body = {"roster": {"rooms": rooms, "bots": bots}}
    assert roster.save(body, {"hermes_home": str(home)}, profiles) == {"ok": True, "message": "Roster saved."}
    monkeypatch.setenv("HERMES_HOME", str(home))
    loaded = config.load_roster()
    assert loaded["rosterSource"] == "file"
    return loaded


def bot(name, zone, **extra):
    return {"id": name, "cls": "Role", "title": "Title", "zone": zone, "loc": "", "color": "#336699", **extra}


def zone_ids(rooms):
    return [z["id"] for r in rooms for z in r["zones"]]


LAYOUTS = {
    # no department called "ops"; the main room is the second one and has departments
    "main-room-with-departments": (
        [{"id": "annex", "label": "Annex", "zones": [{"id": "desk_a", "label": "Desk A"}]},
         {"id": "hq", "label": "HQ", "main": True, "zones": [{"id": "crew", "label": "Crew"}, {"id": "lab", "label": "Lab"}]}],
        "crew"),
    # the main room is empty: the first department in file order (rooms in order, departments in order)
    "empty-main-room": (
        [{"id": "annex", "label": "Annex", "zones": [{"id": "desk_a", "label": "Desk A"}, {"id": "desk_b", "label": "Desk B"}]},
         {"id": "hq", "label": "HQ", "main": True, "zones": []}],
        "desk_a"),
    # the first rooms have no department at all
    "empty-main-and-first-room": (
        [{"id": "empty", "label": "Empty", "zones": []},
         {"id": "hq", "label": "HQ", "main": True, "zones": []},
         {"id": "annex", "label": "Annex", "zones": [{"id": "late", "label": "Late"}]}],
        "late"),
}


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_recruit_lands_in_an_existing_department_after_save_and_reload(tmp_path, monkeypatch, layout):
    rooms, expected = LAYOUTS[layout]
    first = zone_ids(rooms)[0]
    loaded = saved_roster(tmp_path, monkeypatch, rooms, [bot("sysadmin", first)])
    profiles = {"sysadmin": {}, "new-local": {"description": "a new local profile"}}
    bots = collect.roster_bots(profiles, roster=loaded, cfg=CFG)
    recruit = next(b for b in bots if b["id"] == "new-local")
    assert recruit["zone"] == expected and recruit["auto"] is True
    assert recruit["zone"] in zone_ids(loaded["rooms"]), "the department exists in the roster"
    # department numbers: every bot is counted in exactly one department of the roster
    counts = {z: sum(b["zone"] == z for b in bots) for z in zone_ids(loaded["rooms"])}
    assert sum(counts.values()) == len(bots) == 2 and counts[expected] >= 1
    # the next save is consistent: the recruited bot is accepted by the validator and survives a reload
    again = saved_roster(tmp_path, monkeypatch, loaded["rooms"], [{k: v for k, v in b.items() if k != "auto"} for b in bots])
    assert {b["id"]: b["zone"] for b in again["bots"]}["new-local"] == expected


def test_default_department_rule_and_no_departments():
    rooms = LAYOUTS["empty-main-room"][0]
    assert collect.default_department(rooms) == "desk_a"
    assert collect.default_department([{"id": "hq", "main": True, "zones": []}]) is None
    assert collect.default_department([]) is None


def test_recruit_without_any_department_is_skipped_with_a_warning_not_a_made_up_id():
    warnings = []
    rooms = [{"id": "hq", "label": "HQ", "main": True, "zones": []}]
    bots = collect.roster_bots({"new-local": {}}, warnings, roster={"bots": [], "rooms": rooms, "rosterSource": "file"}, cfg=CFG)
    assert bots == [] and warnings == ["roster: no department for new profile new-local"]


def test_collector_source_has_no_fallback_department_literal():
    text = (ROOT / "pixelhq" / "collect.py").read_text(encoding="utf-8")
    assert '"ops"' not in text and "'ops'" not in text


def test_ui_default_department_of_a_new_bot_follows_the_same_rule(tmp_path):
    out = run_floor(tmp_path, """
const rename = (data, from, to) => {
  data.cfg.rooms.forEach(r => r.zones.forEach(z => { if (z.id === from) z.id = to; }));
  data.bots.forEach(b => { if (b.zone === from) b.zone = to; });
};
rename(DATA, 'ops', 'crew');
renderAll(); tab('roster');
const root = document.getElementById('roster-editor');
const type2 = (sel, value) => { const el = root.querySelector(sel); el.value = value; el.oninput(); };
type2('[data-roster-new-room]', 'empty_main'); type2('[data-roster-new-room-label]', 'Empty main');
root.querySelector('[data-roster-add-room]').onclick();
root.querySelectorAll('[data-roster-room]').find(r => r.dataset.rosterRoom === 'empty_main')
  .querySelector('[data-roster-room-main]').onchange();
const main = rosterDraft.rooms.find(r => r.main === true);
assert.equal(main.id, 'empty_main'); assert.equal(main.zones.length, 0);
type2('[data-roster-new-bot]', 'fresh-remote'); root.querySelector('[data-roster-add-bot]').onclick();
const zones = rosterDraft.rooms.flatMap(r => r.zones).map(z => z.id);
const fresh = rosterDraft.bots.find(b => b.id === 'fresh-remote');
assert.ok(fresh && zones.includes(fresh.zone), 'the new bot has an existing department');
assert.equal(fresh.zone, zones[0], 'first department in file order');
assert.ok(!zones.includes('ops'));
root.querySelector('[data-roster-save]').onclick();
const payload = messages.filter(m => m.pixelhqRoster)[0].pixelhqRoster.roster;
const all = payload.rooms.flatMap(r => r.zones).map(z => z.id);
payload.bots.forEach(b => assert.ok(all.includes(b.zone), b.id + ' has a department'));
console.log('PAYLOAD:' + JSON.stringify(payload));
""")
    payload = result(out)
    assert payload["bots"][-1]["id"] == "fresh-remote"
    profiles = {b["id"]: {} for b in payload["bots"] if not b.get("remote")}
    assert roster.save({"roster": payload}, {"hermes_home": str(tmp_path / "backend")}, profiles)["ok"] is True


# ---------------------------------------------------------------- R3-D2: a drag belongs to one pointer

def test_foreign_pointercancel_leaves_the_active_drag_untouched(tmp_path):
    run_floor(tmp_path, """
toggle();
const [x, y] = mid(desk('sysadmin')), [tx, ty] = free('lab');
pointer.down(x, y, undefined, {pointerType: 'touch'});
pointer.move(x + 8, y); pointer.move(tx, ty);
assert.equal(drag.pointer, 1); assert.equal(drag.started, true);
assert.ok(dept('lab').classList.contains('drop'));
const touch = {pointerId: 2, pointerType: 'touch', isPrimary: false};
pointer.send('pointerdown', 5, 5, 1, document.documentElement, touch);
pointer.send('pointercancel', 5, 5, 0, document.documentElement, touch);
assert.ok(drag && drag.pointer === 1 && drag.started, 'the foreign cancel did not end the drag');
assert.ok(ghost.classList.contains('on') && dept('lab').classList.contains('drop'));
assert.ok(desk('sysadmin').classList.contains('dragging'));
assert.notEqual(dragging, null);
pointer.up(tx, ty);
assert.equal(draftBot('sysadmin').zone, 'lab', 'the own pointer still drops');
assert.equal(drag, null);
""")


def test_own_pointercancel_cancels_and_cleans_up_everything(tmp_path):
    run_floor(tmp_path, """
toggle();
const captures = new Map(), released = [];
Element.prototype.setPointerCapture = function (id) { captures.set(id, this); };
Element.prototype.releasePointerCapture = function (id) { released.push(id); captures.delete(id); };
const count = () => ['pointermove', 'pointerup', 'pointercancel', 'keydown'].map(t => (docListeners.get(t) || []).length);
const listeners0 = count(), saved = JSON.stringify(rosterDraft), before = floor.children;
grab('sysadmin');
const [tx, ty] = free('lab'); pointer.move(tx, ty);
assert.ok(drag.started && captures.get(1) === desk('sysadmin'), 'the desk holds the capture');
pointer.cancel(tx, ty);
assert.equal(drag, null); assert.equal(dragging, null);
assert.ok(!ghost.classList.contains('on')); assert.equal(ghost.innerHTML, '');
assert.ok(!desk('sysadmin').classList.contains('dragging'));
assert.ok(!floor.classList.contains('drag-active'));
assert.equal(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).length, 0);
assert.deepEqual(released, [1]); assert.equal(captures.size, 0, 'the capture is released');
assert.deepEqual(count(), listeners0, 'no listener was added or left behind');
assert.equal(JSON.stringify(rosterDraft), saved); assert.equal(posted().length, 0);
pointer.up(tx, ty);
assert.equal(JSON.stringify(rosterDraft), saved, 'a later pointerup does nothing');
""")


# ---------------------------------------------------------------- R3-D3: unsaved is a comparison after the mutation

BAR_PRELUDE = """
tab('roster');
const root = document.getElementById('roster-editor');
const row = id => root.querySelectorAll('[data-roster-bot]').find(b => q('[data-roster-id]', b).value === id);
const field = (id, name) => q('[data-roster-field="' + name + '"]', row(id));
const shown = bar => !!q('[data-layout-save]', bar);
"""


def test_first_keystroke_in_a_bot_field_shows_both_bars_and_restoring_hides_them(tmp_path):
    run_floor(tmp_path, BAR_PRELUDE + """
const title = field('sysadmin', 'title'), original = title.value, rows = root.children;
title.focus();
assert.ok(!shown(officeBar) && !shown(rosterBar));
type(title, original + 'X');
assert.ok(shown(officeBar) && shown(rosterBar), 'both bars show after the first keystroke');
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes') && rosterBar.innerHTML.includes('Unsaved layout changes'));
assert.equal(field('sysadmin', 'title'), title, 'the focused field was not re-rendered');
assert.equal(document.activeElement, title); assert.equal(root.children, rows);
type(title, original);
assert.ok(!shown(officeBar) && !shown(rosterBar), 'restoring the original value hides both bars');
assert.equal(officeBar.innerHTML, ''); assert.ok(rosterBar.innerHTML.includes('No unsaved changes'), 'the Roster tab keeps its bar');
assert.equal(field('sysadmin', 'title'), title); assert.equal(document.activeElement, title);
type(title, original + 'Y');
assert.ok(shown(officeBar) && shown(rosterBar), 'a new change shows them again');
""")


def test_sprite_and_department_selects_follow_the_same_comparison(tmp_path):
    run_floor(tmp_path, BAR_PRELUDE + """
const sprite = field('sysadmin', 'sprite'), was = sprite.value;
choose(sprite, 'rogue');
assert.ok(shown(officeBar) && shown(rosterBar));
choose(field('sysadmin', 'sprite'), was);
assert.ok(!shown(officeBar) && !shown(rosterBar), 'sprite back to the saved value');
const zone = draftBot('sysadmin').zone;
choose(field('sysadmin', 'zone'), 'lab');
assert.ok(shown(officeBar) && shown(rosterBar));
choose(field('sysadmin', 'zone'), zone);
assert.ok(!shown(officeBar) && !shown(rosterBar), 'department back to the saved value');
""")


def test_a_successful_save_hides_both_bars(tmp_path):
    run_floor(tmp_path, BAR_PRELUDE + """
const title = field('sysadmin', 'title');
type(title, title.value + 'Z');
assert.ok(shown(officeBar) && shown(rosterBar));
const payload = saveFromBar(rosterBar);
assert.equal(payload.bots.find(b => b.id === 'sysadmin').title, title.value);
send({pixelhqRosterResult: {ok: true, message: 'Roster saved.'}});
assert.ok(!shown(officeBar) && !shown(rosterBar), 'no Save/Discard after a successful save');
assert.ok(rosterBar.innerHTML.includes('Roster saved.'), 'the result is shown');
assert.equal(layoutUnsaved(), false);
const again = field('sysadmin', 'title'), saved = again.value;
type(again, saved + '!');
assert.ok(shown(rosterBar), 'a change after the save shows the bar again');
type(again, saved);
assert.ok(!shown(rosterBar), 'and restoring it compares against the saved roster');
""")


@pytest.mark.parametrize("rooms", [[], [{"id": "hq", "label": "HQ", "main": True, "zones": []}],
                                   [5, {"id": "x", "zones": 3}, {"id": "y", "zones": [7, {"label": "no id"}]}]])
def test_a_file_roster_without_any_department_is_invalid_warning_and_default(tmp_path, monkeypatch, rooms):
    home = tmp_path / "home"
    (home / "plugin-data" / "pixel-hq").mkdir(parents=True)
    (home / "plugin-data" / "pixel-hq" / "roster.json").write_text(json.dumps({"rooms": rooms, "bots": []}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    loaded = config.load_roster()
    assert loaded["rosterSource"] == "generated" and zone_ids(loaded["rooms"]) == ["command", "crew"]
    assert loaded["warnings"] == ["roster.json: invalid or unreadable roster (ValueError)"]
    recruit = collect.roster_bots({"new-local": {}}, roster=loaded, cfg=CFG)
    assert [(b["id"], b["zone"]) for b in recruit] == [("new-local", "crew")]
