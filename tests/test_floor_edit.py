"""Round 3, section 3: edit mode on the Office floor (drag & drop of bots between departments, "Move to…", in-place room
and department controls, the "Unsaved layout changes" bar).

Everything runs in the plain-Node DOM harness (tests/ui_dom.cjs) with its pointer events: pointerdown/pointermove/pointerup with
coordinates, `elementFromPoint` over boxes that the PRELUDE lays out, `setPointerCapture` as a no-op. A drag is never tested by
calling the drop function. Save payloads are compared with the roster the operation must produce and are accepted by the real
backend validator. Invented names only; no browser was used.
"""
import json
import re
from pathlib import Path

import pytest

from pixelhq import page
from tests.test_roster_departments import accepted, base
from tests.test_roster_ui import run_roster

ROOT = Path(__file__).resolve().parents[1]

# The floor is laid out as a grid of 280 px boxes (five departments in the demo); desks sit two per row inside their box.
PRELUDE = """
const send = data => listeners.get('message')({source: window.parent, data});
const floor = document.getElementById('floor');
const ghost = document.getElementById('drag-ghost');
const officeBar = document.getElementById('office-bar'), rosterBar = document.getElementById('roster-bar');
document.layout = el => {
  if (el.matches('.zone')) {
    const i = floor.querySelectorAll('.zone').indexOf(el);
    return {left: 20 + (i % 4) * 300, top: 20 + Math.floor(i / 4) * 300, width: 280, height: 280};
  }
  if (el.matches('.desk')) {
    const zone = el.closest('.zone'), box = document.layout(zone), i = zone.querySelectorAll('.desk').indexOf(el);
    return {left: box.left + 8 + (i % 2) * 100, top: box.top + 60 + Math.floor(i / 2) * 120, width: 92, height: 110};
  }
  return null;
};
const q = (sel, scope = floor) => scope.querySelector(sel);
const desk = id => floor.querySelectorAll('.desk').find(d => d.dataset.id === id);
const dept = id => floor.querySelectorAll('.zone').find(z => z.dataset.dept === id);
const room = id => floor.querySelectorAll('.room').find(r => r.dataset.room === id);
const deskIds = id => dept(id).querySelectorAll('.desk').map(d => d.dataset.id);
const mid = el => { const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; };
const free = id => { const b = dept(id).getBoundingClientRect(); return [b.left + b.width - 10, b.top + b.height - 10]; };
const OUTSIDE = [5, 5];
const toggle = () => document.getElementById('edit-layout').onclick();
const type = (el, value) => { el.value = value; el.oninput(); };
const choose = (el, value) => { el.value = value; el.onchange(); };
const posted = () => messages.filter(m => m.pixelhqRoster).map(m => m.pixelhqRoster);
const draftBot = id => rosterDraft.bots.find(b => b.id === id);
const snap = () => JSON.parse(JSON.stringify(DATA));
// Presses on a desk and moves past the threshold; returns the start point.
const grab = (id, dx = 6, dy = 6) => { const [x, y] = mid(desk(id)); pointer.down(x, y); pointer.move(x + dx, y + dy); return [x, y]; };
const dragTo = (id, [x, y]) => { grab(id); pointer.move(x, y); pointer.up(x, y); };
const saveFromBar = (bar = officeBar) => { q('[data-layout-save]', bar).onclick(); assert.equal(posted().length, 1); return posted()[0].roster; };
const CLEAN = '<span class="layout-clean">No unsaved changes</span>';
const out = (name, value) => console.log(name + ':' + JSON.stringify(value));
"""


def run_floor(tmp_path, probe, *, iframe=True, actions=""):
    return run_roster(tmp_path, PRELUDE + probe, iframe=iframe, actions=actions)


def result(output, name="PAYLOAD"):
    line = next(line for line in output.splitlines() if line.startswith(name + ":"))
    return json.loads(line[len(name) + 1:])


def moved(bot_id, zone):
    want = base()
    next(b for b in want["bots"] if b["id"] == bot_id)["zone"] = zone
    return want


# ---- the switch --------------------------------------------------------------------------------------------------------

def test_edit_layout_is_offered_in_the_embedded_page_and_with_actions_only(tmp_path):
    probe = "const button = document.getElementById('edit-layout');"
    run_floor(tmp_path, probe + "assert.notEqual(button.style.display, 'none'); assert.equal(button.attrs['aria-pressed'], 'false');"
              "toggle(); assert.equal(layoutEdit, true); assert.equal(button.attrs['aria-pressed'], 'true');", iframe=True)
    run_floor(tmp_path, probe + "assert.notEqual(button.style.display, 'none');", iframe=False, actions="?actions=1")
    run_floor(tmp_path, probe + "assert.equal(button.style.display, 'none');"
              "toggle(); assert.equal(layoutEdit, false); assert.ok(!floor.classList.contains('editing'));"
              "assert.equal(floor.querySelectorAll('[data-move-to]').length, 0);", iframe=False, actions="")


def test_the_floor_is_drawn_from_the_draft_in_edit_mode_and_from_the_snapshot_outside_it(tmp_path):
    run_floor(tmp_path, """
const home = id => floor.querySelectorAll('.zone').find(z => z.querySelectorAll('.desk').some(d => d.dataset.id === id)).dataset.dept;
assert.ok(!floor.classList.contains('editing'));
assert.equal(floor.querySelectorAll('[data-move-to]').length, 0, 'no controls outside edit mode');
assert.equal(floor.querySelectorAll('[data-edit-open-room]').length, 0);
toggle();
assert.ok(floor.classList.contains('editing'));
assert.equal(floor.querySelectorAll('.desk').length, DATA.bots.length);
assert.equal(floor.querySelectorAll('[data-move-to]').length, DATA.bots.length, 'a Move to… select on every desk');
assert.deepEqual(floor.querySelectorAll('.zone').map(z => z.dataset.dept), ['command', 'ops', 'lab', 'quarantine', 'remote']);
assert.deepEqual(floor.querySelectorAll('.room[data-room]').map(r => r.dataset.room), ['hq', 'outpost']);
assert.ok(q('[data-edit-open-room]'), 'the "＋ Room" control');
const first = q('[data-move-to]');
assert.deepEqual(first.querySelectorAll('optgroup').map(g => g.attrs.label), ['HQ · MAIN HOST', 'OUTPOST · REMOTE HOST']);
// placement from the draft, status from the snapshot
draftBot('devops').zone = 'lab'; rosterChanged(); renderRoster();
assert.equal(home('devops'), 'lab');
assert.equal(DATA.bots.find(b => b.id === 'devops').zone, 'ops', 'the snapshot is untouched');
assert.ok(desk('devops').attrs.class.includes('st-' + DATA.bots.find(b => b.id === 'devops').status));
// leaving edit mode keeps the draft and the bar, the floor is the snapshot again
toggle();
assert.ok(!floor.classList.contains('editing'));
assert.equal(home('devops'), 'ops');
assert.equal(rosterDirty, true);
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'));
toggle();
assert.equal(home('devops'), 'lab', 'the draft is back in edit mode');
""")


# ---- dragging ----------------------------------------------------------------------------------------------------------

def test_drag_a_desk_onto_another_department_changes_bot_zone_and_the_save_payload(tmp_path):
    out = run_floor(tmp_path, """
toggle();
const before = floor.children;
const [x0, y0] = mid(desk('sysadmin'));
pointer.down(x0, y0);
pointer.move(x0 + 3, y0);
assert.ok(!ghost.classList.contains('on'), 'no ghost below the threshold');
pointer.move(x0 + 8, y0 + 3);
assert.ok(ghost.classList.contains('on'), 'ghost follows the pointer');
assert.ok(ghost.innerHTML.includes('class="spr"'), 'the ghost is the sprite');
assert.ok(desk('sysadmin').classList.contains('dragging'));
assert.ok(floor.classList.contains('drag-active'));
assert.equal(dragging, floor);
const [lx, ly] = free('lab');
pointer.move(lx, ly);
assert.equal(ghost.style.transform, 'translate(' + (lx + 10) + 'px,' + (ly + 10) + 'px)');
assert.deepEqual(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).map(z => z.dataset.dept), ['lab']);
pointer.move(...OUTSIDE);
assert.equal(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).length, 0, 'no highlight outside');
const [rx, ry] = mid(desk('dev-a'));
pointer.move(rx, ry);
assert.deepEqual(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).map(z => z.dataset.dept), ['lab'],
  'over a desk the department is highlighted');
assert.equal(draftBot('sysadmin').zone, 'ops', 'nothing changes before the drop');
assert.equal(floor.children, before, 'no render during the drag');
pointer.up(rx, ry);
assert.ok(!ghost.classList.contains('on'));
assert.equal(dragging, null);
assert.equal(drag, null);
assert.equal(draftBot('sysadmin').zone, 'lab');
assert.equal(DATA.bots.find(b => b.id === 'sysadmin').zone, 'ops');
assert.ok(deskIds('lab').includes('sysadmin') && !deskIds('ops').includes('sysadmin'), 'the floor shows the new placement');
assert.equal(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).length, 0);
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'));
assert.equal(rosterBar.innerHTML, officeBar.innerHTML, 'one state, two bars');
out('PAYLOAD', saveFromBar());
""")
    payload = result(out)
    assert payload == moved("sysadmin", "lab")
    accepted(tmp_path, payload)


def test_a_drag_works_for_the_lone_bot_of_a_department_and_across_rooms(tmp_path):
    out = run_floor(tmp_path, "toggle(); dragTo('trial-model', free('remote')); out('PAYLOAD', saveFromBar());")
    assert result(out) == moved("trial-model", "remote")
    accepted(tmp_path, result(out))


@pytest.mark.parametrize("how", ["outside", "escape", "pointercancel", "own", "released-outside-without-pointerup"])
def test_drop_outside_escape_cancel_and_own_department_change_nothing(tmp_path, how):
    run_floor(tmp_path, """
toggle();
const how = HOW, before = floor.children, saved = JSON.stringify(rosterDraft);
grab('sysadmin');
assert.ok(ghost.classList.contains('on'));
const [lx, ly] = free('lab'), [ox, oy] = free('ops');
pointer.move(lx, ly);
assert.ok(dept('lab').classList.contains('drop'));
if (how === 'outside') pointer.up(...OUTSIDE);
if (how === 'escape') { pointer.key('Escape'); pointer.up(lx, ly); }
if (how === 'pointercancel') { pointer.cancel(lx, ly); pointer.up(lx, ly); }
if (how === 'own') { pointer.move(ox, oy); pointer.up(ox, oy); }
if (how === 'released-outside-without-pointerup') pointer.send('pointermove', lx, ly, 0);
assert.equal(drag, null);
assert.equal(dragging, null);
assert.ok(!ghost.classList.contains('on'));
assert.equal(floor.querySelectorAll('.zone').filter(z => z.classList.contains('drop')).length, 0);
assert.ok(!desk('sysadmin').classList.contains('dragging'));
assert.equal(JSON.stringify(rosterDraft), saved);
assert.equal(rosterDirty, false);
assert.equal(officeBar.innerHTML, CLEAN, 'clean line: nothing changed');
assert.equal(posted().length, 0);
assert.equal(floor.children, before, 'nothing was re-rendered');
""".replace("HOW", json.dumps(how)))


def test_movement_below_four_pixels_is_a_click_that_selects_the_desk(tmp_path):
    run_floor(tmp_path, """
toggle();
const before = floor.children, saved = JSON.stringify(rosterDraft);
assert.notEqual(sel, 'devops');
for (const [dx, dy] of [[0, 0], [3, 0], [2, 2], [4, 0]]) {
  const [x, y] = mid(desk('devops'));
  sel = null;
  pointer.down(x, y); pointer.move(x + dx, y + dy); pointer.up(x + dx, y + dy); pointer.click(x + dx, y + dy);
  assert.equal(sel, 'devops', 'a click selects the desk (' + dx + ',' + dy + ')');
  assert.ok(!ghost.classList.contains('on'));
  assert.equal(drag, null);
}
assert.equal(JSON.stringify(rosterDraft), saved);
assert.equal(rosterDirty, false);
assert.equal(floor.children, before, 'a click does not re-render the floor');
// more than four pixels is a drag
const [x, y] = mid(desk('devops'));
pointer.down(x, y); pointer.move(x + 5, y);
assert.ok(ghost.classList.contains('on'));
pointer.key('Escape');
""")


def test_the_click_that_follows_a_drag_does_not_select_but_the_next_click_does(tmp_path):
    run_floor(tmp_path, """
toggle();
sel = 'default';
const [rx, ry] = mid(desk('dev-a'));
grab('sysadmin'); pointer.move(rx, ry); pointer.up(rx, ry);
assert.equal(draftBot('sysadmin').zone, 'lab');
pointer.click(rx, ry);
assert.equal(sel, 'default', 'the browser click after a drag is ignored');
const [x, y] = mid(desk('dev-a'));
pointer.down(x, y); pointer.up(x, y); pointer.click(x, y);
assert.equal(sel, 'dev-a');
""")


def test_a_drop_without_a_following_click_does_not_swallow_the_next_desk_click(tmp_path):
    """A drop re-renders the floor, so the browser sends no click; the block must end with the pointerup's task."""
    run_floor(tmp_path, """
const tasks = [];
hostClock.later = fn => tasks.push(fn);
const nextTask = () => tasks.splice(0).forEach(fn => fn());
toggle();
sel = 'default';
const [rx, ry] = mid(desk('dev-a'));
grab('sysadmin'); pointer.move(rx, ry); pointer.up(rx, ry);
assert.equal(draftBot('sysadmin').zone, 'lab');
nextTask();
toggle();
const [x, y] = mid(desk('dev-a'));
pointer.click(x, y);
assert.equal(sel, 'dev-a', 'the first click after the drop selects');
""")


def test_pointer_events_on_the_controls_of_a_desk_do_not_start_a_drag(tmp_path):
    run_floor(tmp_path, """
toggle();
const select = q('[data-move-to="sysadmin"]');
const [x, y] = mid(desk('sysadmin'));
pointer.down(x, y, select); pointer.move(x + 30, y + 30, select);
assert.equal(drag, null);
assert.ok(!ghost.classList.contains('on'));
pointer.up(x + 30, y + 30);
pointer.down(x, y, undefined, {button: 2, buttons: 2}); pointer.move(x + 30, y);
assert.equal(drag, null, 'only the primary button drags');
assert.ok(!ghost.classList.contains('on'));
""")


def test_outside_edit_mode_a_pointer_press_never_starts_a_drag(tmp_path):
    run_floor(tmp_path, """
const [x, y] = mid(desk('sysadmin'));
pointer.down(x, y); pointer.move(x + 30, y + 30);
assert.equal(drag, null);
assert.ok(!ghost.classList.contains('on'));
pointer.up(x + 30, y + 30);
assert.equal(rosterDirty, false);
""")


# ---- no interruption ---------------------------------------------------------------------------------------------------

DEFERRAL = """
toggle();
const next = snap(); delete next.cfg.appearance; DATA = next;
const changed = () => {
  const copy = snap();
  copy.bots.find(b => b.id === 'dev-b').status = 'blocked';
  copy.bots.find(b => b.id === 'dev-b').blocked = 2;
  return copy;
};
const liveFor = () => ({generated: 10, bots: {'dev-a': {active: true, tasks: [], sessions: [
  {id: 'sample-session', title: 'Sample', source: 'desktop', startedAt: 1, lastAt: 2, msgs: 3, toolCalls: 1, inTok: 0, outTok: 0}]}}});
const before = floor.children;
grab('sysadmin');
send({pixelhq: changed()});
send({pixelhqLive: liveFor()});
send({pixelhqTheme: {mode: 'light'}});
assert.equal(floor.children, before, 'snapshot, live data and theme did not re-render the floor during the drag');
assert.ok(deferredRenders.has(floor), 'the render waits');
assert.equal(DATA.bots.find(b => b.id === 'dev-b').status, 'blocked', 'the state is current');
assert.ok(desk('dev-b').attrs.class.includes('st-idle'), 'the desk still shows the old state');
assert.ok(ghost.classList.contains('on'), 'the drag goes on');
"""


def test_snapshot_live_and_theme_messages_during_a_drag_are_applied_after_the_drop(tmp_path):
    run_floor(tmp_path, DEFERRAL + """
const [lx, ly] = free('lab');
pointer.move(lx, ly);
assert.equal(floor.children, before);
pointer.up(lx, ly);
assert.equal(draftBot('sysadmin').zone, 'lab');
assert.notEqual(floor.children, before, 'rendered after the drop');
assert.equal(deferredRenders.has(floor), false);
assert.ok(deskIds('lab').includes('sysadmin'));
assert.ok(desk('dev-b').attrs.class.includes('st-blocked'), 'the snapshot that arrived during the drag is shown');
assert.ok(desk('dev-a').attrs.class.includes('st-running'), 'the live data that arrived during the drag is shown');
assert.equal(document.documentElement.dataset.mode, 'light');
""")


@pytest.mark.parametrize("ending", ["escape", "outside", "own"])
def test_the_deferred_render_also_runs_when_the_drag_changes_nothing(tmp_path, ending):
    run_floor(tmp_path, DEFERRAL + """
const ending = ENDING;
if (ending === 'escape') pointer.key('Escape');
if (ending === 'outside') pointer.up(...OUTSIDE);
if (ending === 'own') { const [ox, oy] = free('ops'); pointer.move(ox, oy); pointer.up(ox, oy); }
assert.equal(drag, null);
assert.notEqual(floor.children, before, 'the render that waited ran');
assert.equal(deferredRenders.has(floor), false);
assert.ok(desk('dev-b').attrs.class.includes('st-blocked'));
assert.ok(desk('dev-a').attrs.class.includes('st-running'));
assert.equal(rosterDirty, false);
""".replace("ENDING", json.dumps(ending)))


def test_the_save_timeout_timer_and_roster_renders_do_not_redraw_the_floor_during_a_drag(tmp_path):
    run_floor(tmp_path, """
toggle();
const before = floor.children;
grab('sysadmin');
renderRoster(); renderFloorEdit(); renderFloor();
assert.equal(floor.children, before, 'every path to the floor render honours the drag');
timers.splice(0).forEach(fn => fn()); flushZeroTimers();
assert.equal(floor.children, before);
assert.equal(timers.filter(fn => fn.ms === 0).length, 0, 'a held render does not spin the flush timer');
pointer.key('Escape');
assert.notEqual(floor.children, before);
""")


# ---- Move to… ----------------------------------------------------------------------------------------------------------

def test_move_to_select_equals_a_drag(tmp_path):
    by_drag = run_floor(tmp_path, """
toggle(); dragTo('devops', free('remote'));
out('DRAFT', rosterDraft); out('LAYOUT', floor.querySelectorAll('.zone').map(z => [z.dataset.dept, deskIds(z.dataset.dept)]));
out('PAYLOAD', saveFromBar());
""")
    by_select = run_floor(tmp_path, """
toggle();
const select = q('[data-move-to="devops"]');
select.focus(); // the select is replaced while it holds the focus: the harness would throw on re-entrant renders
choose(select, 'remote');
out('DRAFT', rosterDraft); out('LAYOUT', floor.querySelectorAll('.zone').map(z => [z.dataset.dept, deskIds(z.dataset.dept)]));
out('PAYLOAD', saveFromBar());
""")
    for name in ("DRAFT", "LAYOUT", "PAYLOAD"):
        assert result(by_drag, name) == result(by_select, name)
    assert result(by_select) == moved("devops", "remote")
    accepted(tmp_path, result(by_select))


def test_move_to_ignores_the_placeholder_and_a_move_to_the_own_department(tmp_path):
    run_floor(tmp_path, """
toggle();
const before = floor.children;
const select = q('[data-move-to="sysadmin"]');
assert.equal(select.value, '');
choose(select, '');
choose(select, 'ops');
assert.equal(rosterDirty, false);
assert.equal(officeBar.innerHTML, CLEAN);
""")


# ---- in-place operations equal the Roster-tab operations ---------------------------------------------------------------

ROSTER_PRELUDE = """
const rroot = document.getElementById('roster-editor');
const rq = (sel, scope = rroot) => scope.querySelector(sel);
const rroom = id => rroot.querySelectorAll('[data-roster-room]').find(r => r.dataset.rosterRoom === id);
const rzone = id => rroot.querySelectorAll('[data-roster-zone]').find(z => z.dataset.rosterZone === id);
const rsave = () => { rq('[data-roster-save]').onclick(); assert.equal(posted().length, 1); return posted()[0].roster; };
const setup = () => { %s; renderAll(); out('BEFORE', rosterFromSnapshot()); };
"""

# (name, setup, in-place operation on the floor, the same operation in the Roster tab)
OPERATIONS = [
    ("room-rename", "",
     "type(q('[data-edit-room-label]', room('outpost')), 'Remote site');",
     "type(rq('[data-roster-room-label]', rroom('outpost')), 'Remote site');"),
    ("room-reorder", "",
     "q('[data-edit-room-down]', room('hq')).onclick(); q('[data-edit-room-up]', room('hq')).onclick();"
     " q('[data-edit-room-up]', room('outpost')).onclick();",
     "rq('[data-roster-room-down]', rroom('hq')).onclick(); rq('[data-roster-room-up]', rroom('hq')).onclick();"
     " rq('[data-roster-room-up]', rroom('outpost')).onclick();"),
    ("room-main", "",
     "q('[data-edit-room-main]', room('outpost')).onchange();",
     "rq('[data-roster-room-main]', rroom('outpost')).onchange();"),
    ("room-add", "",
     "q('[data-edit-open-room]').onclick(); const f = q('[data-edit-form]');"
     " type(q('[data-edit-new-id]', f), 'annex'); type(q('[data-edit-new-label]', f), 'Annex <B>'); q('[data-edit-submit]', f).onclick();"
     " assert.ok(room('annex')); assert.equal(floor.querySelectorAll('[data-edit-form]').length, 0, 'the form closes');",
     "type(rq('[data-roster-new-room]'), 'annex'); type(rq('[data-roster-new-room-label]'), 'Annex <B>');"
     " rq('[data-roster-add-room]').onclick();"),
    ("room-remove-empty", "DATA.cfg.rooms.push({id: 'annex', label: 'Annex', zones: []});",
     "q('[data-edit-room-remove]', room('annex')).onclick(); assert.equal(room('annex'), undefined);",
     "rq('[data-roster-remove-room]', rroom('annex')).onclick();"),
    ("department-add-in-room", "",
     "q('[data-edit-open-zone]', room('outpost')).onclick(); const f = q('[data-edit-form]', room('outpost'));"
     " type(q('[data-edit-new-id]', f), 'annex'); type(q('[data-edit-new-label]', f), 'Annex'); q('[data-edit-submit]', f).onclick();"
     " assert.ok(room('outpost').querySelectorAll('.zone').some(z => z.dataset.dept === 'annex'));",
     "type(rq('[data-roster-new-zone]'), 'annex'); type(rq('[data-roster-new-zone-label]'), 'Annex');"
     " choose(rq('[data-roster-new-zone-room]'), 'outpost'); rq('[data-roster-add-zone]').onclick();"),
    ("department-add-in-the-main-room", "",
     "q('[data-edit-open-zone]', room('hq')).onclick(); const f = q('[data-edit-form]', room('hq'));"
     " type(q('[data-edit-new-id]', f), 'annex'); type(q('[data-edit-new-label]', f), 'Annex'); q('[data-edit-submit]', f).onclick();",
     "type(rq('[data-roster-new-zone]'), 'annex'); type(rq('[data-roster-new-zone-label]'), 'Annex');"
     " rq('[data-roster-add-zone]').onclick();"),
    ("department-rename", "",
     "type(q('[data-edit-zone-label]', dept('lab')), 'Workshop');",
     "type(rq('[data-roster-zone-label]', rzone('lab')), 'Workshop');"),
    ("department-reorder", "",
     "q('[data-edit-zone-right]', dept('ops')).onclick(); q('[data-edit-zone-left]', dept('quarantine')).onclick();",
     "rq('[data-roster-zone-down]', rzone('ops')).onclick(); rq('[data-roster-zone-up]', rzone('quarantine')).onclick();"),
    ("department-move-to-room", "",
     "choose(q('[data-edit-zone-room]', dept('remote')), 'hq'); choose(q('[data-edit-zone-room]', dept('lab')), 'outpost');",
     "choose(rq('[data-roster-zone-room]', rzone('remote')), 'hq'); choose(rq('[data-roster-zone-room]', rzone('lab')), 'outpost');"),
    ("department-remove-empty", "DATA.cfg.rooms[1].zones.push({id: 'annex', label: 'Annex'});",
     "q('[data-edit-zone-remove]', dept('annex')).onclick(); assert.equal(dept('annex'), undefined);",
     "rq('[data-roster-remove-zone]', rzone('annex')).onclick();"),
]


@pytest.mark.parametrize("name,setup,in_place,in_roster", OPERATIONS, ids=[case[0] for case in OPERATIONS])
def test_in_place_operation_equals_the_roster_tab_operation(tmp_path, name, setup, in_place, in_roster):
    prelude = ROSTER_PRELUDE % setup
    floor_out = run_floor(tmp_path, prelude + "setup(); toggle();" + in_place + "out('PAYLOAD', saveFromBar());")
    roster_out = run_floor(tmp_path, prelude + "setup(); tab('roster');" + in_roster + "out('PAYLOAD', rsave());")
    got = result(floor_out)
    assert got == result(roster_out)
    assert got != result(floor_out, "BEFORE"), "the operation changed the roster"
    assert result(floor_out, "BEFORE") == result(roster_out, "BEFORE")
    accepted(tmp_path, got)


def test_in_place_text_edits_change_the_draft_without_rendering_and_show_the_bar(tmp_path):
    run_floor(tmp_path, """
toggle();
const input = q('[data-edit-zone-label]', dept('lab'));
const before = floor.children;
input.focus();
type(input, 'Workshop');
assert.equal(floor.children, before, 'typing does not render the floor (D8)');
assert.equal(document.activeElement, input);
assert.equal(rosterDraft.rooms[0].zones[2].label, 'Workshop');
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'), 'the bar follows while typing');
// a snapshot arrives while the field has the focus: the render waits for the focus to leave
send({pixelhq: snap()});
assert.equal(floor.children, before);
assert.ok(deferredRenders.has(floor));
assert.equal(input.value, 'Workshop');
input.blur(); flushZeroTimers();
assert.notEqual(floor.children, before, 'rendered after the focus left');
assert.equal(q('[data-edit-zone-label]', dept('lab')).value, 'Workshop', 'the typed name survives the render');
""")


def test_room_and_department_forms_report_problems_in_the_bar_and_keep_what_was_typed(tmp_path):
    run_floor(tmp_path, """
toggle();
q('[data-edit-open-zone]', room('hq')).onclick();
assert.equal(document.activeElement, q('[data-edit-new-id]', room('hq')), 'the id field gets the focus');
let f = q('[data-edit-form]', room('hq'));
type(q('[data-edit-new-id]', f), 'bad.id'); type(q('[data-edit-new-label]', f), 'Annex');
q('[data-edit-submit]', f).onclick();
assert.ok(officeBar.innerHTML.includes('Department id: use 1–64 ASCII letters'), officeBar.innerHTML);
assert.ok(officeBar.innerHTML.includes('layout-result bad'));
assert.equal(rosterDirty, false);
f = q('[data-edit-form]', room('hq'));
assert.ok(f, 'the form stays open');
assert.equal(q('[data-edit-new-id]', f).value, 'bad.id');
assert.equal(q('[data-edit-new-label]', f).value, 'Annex');
type(q('[data-edit-new-id]', f), 'ops');
q('[data-edit-submit]', f).onclick();
assert.ok(officeBar.innerHTML.includes('Department id already exists.'));
q('[data-edit-cancel]', q('[data-edit-form]', room('hq'))).onclick();
assert.equal(floor.querySelectorAll('[data-edit-form]').length, 0);
q('[data-edit-open-room]').onclick();
f = q('[data-edit-form]');
type(q('[data-edit-new-id]', f), 'hq'); q('[data-edit-submit]', f).onclick();
assert.ok(officeBar.innerHTML.includes('Room id already exists.'));
""")


def test_refused_operations_change_nothing(tmp_path):
    run_floor(tmp_path, """
toggle();
const saved = JSON.stringify(rosterDraft);
assert.equal(q('[data-edit-room-remove]', room('hq')).disabled, true, 'the main room cannot be removed');
assert.equal(q('[data-edit-room-remove]', room('outpost')).disabled, true, 'a room with departments cannot be removed');
assert.equal(q('[data-edit-zone-remove]', dept('ops')).disabled, true, 'a department with bots cannot be removed');
assert.equal(q('[data-edit-room-up]', room('hq')).disabled, true);
assert.equal(q('[data-edit-zone-left]', dept('command')).disabled, true);
q('[data-edit-room-remove]', room('hq')).onclick();
q('[data-edit-room-remove]', room('outpost')).onclick();
q('[data-edit-zone-remove]', dept('ops')).onclick();
q('[data-edit-room-up]', room('hq')).onclick();
q('[data-edit-zone-left]', dept('command')).onclick();
choose(q('[data-edit-zone-room]', dept('ops')), '');
assert.equal(JSON.stringify(rosterDraft), saved);
assert.equal(officeBar.innerHTML, CLEAN);
""")


def test_the_roster_tab_and_the_floor_work_on_one_draft(tmp_path):
    run_floor(tmp_path, """
toggle();
type(q('[data-edit-zone-label]', dept('lab')), 'Workshop');
tab('roster');
const rroot = document.getElementById('roster-editor');
const zoneRow = rroot.querySelectorAll('[data-roster-zone]').find(z => z.dataset.rosterZone === 'lab');
assert.equal(zoneRow.querySelector('[data-roster-zone-label]').value, 'Workshop', 'the Roster tab shows the floor edit');
assert.ok(rosterBar.innerHTML.includes('Unsaved layout changes'));
// a structural edit in the Roster tab shows on the floor at once, a typed one when the Office tab is opened again
zoneRow.querySelector('[data-roster-zone-room]').value = 'outpost'; zoneRow.querySelector('[data-roster-zone-room]').onchange();
assert.ok(room('outpost').querySelectorAll('.zone').some(z => z.dataset.dept === 'lab'));
const rowAgain = rroot.querySelectorAll('[data-roster-zone]').find(z => z.dataset.rosterZone === 'lab');
type(rowAgain.querySelector('[data-roster-zone-label]'), 'Workshop 2');
tab('office');
assert.equal(q('[data-edit-zone-label]', dept('lab')).value, 'Workshop 2');
// the bot moved by a drag is shown in the Roster tab's department select
dragTo('sysadmin', free('command'));
tab('roster');
const botRow = rroot.querySelectorAll('[data-roster-bot]').find(b => b.querySelector('[data-roster-id]').value === 'sysadmin');
assert.equal(botRow.querySelector('[data-roster-field="zone"]').value, 'command');
""")


# ---- the bar: Save and Discard ------------------------------------------------------------------------------------------

def test_save_from_the_bar_is_the_roster_round_trip_post_first(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
let barAtPost = null; const original = window.parent.postMessage;
window.parent.postMessage = message => { if (message.pixelhqRoster) barAtPost = officeBar.innerHTML; original(message); };
const payload = saveFromBar();
assert.ok(!barAtPost.includes('Saving roster'), 'the request is posted before the render (D16c)');
assert.deepEqual(payload.bots.find(b => b.id === 'sysadmin').zone, 'lab');
for (const bar of [officeBar, rosterBar]) {
  assert.ok(bar.innerHTML.includes('Saving roster'), 'busy on both bars');
  assert.ok(q('[data-layout-save]', bar).disabled && q('[data-layout-discard]', bar).disabled);
}
assert.equal(q('[data-move-to="devops"]').disabled, true, 'the floor is locked while saving');
assert.equal(q('[data-edit-zone-label]', dept('lab')).disabled, true);
const [x, y] = mid(desk('devops')); pointer.down(x, y); pointer.move(x + 20, y + 20);
assert.equal(drag, null, 'no drag while saving');
q('[data-layout-save]', officeBar).onclick();
assert.equal(posted().length, 1, 'a second Save while busy sends nothing');
send({pixelhqRosterResult: {ok: true, message: 'Roster saved.'}});
assert.equal(rosterDirty, false);
assert.ok(!officeBar.innerHTML.includes('Unsaved'));
assert.ok(officeBar.innerHTML.includes('layout-result ok') && officeBar.innerHTML.includes('Roster saved.'), officeBar.innerHTML);
assert.equal(rosterBar.innerHTML, officeBar.innerHTML);
assert.deepEqual(deskIds('lab').includes('sysadmin'), true, 'edit mode shows the saved placement before the new snapshot arrives');
assert.equal(q('[data-move-to="devops"]').disabled, false);
// the host sends the fresh snapshot: the floor follows it
const fresh = snap(); fresh.bots.find(b => b.id === 'sysadmin').zone = 'lab'; send({pixelhq: fresh});
assert.ok(deskIds('lab').includes('sysadmin'));
""")


def test_a_refused_save_keeps_the_draft_and_the_bar(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
saveFromBar();
send({pixelhqRosterResult: {ok: false, message: 'Roster refused: sample reason.'}});
assert.equal(rosterDirty, true);
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'));
assert.ok(officeBar.innerHTML.includes('layout-result bad') && officeBar.innerHTML.includes('Roster refused: sample reason.'));
assert.equal(draftBot('sysadmin').zone, 'lab');
assert.ok(deskIds('lab').includes('sysadmin'));
dragTo('devops', free('lab'));
assert.ok(!officeBar.innerHTML.includes('Roster refused'), 'the next change clears the old result');
""")


def test_the_save_from_the_roster_tab_bar_and_the_editor_button_send_the_same_roster(tmp_path):
    bar = run_floor(tmp_path, "toggle(); dragTo('sysadmin', free('lab')); tab('roster'); out('PAYLOAD', saveFromBar(rosterBar));")
    button = run_floor(tmp_path, "toggle(); dragTo('sysadmin', free('lab')); tab('roster');"
                                 "document.getElementById('roster-editor').querySelector('[data-roster-save]').onclick();"
                                 "out('PAYLOAD', posted()[0].roster);")
    assert result(bar) == result(button) == moved("sysadmin", "lab")


def test_discard_is_a_two_click_button_that_returns_to_the_saved_roster(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
const saved = JSON.stringify(rosterFromSnapshot());
let discard = q('[data-layout-discard]', officeBar);
discard.onclick();
assert.equal(discard.dataset.armed, '1', 'the first click only arms the button');
assert.equal(discard.textContent, 'Confirm: discard?');
assert.equal(draftBot('sysadmin').zone, 'lab');
timers.splice(0).forEach(fn => fn());
assert.equal(discard.dataset.armed, '', 'it disarms by itself');
assert.equal(discard.textContent, 'Discard');
assert.equal(draftBot('sysadmin').zone, 'lab');
discard.onclick(); discard.onclick();
assert.equal(JSON.stringify(rosterDraft), saved);
assert.equal(rosterDirty, false);
assert.equal(officeBar.innerHTML, CLEAN);
assert.equal(rosterBar.innerHTML, CLEAN);
assert.ok(deskIds('ops').includes('sysadmin') && !deskIds('lab').includes('sysadmin'), 'the floor is back at the saved roster');
assert.equal(posted().length, 0, 'Discard sends nothing');
// after a Save the base is the saved roster, not the snapshot
dragTo('sysadmin', free('lab')); saveFromBar();
send({pixelhqRosterResult: {ok: true, message: 'Roster saved.'}});
dragTo('devops', free('lab'));
q('[data-layout-discard]', officeBar).onclick(); q('[data-layout-discard]', officeBar).onclick();
assert.equal(draftBot('sysadmin').zone, 'lab', 'Discard returns to the last saved roster');
assert.equal(draftBot('devops').zone, 'ops');
""")


def test_the_bar_is_not_redrawn_while_its_content_is_unchanged_so_an_armed_button_stays_armed(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
const discard = q('[data-layout-discard]', officeBar);
discard.onclick();
send({pixelhq: snap()}); send({pixelhqLive: {generated: 10, bots: {}}}); renderAll();
assert.equal(q('[data-layout-discard]', officeBar), discard, 'the same button');
assert.equal(discard.dataset.armed, '1');
""")


def test_a_reverted_change_hides_the_bar(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
assert.ok(officeBar.innerHTML.includes('Unsaved'));
dragTo('sysadmin', free('ops'));
assert.equal(officeBar.innerHTML, CLEAN, 'the draft equals the saved roster again');
""")


def test_a_clean_draft_follows_new_snapshots_and_a_changed_one_keeps_its_placement(tmp_path):
    run_floor(tmp_path, """
toggle();
const moved = id => { const copy = snap(); copy.bots.find(b => b.id === id).zone = 'lab'; return copy; };
send({pixelhq: moved('netadmin')});
assert.ok(deskIds('lab').includes('netadmin'), 'a clean draft follows the snapshot');
dragTo('sysadmin', free('command'));
send({pixelhq: moved('devops')});
assert.ok(deskIds('command').includes('sysadmin'), 'the unsaved placement survives the snapshot');
assert.ok(deskIds('ops').includes('devops'), 'and so does the rest of the draft');
""")


def test_the_standalone_page_with_actions_reports_that_nothing_was_sent(tmp_path):
    run_floor(tmp_path, """
toggle(); dragTo('sysadmin', free('lab'));
q('[data-layout-save]', officeBar).onclick();
assert.equal(posted().length, 0);
assert.ok(officeBar.innerHTML.includes('standalone page: no host, nothing was sent'), officeBar.innerHTML);
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'));
""", iframe=False, actions="?actions=1")


# ---- sources -----------------------------------------------------------------------------------------------------------

def test_the_sources_use_no_html5_drag_and_drop():
    sources = [page.bundle_js(), (ROOT / "pixelhq" / "ui" / "index.html").read_text(encoding="utf-8")]
    sources += [p.read_text(encoding="utf-8") for p in (ROOT / "pixelhq" / "ui" / "js").glob("*.js")]
    for text in sources:
        assert not re.search(r"draggable|dragstart|dragover|dragenter|ondrop\b|dataTransfer", text, re.I)
        assert not re.search(r"\bdrop\s*\(", text)


def test_the_floor_styles_stop_scrolling_and_text_selection_while_dragging():
    css = (ROOT / "pixelhq" / "ui" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"#floor\.editing \.desk\{([^}]*)\}", css)
    assert rule and "touch-action:none" in rule.group(1) and "user-select:none" in rule.group(1)
    assert re.search(r"\.drag-ghost\{[^}]*pointer-events:none", css)
