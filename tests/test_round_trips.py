"""D10: one pending/result helper with UI timeouts (injectable clock) and one armed-button helper.

Executed in the plain-Node DOM model. `hostClock.now` is replaced by a fake clock and the harness collects timers in
`timers` instead of running them, so nothing sleeps: a test advances `now` and fires the collected timers by hand.
"""
import re
from pathlib import Path

import pytest

from pixelhq import page
from tests.test_roster_ui import run_roster

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = "no answer from the host (timeout)"

CLOCK = """
let now = 0, queue = [];
hostClock.now = () => now;
hostClock.later = (fn, ms) => { queue.push({fn, due:now + ms}); };
const advance = ms => { now += ms; const due = queue.filter(t => t.due <= now); queue = queue.filter(t => t.due > now); due.forEach(t => t.fn()); };
const send = data => listeners.get('message')({source:window.parent, data});
send({pixelhq:DATA});
const bot = DATA.bots[0];
"""


def run(tmp_path, probe):
    return run_roster(tmp_path, CLOCK + probe, iframe=True)


@pytest.mark.parametrize("limit_ms", [20000])
def test_review_round_trip_times_out_after_20_s_and_can_be_retried(tmp_path, limit_ms):
    run(tmp_path, """
const card = document.getElementById('detail'), review = () => card.querySelector('[data-review]');
card.querySelector('[data-rate="pass"]').onclick();
card.querySelector('[data-review-ref]').value = 'kept draft'; card.querySelector('[data-review-ref]').oninput();
card.querySelector('[data-review-confirm]').onclick();
assert.equal(messages.filter(m => m.pixelhqReview).length, 1);
assert.equal(card.querySelector('[data-rate="pass"]').disabled, true);
advance(LIMIT - 1);
assert.equal(card.querySelector('[data-rate="pass"]').disabled, true, 'still waiting just before the limit');
assert.ok(!review().innerHTML.includes(TIMEOUT));
advance(1);
assert.ok(review().innerHTML.includes('res bad') && review().innerHTML.includes(TIMEOUT));
assert.equal(card.querySelector('[data-rate="pass"]').disabled, false);
assert.equal(card.querySelector('[data-review-ref]').value, 'kept draft', 'the unsent draft survives');
card.querySelector('[data-review-confirm]').onclick();
assert.equal(messages.filter(m => m.pixelhqReview).length, 2, 'controls work again');
""".replace("LIMIT", str(limit_ms)).replace("TIMEOUT", repr(TIMEOUT)))


def test_review_answer_before_the_limit_wins_and_the_late_timer_is_harmless(tmp_path):
    run(tmp_path, """
const card = document.getElementById('detail'), review = () => card.querySelector('[data-review]');
card.querySelector('[data-rate="pass"]').onclick(); card.querySelector('[data-review-confirm]').onclick();
advance(5000);
send({pixelhqReviewResult:{ok:true, message:'Review saved.', agent:bot.id, sessionId:null}});
assert.ok(review().innerHTML.includes('Review saved.'));
advance(60000);
assert.ok(review().innerHTML.includes('Review saved.') && !review().innerHTML.includes(TIMEOUT));
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_jump_round_trip_times_out_after_20_s_and_a_late_answer_replaces_the_timeout_line(tmp_path):
    run(tmp_path, """
const session = {id:'sample-session', title:'Sample', source:'desktop', startedAt:1, lastAt:2, msgs:1, toolCalls:0, inTok:0, outTok:0};
send({pixelhqLive:{generated:10, bots:{[bot.id]:{active:true, tasks:[], sessions:[session]}}}});
const live = document.getElementById('lactive'), jumpRow = () => live.querySelector('[data-jump-row]');
live.querySelector('[data-jump="Open"]').onclick();
assert.equal(messages.filter(m => m.pixelhqOpen).length, 1);
advance(19999);
assert.equal(live.querySelector('[data-jump="Open"]').disabled, true);
advance(1);
assert.equal(live.querySelector('[data-jump="Open"]').disabled, false);
assert.ok(jumpRow().innerHTML.includes('res bad') && jumpRow().innerHTML.includes(TIMEOUT));
send({pixelhqOpenResult:{ok:true, message:'Session opened', sessionId:'other-session'}});
assert.ok(jumpRow().innerHTML.includes(TIMEOUT), 'an answer for another session does not rewrite the row');
send({pixelhqOpenResult:{ok:true, message:'Session opened', sessionId:'sample-session'}});
assert.ok(jumpRow().innerHTML.includes('res ok') && jumpRow().innerHTML.includes('Session opened'));
assert.ok(!jumpRow().innerHTML.includes(TIMEOUT), 'the late answer replaces the timeout line');
send({pixelhqOpenResult:{ok:false, message:'Second answer', sessionId:'sample-session'}});
assert.ok(!jumpRow().innerHTML.includes('Second answer'), 'a second answer for the same trip is unsolicited');
live.querySelector('[data-jump="Open"]').onclick();
assert.equal(messages.filter(m => m.pixelhqOpen).length, 2);
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_chat_round_trip_times_out_too(tmp_path):
    run(tmp_path, """
const card = document.getElementById('detail'), review = () => card.querySelector('[data-review]');
card.querySelector('[data-jump="Chat"]').onclick();
advance(20000);
assert.equal(card.querySelector('[data-jump="Chat"]').disabled, false);
assert.ok(card.querySelector('[data-jump-row]').innerHTML.includes(TIMEOUT));
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_roster_round_trip_times_out_after_20_s_keeps_the_draft_and_takes_a_late_answer(tmp_path):
    run(tmp_path, """
tab('roster');
const editor = document.getElementById('roster-editor');
const title = editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]');
title.value = 'Edited title'; title.oninput();
editor.querySelector('[data-roster-save]').onclick();
assert.equal(editor.querySelector('[data-roster-controls]').disabled, true);
advance(19999);
assert.equal(editor.querySelector('[data-roster-controls]').disabled, true);
advance(1);
assert.equal(editor.querySelector('[data-roster-controls]').disabled, false);
assert.ok(editor.innerHTML.includes('res bad') && editor.innerHTML.includes(TIMEOUT));
assert.equal(editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]').value, 'Edited title');
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
assert.ok(editor.innerHTML.includes('Roster saved.') && editor.innerHTML.includes('res ok'));
assert.ok(!editor.innerHTML.includes(TIMEOUT), 'the late answer replaces the timeout line');
assert.equal(rosterDirty, false, 'the unchanged draft is now the saved base');
assert.equal(rosterSaved.bots[1].title, 'Edited title');
assert.equal(editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]').value, 'Edited title');
send({pixelhqRosterResult:{ok:false, message:'Second answer'}});
assert.ok(!editor.innerHTML.includes('Second answer'), 'an answer without a waiting trip is ignored');
editor.querySelector('[data-roster-save]').onclick();
assert.equal(messages.filter(m => m.pixelhqRoster).length, 2);
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_roster_reset_round_trip_also_times_out(tmp_path):
    run(tmp_path, """
tab('roster');
const editor = document.getElementById('roster-editor');
const reset = editor.querySelector('[data-roster-reset]'); reset.onclick(); reset.onclick();
assert.deepEqual(messages.filter(m => m.pixelhqRoster).map(m => ({...m.pixelhqRoster, rid: typeof m.pixelhqRoster.rid})),
  [{reset:true, rid:'string'}]);
advance(20000);
assert.equal(editor.querySelector('[data-roster-controls]').disabled, false);
assert.ok(editor.innerHTML.includes(TIMEOUT));
""".replace("TIMEOUT", repr(TIMEOUT)))


ACTION = """
const blocker = {board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:bot.id, cat:'you', ageDays:1,
  openParents:[], actions:['comment'], reason:'Sample reason'};
send({pixelhq:{...DATA, blockers:[blocker]}});
const list = document.getElementById('blist');
drafts['platform/t_abcdef01'] = 'Sample comment';
list.querySelector('[data-act="comment"]').onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 1);
"""


def test_kanban_action_waits_75_s_before_timing_out(tmp_path):
    run(tmp_path, ACTION + """
advance(20000); advance(20000); advance(34999);
assert.equal(list.querySelector('[data-act="comment"]').disabled, true, 'still pending at 74.999 s');
assert.ok(!list.innerHTML.includes(TIMEOUT));
advance(1);
assert.equal(list.querySelector('[data-act="comment"]').disabled, false);
assert.ok(list.innerHTML.includes('res bad') && list.innerHTML.includes(TIMEOUT));
assert.equal(lastRes[0].text, TIMEOUT);
assert.equal(drafts['platform/t_abcdef01'], 'Sample comment', 'the typed text is kept for a retry');
list.querySelector('[data-act="comment"]').onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 2);
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_kanban_action_answered_in_time_is_not_overwritten_by_the_timer(tmp_path):
    run(tmp_path, ACTION + """
advance(30000);
send({pixelhqActionResult:{board:'platform', id:'t_abcdef01', ok:true, message:'Comment added'}});
advance(60000);
assert.ok(list.innerHTML.includes('Comment added') && !list.innerHTML.includes(TIMEOUT));
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_triage_round_trip_times_out_after_20_s(tmp_path):
    run(tmp_path, """
send({pixelhq:{...DATA, blockers:[{board:'platform', id:'t_abcdef01', title:'Sample', assignee:bot.id, cat:'you',
  ageDays:1, openParents:[], actions:[], reason:'Sample reason'}]}});
const button = document.getElementById('btriage');
button.onclick(); button.onclick();
assert.equal(messages.filter(m => m.pixelhqTriage).length, 1);
assert.equal(button.disabled, true); assert.equal(button.textContent, 'Starting triage …');
advance(19999); assert.equal(button.disabled, true);
advance(1);
assert.equal(button.disabled, false);
assert.equal(lastRes[0].ok, false); assert.equal(lastRes[0].text, TIMEOUT);
assert.ok(document.getElementById('bres').innerHTML.includes(TIMEOUT));
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_trip_helper_contract_clock_and_independent_keys(tmp_path):
    run(tmp_path, """
const expired = [];
const trips = hostTrips(1000, (key, info) => expired.push([key, info]));
trips.start('a', {n:1}); advance(400); trips.start('b', {n:2});
advance(599); assert.deepEqual(expired, []);
advance(1); assert.deepEqual(expired, [['a', {n:1}]]);
assert.equal(trips.busy('a'), false); assert.equal(trips.busy('b'), true);
assert.deepEqual(trips.result('a'), {ok:false, message:TIMEOUT});
advance(399); assert.deepEqual(expired.map(e => e[0]), ['a']);
advance(1); assert.deepEqual(expired.map(e => e[0]), ['a', 'b']);
assert.deepEqual(trips.waiting().map(e => e[0]), ['a', 'b'], 'timed-out trips still wait for a late answer');
assert.equal(trips.finish('a', {ok:true, message:'late'}), true, 'a timed-out key can still be finished (D21)');
assert.deepEqual(trips.result('a'), {ok:true, message:'late'});
assert.equal(trips.finish('a', {ok:false}), false, 'a second answer for the same trip is rejected');
assert.equal(trips.finish('never-started', {ok:true}), false);
assert.deepEqual(trips.result('a'), {ok:true, message:'late'});
trips.start('c'); assert.equal(trips.finish('c', {ok:true, message:'x'}), true);
assert.deepEqual(trips.result('c'), {ok:true, message:'x'});
advance(5000); assert.deepEqual(trips.result('c'), {ok:true, message:'x'}, 'a finished trip never times out');
trips.start('c'); assert.equal(trips.result('c'), undefined, 'a new trip clears the previous result');
assert.equal(TRIP_MS.action, 75000); assert.equal(TRIP_MS.other, 20000);
""".replace("TIMEOUT", repr(TIMEOUT)))


def test_standalone_submit_finishes_the_trip_immediately_without_a_timer_effect(tmp_path):
    run_roster(tmp_path, """
let now = 0; hostClock.now = () => now;
const bot = DATA.bots[0]; detail(bot);
const card = document.getElementById('detail'), review = () => card.querySelector('[data-review]');
card.querySelector('[data-rate="pass"]').onclick(); card.querySelector('[data-review-confirm]').onclick();
assert.ok(card.querySelector('[data-review]').innerHTML.includes('standalone page: no host, nothing was sent'));
now += 100000; timers.splice(0).forEach(fn => fn());
assert.ok(!card.querySelector('[data-review]').innerHTML.includes('no answer from the host'));
""", actions="?actions=1")


ARM = """
const button = new Element('button', {});
button.textContent = 'Archive'; button.classList.add('btn');
let runs = 0;
const click = () => armedButton(button, () => 'Archive', 'Confirm: Archive?', () => { runs++; });
"""


def test_armed_button_two_clicks_run_once_and_clear_the_armed_state(tmp_path):
    run(tmp_path, ARM + """
click();
assert.equal(runs, 0); assert.equal(button.dataset.armed, '1');
assert.equal(button.textContent, 'Confirm: Archive?'); assert.ok(button.classList.contains('armed'));
click();
assert.equal(runs, 1); assert.notEqual(button.dataset.armed, '1'); assert.ok(!button.classList.contains('armed'));
click(); assert.equal(runs, 1, 'a third click arms again instead of running');
""")


def test_armed_button_expires_after_6_s_and_restores_the_current_label(tmp_path):
    run(tmp_path, ARM + """
let label = 'Archive'; const armedClick = () => armedButton(button, () => label, 'Confirm?', () => { runs++; });
armedClick(); label = 'Archive (3 cards)';
advance(6000);
assert.notEqual(button.dataset.armed, '1'); assert.ok(!button.classList.contains('armed'));
assert.equal(button.textContent, 'Archive (3 cards)');
armedClick(); assert.equal(runs, 0, 'after expiry the next click only arms again');
""")


def test_armed_button_replaced_by_a_render_is_left_alone(tmp_path):
    run(tmp_path, ARM + """
click(); button.isConnected = false; button.textContent = 'rendered elsewhere';
advance(6000);
assert.equal(button.textContent, 'rendered elsewhere');
""")


@pytest.mark.parametrize("kind", ["archive", "retry", "answer"])
def test_kanban_confirm_buttons_use_the_shared_armed_helper(tmp_path, kind):
    run(tmp_path, """
const blocker = {board:'platform', id:'t_abcdef01', title:'Sample', assignee:bot.id, cat:'you', ageDays:1,
  openParents:[], actions:[KIND], reason:'Sample'};
send({pixelhq:{...DATA, blockers:[blocker]}});
drafts['platform/t_abcdef01'] = 'Sample answer';
const list = document.getElementById('blist'), button = list.querySelector('[data-act]');
button.onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 0);
assert.ok(button.textContent.startsWith('Confirm: '));
advance(6000); assert.equal(button.textContent, ALAB[KIND]);
button.onclick(); button.onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 1);
""".replace("KIND", repr(kind)))


def test_the_three_armed_copies_are_gone_from_the_page_script():
    source = page.bundle_js()
    assert source.count("classList.add('armed')") == 1
    assert len(re.findall(r"setTimeout\(", source)) == 1, "one timer entry point: hostClock.later"
    assert len(re.findall(r"dataset\.armed\s*=(?!=)", source)) == 2, "arm and disarm live in the helper only"
