"""Exercise SQLite-shaped UI values and standalone submits in plain Node, not a browser."""
import json

import pytest

from tests.test_review_ui import run_ui

PAYLOAD = '\"><img src=x onerror="sample()">&\''


def test_live_task_pid_is_escaped_even_when_sqlite_returns_text(tmp_path):
    run_ui(tmp_path, """
const payload = PAYLOAD;
const task = {id:'t_abcdef01', board:'platform', title:'Sample task', heartbeatAge:3, pid:payload};
const html = taskHtml(task, 10);
assert.ok(html.includes(' · PID ' + esc(payload)));
assert.ok(!html.includes('<img'));
assert.ok(taskHtml({...task, pid:4321}, 10).includes(' · PID 4321'));
""".replace("PAYLOAD", json.dumps(PAYLOAD)))


@pytest.mark.parametrize("renderer, field", [
    ("bubble", "blocked"),
    *[("bars", field) for field in ("lvl", "xpPct", "hp", "n")],
    *[("detail", field) for field in ("status", "lvl", "sessions7d", "own", "summ", "subSessions", "attrs",
                                     "openQuests", "blocked")],
    *[("office", field) for field in ("status", "lvl", "hp")],
    *[("board", field) for field in ("status", "lvl", "xpPct", "hp", "p", "r", "f", "blocked")],
    ("hud", "blocked"),
])
def test_sqlite_shaped_bot_values_cannot_inject_markup(tmp_path, renderer, field):
    run_ui(tmp_path, """
const payload = PAYLOAD, field = FIELD, renderer = RENDERER;
const bot = DATA.bots[0];
DATA.bots = [bot]; LIVE = null;
bot.status = 'blocked';
bot[field] = ['own','summ','attrs'].includes(field) ? [payload,1,1,1] : payload;
let html;
if (renderer === 'bubble') html = bubble(bot);
else if (renderer === 'bars') html = bars(bot);
else if (renderer === 'detail') { detail(bot); html = elements.get('detail').innerHTML; }
else if (renderer === 'office') {
  office(); html = elements.get('floor').querySelectorAll('[data-zone]').map(el => el.innerHTML).join('');
} else if (renderer === 'board') { board(); html = elements.get('tb').innerHTML; }
else { hud(); html = elements.get('hud').innerHTML; }
assert.ok(html.length > 0, 'renderer must actually produce markup');
assert.ok(!html.includes('<img'), renderer + '.' + field + ' must escape or coerce SQLite text');
""".replace("PAYLOAD", json.dumps(PAYLOAD)).replace("FIELD", json.dumps(field))
           .replace("RENDERER", json.dumps(renderer)))


def test_sqlite_shaped_blocker_age_cannot_inject_markup(tmp_path):
    run_ui(tmp_path, """
DATA.blockers = [{board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:DATA.bots[0].id,
  cat:'unknown', ageDays:PAYLOAD, openParents:[], actions:[], reason:'Sample reason'}];
blk();
assert.ok(!elements.get('blist').innerHTML.includes('<img'));
""".replace("PAYLOAD", json.dumps(PAYLOAD)))


def test_hud_and_reactor_escape_metrics_labels_and_coerce_numeric_values(tmp_path):
    run_ui(tmp_path, """
const payload = PAYLOAD;
DATA.reactor = {nodes:[{id:payload, util:payload, power:payload}], engine:'sample', model:'Sample model', srv:null};
const html = reactorHtml(DATA.reactor);
assert.ok(!html.includes('<img'));
assert.ok(html.includes(esc(payload)), 'the node label is visible as text');
hud();
const hudHtml = elements.get('hud').innerHTML;
assert.ok(!hudHtml.includes('<img'));
assert.ok(hudHtml.includes(esc(payload)));
assert.ok(!hudHtml.includes('&amp;lt;img'), 'labels must not be double-escaped');
""".replace("PAYLOAD", json.dumps(PAYLOAD)))


@pytest.mark.parametrize("session_id", [None, "sample-session"])
def test_standalone_review_finishes_immediately_without_sending_or_losing_draft(tmp_path, session_id):
    run_ui(tmp_path, """
const bot = DATA.bots[0], sessionId = SESSION_ID;
if (sessionId) {
  LIVE = {generated:10, bots:{[bot.id]:{active:true, sessions:[{id:sessionId, title:'Sample session',
    source:'desktop', startedAt:1, msgs:0, toolCalls:0, inTok:0, outTok:0}], tasks:[]}}};
  liveTab();
} else detail(bot);
const root = elements.get(sessionId ? 'lactive' : 'detail');
let widget = root.querySelector('[data-review]');
widget.querySelector('[data-rate="pass"]').onclick();
widget.querySelector('[data-review-ref]').value = 'Sample unsent draft';
widget.querySelector('[data-review-ref]').oninput();
widget.querySelector('[data-review-confirm]').onclick();
const key = reviewKey(bot.id, sessionId);
assert.equal(reviewTrips.busy(key), false, 'no pending state may survive a standalone submit');
assert.equal(reviewTrips.result(key).ok, false);
assert.equal(reviewTrips.result(key).message, 'standalone page: no host, nothing was sent');
assert.equal(messages.filter(m => m.pixelhqReview).length, 0);
assert.ok(!widget.innerHTML.includes('Saving review'));
assert.equal(widget.querySelector('fieldset').disabled, false);
assert.equal(widget.querySelector('[data-rate]').disabled, false);
if (sessionId) liveTab(); else detail(bot);
widget = root.querySelector('[data-review]');
assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
assert.equal(widget.querySelector('[data-review-ref]').value, 'Sample unsent draft');
widget.querySelector('[data-review-cancel]').onclick();
assert.ok(!widget.querySelector('[data-review-form]'));
""".replace("SESSION_ID", json.dumps(session_id)))


@pytest.mark.parametrize("action", ["answer", "retry", "comment", "archive"])
@pytest.mark.parametrize("iframe", [False, True], ids=["standalone", "hosted"])
def test_action_submits_resolve_without_host_and_keep_hosted_roundtrip(tmp_path, action, iframe):
    run_ui(tmp_path, """
const action = ACTION, hosted = HOSTED;
global.setTimeout = () => 0; // Arming timers do not need a real clock in this synchronous probe.
const key = 'platform/t_abcdef01';
DATA.blockers = [{board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:DATA.bots[0].id,
  cat:'unknown', ageDays:1, openParents:[], actions:[action], reason:'Sample reason'}];
drafts[key] = 'Sample response';
blk();
let button = document.querySelectorAll('[data-act]')[0];
button.onclick();
if (CONFIRM.has(action)) {
  assert.equal(actionTrips.busy(key), false, 'the first click only arms destructive actions');
  assert.equal(button.dataset.armed, '1');
  button.onclick();
}
const sent = messages.filter(m => m.pixelhqAction);
if (hosted) {
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].pixelhqAction, {board:'platform', id:'t_abcdef01', action, text:'Sample response'});
  assert.equal(actionTrips.busy(key), true);
  const response = {pixelhqActionResult:{board:'platform', id:'t_abcdef01', ok:true, message:'Sample action complete'}};
  listeners.get('message')({source:{}, data:response});
  assert.equal(actionTrips.busy(key), true, 'only the host may resolve an embedded action');
  listeners.get('message')({source:window.parent, data:response});
  assert.ok(!actionTrips.busy(key));
  assert.equal(drafts[key], undefined);
  assert.ok(elements.get('blist').innerHTML.includes('Sample action complete'));
} else {
  assert.ok(!actionTrips.busy(key), 'standalone actions must finish synchronously');
  assert.equal(sent.length, 0);
  assert.equal(actionTrips.result(key).ok, false);
  assert.equal(actionTrips.result(key).message, 'standalone page: no host, nothing was sent');
  assert.equal(drafts[key], 'Sample response');
  assert.ok(elements.get('blist').innerHTML.includes('standalone page: no host, nothing was sent'));
  assert.ok(!elements.get('blist').innerHTML.includes('running …'));
  assert.equal(document.querySelectorAll('[data-act]')[0].disabled, false);
  assert.equal(lastRes[0].text, 'standalone page: no host, nothing was sent');
}
""".replace("ACTION", json.dumps(action)).replace("HOSTED", json.dumps(iframe)), iframe=iframe)


def test_standalone_triage_also_finishes_without_sending(tmp_path):
    run_ui(tmp_path, """
global.setTimeout = () => 0;
DATA.blockers = [{board:'platform', id:'t_abcdef01', title:'Sample triage task', assignee:DATA.bots[0].id,
  cat:'unknown', ageDays:1, openParents:[], actions:[], reason:'Sample reason'}];
blk();
const button = elements.get('btriage');
button.onclick(); button.onclick();
assert.equal(triageBusy(), false);
assert.equal(button.disabled, false);
assert.equal(messages.filter(m => m.pixelhqTriage).length, 0);
assert.ok(elements.get('bres').innerHTML.includes('standalone page: no host, nothing was sent'));
""")
