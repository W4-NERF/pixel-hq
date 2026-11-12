"""D8/D9: periodic renders never replace a container that holds the focused field; the roster editor keeps its base.

Executed in the plain-Node DOM model (tests/ui_dom.cjs), not a browser: `focus()`/`blur()` there set
`document.activeElement` and fire `focusout` with a `relatedTarget`, like the browser events the
page listens to. The deferred render runs from a 0 ms timer (D16), so these tests call `flushZeroTimers()` after the blur.
"""
import pytest

from tests.test_roster_ui import run_roster

LIVE_SETUP = """
const bot = DATA.bots[0];
const liveWith = title => ({generated:10, bots:{[bot.id]:{active:true, tasks:[], sessions:[
  {id:'sample-session', title, source:'desktop', startedAt:1, lastAt:2, msgs:3, toolCalls:1, inTok:0, outTok:0}]}}});
const send = data => listeners.get('message')({source:window.parent, data});
send({pixelhq:DATA}); send({pixelhqLive:liveWith('First title')});
const live = document.getElementById('lactive');
live.querySelector('[data-rate="pass"]').onclick();
const ref = live.querySelector('[data-review-ref]');
"""

BLOCKED_SETUP = """
const bot = DATA.bots[0];
const blocker = reason => ({board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:bot.id,
  cat:'you', ageDays:1, openParents:[], actions:['answer','comment'], reason});
const send = data => listeners.get('message')({source:window.parent, data});
const withBlocker = reason => ({...DATA, blockers:[blocker(reason)]});
send({pixelhq:withBlocker('First reason')});
const list = document.getElementById('blist');
const area = list.querySelector('[data-ta]');
"""

ROSTER_SETUP = """
const send = data => listeners.get('message')({source:window.parent, data});
const withTitle = title => { const copy = JSON.parse(JSON.stringify(DATA)); copy.bots[1].title = title; return copy; };
send({pixelhq:DATA}); tab('roster');
const editor = document.getElementById('roster-editor');
const titleField = () => editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]');
"""


def test_live_review_form_keeps_the_focused_field_across_every_periodic_message(tmp_path):
    run_roster(tmp_path, LIVE_SETUP + """
ref.focus(); ref.value = 'typed note'; ref.oninput();
send({pixelhqLive:liveWith('Second title')});
assert.equal(live.querySelector('[data-review-ref]'), ref, 'live message');
send({pixelhq:{...DATA, generated:DATA.generated + 60}});
assert.equal(live.querySelector('[data-review-ref]'), ref, 'snapshot message');
send({pixelhqTheme:{mode:'light'}});
assert.equal(live.querySelector('[data-review-ref]'), ref, 'theme message');
assert.ok(live.innerHTML.includes('First title') && !live.innerHTML.includes('Second title'));
""", iframe=True)


def test_live_render_runs_after_blur_and_keeps_the_typed_value(tmp_path):
    run_roster(tmp_path, LIVE_SETUP + """
ref.focus(); ref.value = 'typed note'; ref.oninput();
send({pixelhqLive:liveWith('Second title')});
assert.ok(!live.innerHTML.includes('Second title'));
ref.blur(); flushZeroTimers();
assert.ok(live.innerHTML.includes('Second title'), 'deferred render must run once the flush timer fires');
const fresh = live.querySelector('[data-review-ref]');
assert.notEqual(fresh, ref);
assert.equal(fresh.value, 'typed note', 'the draft survives the deferred render');
send({pixelhqLive:liveWith('Third title')});
assert.ok(live.innerHTML.includes('Third title'), 'no field is focused any more: render immediately');
""", iframe=True)


def test_focus_moving_inside_the_container_stays_deferred_until_it_leaves(tmp_path):
    run_roster(tmp_path, LIVE_SETUP + """
const dim = live.querySelector('[data-review-dim="safety"]');
ref.focus(); send({pixelhqLive:liveWith('Second title')});
dim.focus();
assert.ok(!live.innerHTML.includes('Second title'), 'tabbing to another field must not render');
assert.equal(live.querySelector('[data-review-dim="safety"]'), dim);
dim.blur(); flushZeroTimers();
assert.ok(live.innerHTML.includes('Second title'));
""", iframe=True)


def test_a_focused_button_does_not_hold_back_renders(tmp_path):
    run_roster(tmp_path, LIVE_SETUP + """
const confirm = live.querySelector('[data-review-confirm]');
confirm.focus(); send({pixelhqLive:liveWith('Second title')});
assert.ok(live.innerHTML.includes('Second title'));
""", iframe=True)


def test_review_form_in_the_character_card_is_guarded_too(tmp_path):
    run_roster(tmp_path, """
const send = data => listeners.get('message')({source:window.parent, data});
send({pixelhq:DATA});
const card = document.getElementById('detail');
card.querySelector('[data-rate="fail"]').onclick();
const ref = card.querySelector('[data-review-ref]'); ref.focus();
const changed = JSON.parse(JSON.stringify(DATA)); changed.bots.find(b => b.id === sel).lvl = 99;
send({pixelhq:changed});
assert.equal(card.querySelector('[data-review-ref]'), ref);
ref.blur(); flushZeroTimers();
assert.notEqual(card.querySelector('[data-review-ref]'), ref);
assert.ok(card.innerHTML.includes('>99<'));
""", iframe=True)


def test_blocked_text_area_keeps_focus_identity_and_draft(tmp_path):
    run_roster(tmp_path, BLOCKED_SETUP + """
area.focus(); area.value = 'answer in progress'; area.oninput();
send({pixelhq:withBlocker('Second reason')});
assert.equal(list.querySelector('[data-ta]'), area, 'snapshot message');
send({pixelhqTheme:{mode:'light'}});
assert.equal(list.querySelector('[data-ta]'), area, 'theme message');
assert.ok(list.innerHTML.includes('First reason') && !list.innerHTML.includes('Second reason'));
area.blur(); flushZeroTimers();
assert.ok(list.innerHTML.includes('Second reason'));
const fresh = list.querySelector('[data-ta]');
assert.notEqual(fresh, area);
assert.equal(fresh.value, 'answer in progress');
""", iframe=True)


def test_blocked_tab_chrome_still_updates_while_the_list_waits(tmp_path):
    run_roster(tmp_path, BLOCKED_SETUP + """
area.focus();
send({pixelhq:{...withBlocker('Second reason'), blockers:[blocker('Second reason'), {...blocker('x'), id:'t_abcdef02'}]}});
assert.equal(document.getElementById('blktab').textContent, 'Blocked (2)');
assert.equal(list.querySelectorAll('[data-ta]').length, 1, 'list itself is deferred');
area.blur(); flushZeroTimers();
assert.equal(list.querySelectorAll('[data-ta]').length, 2);
""", iframe=True)


def test_roster_editor_keeps_the_focused_field_for_clean_and_dirty_drafts(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
let field = titleField(); field.focus();
send({pixelhq:withTitle('Server title')});
assert.equal(titleField(), field, 'clean editor, snapshot');
send({pixelhqTheme:{mode:'light'}});
assert.equal(titleField(), field, 'clean editor, theme');
field.blur(); flushZeroTimers();
assert.notEqual(titleField(), field);
assert.equal(titleField().value, 'Server title', 'a clean editor follows the snapshot after blur');
field = titleField(); field.focus(); field.value = 'My title'; field.oninput();
send({pixelhq:withTitle('Other server title')});
assert.equal(titleField(), field, 'dirty editor, snapshot');
field.blur(); flushZeroTimers();
assert.equal(titleField().value, 'My title', 'a dirty draft is never replaced');
""", iframe=True)


def test_roster_select_holds_the_render_too_but_user_driven_renders_do_not_wait(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
const row = () => editor.querySelectorAll('[data-roster-bot]')[1];
const select = row().querySelector('[data-roster-field="sprite"]'); select.focus();
send({pixelhq:withTitle('Server title')});
assert.equal(row().querySelector('[data-roster-field="sprite"]'), select);
const zone = row().querySelector('[data-roster-field="zone"]'); zone.focus();
zone.value = DATA.cfg.rooms.flatMap(r => r.zones)[0].id; zone.onchange();
assert.notEqual(row().querySelector('[data-roster-field="zone"]'), zone, 'a zone change re-renders immediately');
""", iframe=True)


def test_failed_follow_up_snapshot_does_not_revert_the_editor_to_pre_save_values(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
const title = titleField(); title.value = 'Saved title'; title.oninput();
editor.querySelector('[data-roster-save]').onclick();
const saved = messages.filter(m => m.pixelhqRoster).at(-1).pixelhqRoster;
assert.equal(saved.roster.bots[1].title, 'Saved title');
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
assert.equal(titleField().value, 'Saved title');
send({pixelhqError:'sample refresh failure'});
assert.equal(titleField().value, 'Saved title', 'failed follow-up snapshot');
send({pixelhqTheme:{mode:'light'}});
assert.equal(titleField().value, 'Saved title', 'a later theme render');
assert.equal(rosterDirty, false);
editor.querySelector('[data-roster-save]').onclick();
const again = messages.filter(m => m.pixelhqRoster).at(-1).pixelhqRoster;
assert.deepEqual(again, saved, 'a second Save writes the saved roster, not the old one');
""", iframe=True)


def test_new_snapshot_replaces_the_saved_base_only_while_the_editor_is_clean(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
let title = titleField(); title.value = 'Saved title'; title.oninput();
editor.querySelector('[data-roster-save]').onclick();
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
send({pixelhq:withTitle('Fresh from server')});
assert.equal(titleField().value, 'Fresh from server', 'clean editor takes the fresh snapshot');
title = titleField(); title.value = 'Unsaved edit'; title.oninput();
send({pixelhq:withTitle('Newer from server')});
assert.equal(titleField().value, 'Unsaved edit', 'dirty editor keeps its draft');
""", iframe=True)


def test_rejected_save_keeps_the_draft_and_does_not_become_the_base(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
const title = titleField(); title.value = 'Rejected title'; title.oninput();
editor.querySelector('[data-roster-save]').onclick();
send({pixelhqRosterResult:{ok:false, message:'bots[1].title: too long'}});
assert.equal(rosterDirty, true);
assert.equal(titleField().value, 'Rejected title');
send({pixelhq:withTitle('Server title')});
assert.equal(titleField().value, 'Rejected title');
""", iframe=True)


def test_reset_clears_the_saved_base(tmp_path):
    run_roster(tmp_path, ROSTER_SETUP + """
const title = titleField(); title.value = 'Saved title'; title.oninput();
editor.querySelector('[data-roster-save]').onclick();
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
const reset = editor.querySelector('[data-roster-reset]'); reset.onclick(); reset.onclick();
send({pixelhqRosterResult:{ok:true, message:'Roster reset to generated.'}});
send({pixelhq:withTitle('Generated title')});
assert.equal(titleField().value, 'Generated title');
""", iframe=True)


@pytest.mark.parametrize("container", ["blist"])
def test_deferred_render_is_dropped_once_the_container_renders_for_another_reason(tmp_path, container):
    run_roster(tmp_path, """
const send = data => listeners.get('message')({source:window.parent, data});
send({pixelhq:DATA});
const el = document.getElementById(CONTAINER);
let runs = 0; const field = new Element('input', {}); field.parentNode = el;
document.activeElement = field;
renderUnlessFocused(el, () => { runs++; });
assert.equal(runs, 0);
document.activeElement = null;
renderUnlessFocused(el, () => { runs++; });
assert.equal(runs, 1);
fire('focusout', {target:field, relatedTarget:null});
assert.equal(runs, 1, 'the stale deferral must not run a second time');
""".replace("CONTAINER", repr(container)), iframe=True)
