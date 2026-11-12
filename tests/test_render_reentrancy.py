"""D16: render re-entrancy. Removing the focused element fires `focusout` synchronously in the middle of the removal.

Executed in the plain-Node DOM model (tests/ui_dom.cjs), which models exactly that: removing a focused element
(innerHTML, replaceChildren, removeChild) dispatches `focusout` (relatedTarget null) before the removal completes, and a
listener that replaces the container's children meanwhile makes the outer removal throw `NotFoundError`.
Every flow below starts with a deferred render pending (D8) and the focus inside the container, like the real page.
"""
import pytest

from tests.test_roster_ui import run_roster

COMMON = """
const send = data => listeners.get('message')({source:window.parent, data});
const posted = key => messages.filter(m => m[key]);
const zeroTimers = () => timers.filter(fn => fn.ms === 0).length;
"""

ROSTER = COMMON + """
const withTitle = title => { const copy = JSON.parse(JSON.stringify(DATA)); copy.bots[1].title = title; return copy; };
send({pixelhq:DATA}); tab('roster');
const editor = document.getElementById('roster-editor');
const row = i => editor.querySelectorAll('[data-roster-bot]')[i];
const titleField = () => row(1).querySelector('[data-roster-field="title"]');
let serial = 0;
// Typing in a text field, then a snapshot arrives: the editor render is deferred. Then the pointer moves the focus to
// `control` (a button or radio inside the editor) and the focus flush timer runs: the render must stay deferred.
const pendingThenFocus = control => {
  const field = titleField(); field.focus(); field.value = 'Draft ' + (++serial); field.oninput();
  send({pixelhq:withTitle('Server ' + serial)});
  assert.equal(deferredRenders.size, 1, 'a deferred render is pending');
  control.focus(); flushZeroTimers();
  assert.equal(deferredRenders.size, 1, 'focus is still inside the container: stays deferred');
};
"""

LIVE = COMMON + """
const bot = DATA.bots[0];
const liveWith = title => ({generated:10, bots:{[bot.id]:{active:true, tasks:[], sessions:[
  {id:'sample-session', title, source:'desktop', startedAt:1, lastAt:2, msgs:3, toolCalls:1, inTok:0, outTok:0, stale:true}]}}});
send({pixelhq:DATA}); send({pixelhqLive:liveWith('First title')});
const live = document.getElementById('lactive');
live.querySelector('[data-rate="pass"]').onclick();
const ref = live.querySelector('[data-review-ref]');
"""

BLOCKED = COMMON + """
const bot = DATA.bots[0];
const blocker = reason => ({board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:bot.id,
  cat:'you', ageDays:1, openParents:[], actions:['answer','comment','retry'], reason});
const withBlocker = reason => ({...DATA, blockers:[blocker(reason)]});
send({pixelhq:withBlocker('First reason')});
const list = document.getElementById('blist');
const area = list.querySelector('[data-ta]');
area.focus(); area.value = 'a note for the bot'; area.oninput();
send({pixelhq:withBlocker('Second reason')});
assert.equal(deferredRenders.size, 1, 'a deferred render is pending');
"""


def test_harness_removing_the_focused_element_fires_focusout_before_the_removal_completes(tmp_path):
    run_roster(tmp_path, """
const box = document.getElementById('lactive'); box.innerHTML = '<div><input type="text" id="f"></div><button>b</button>';
const input = box.querySelector('input'); let seen = null; let childrenDuring = null;
document.addEventListener('focusout', e => { seen = e; childrenDuring = box.children.length; });
input.focus(); assert.equal(seen, null);
box.innerHTML = '<span>new</span>';
assert.equal(seen.target, input); assert.equal(seen.relatedTarget, null);
assert.equal(childrenDuring, 2, 'the old children were still attached while focusout ran');
assert.equal(document.activeElement, null);
assert.equal(box.children.length, 1);
// the other removal paths of the harness behave the same
const second = new Element('input'); box.replaceChildren(second); second.focus(); seen = null;
box.replaceChildren(); assert.equal(seen.target, second); assert.equal(seen.relatedTarget, null);
const third = new Element('input'); box.replaceChildren(third); third.focus(); seen = null;
box.removeChild(third); assert.equal(seen.target, third); assert.equal(box.children.length, 0);
""", iframe=True)


@pytest.mark.parametrize("how", ["innerHTML", "replaceChildren", "removeChild"])
def test_harness_throws_not_found_error_when_a_focusout_listener_replaces_the_children(tmp_path, how):
    run_roster(tmp_path, """
const box = document.getElementById('lactive'); box.innerHTML = '<input type="text">';
const field = box.querySelector('input'); field.focus();
document.addEventListener('focusout', () => { box.innerHTML = '<p>from the listener</p>'; });
let error = null;
try { HOW } catch (e) { error = e; }
assert.ok(error, 'the outer removal must throw');
assert.equal(error.name, 'NotFoundError');
assert.match(error.message, /no longer a child of this node/);
""".replace("HOW", {"innerHTML": "box.innerHTML = '<p>outer</p>';", "replaceChildren": "box.replaceChildren();",
                      "removeChild": "box.removeChild(field);"}[how]), iframe=True)


def test_roster_save_with_a_pending_deferred_render_sends_exactly_one_message(tmp_path):
    run_roster(tmp_path, ROSTER + """
const save = editor.querySelector('[data-roster-save]');
pendingThenFocus(save);
save.onclick();
assert.equal(posted('pixelhqRoster').length, 1);
assert.equal(posted('pixelhqRoster')[0].pixelhqRoster.roster.bots[1].title, 'Draft 1');
assert.ok(editor.innerHTML.includes('Saving roster'), 'the pending state is rendered');
assert.equal(deferredRenders.size, 0, 'the direct render cancelled the deferred one');
flushZeroTimers();
assert.equal(posted('pixelhqRoster').length, 1);
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
assert.ok(editor.innerHTML.includes('Roster saved.'));
""", iframe=True)


def test_roster_reset_two_clicks_with_a_pending_deferred_render_send_one_message(tmp_path):
    run_roster(tmp_path, ROSTER + """
const reset = editor.querySelector('[data-roster-reset]');
pendingThenFocus(reset);
reset.onclick(); assert.equal(posted('pixelhqRoster').length, 0, 'the first click only arms the button');
reset.onclick();
assert.equal(posted('pixelhqRoster').length, 1);
assert.deepEqual(posted('pixelhqRoster')[0].pixelhqRoster, {reset:true});
""", iframe=True)


def test_roster_swatch_click_with_a_pending_deferred_render_renders_the_colour(tmp_path):
    run_roster(tmp_path, ROSTER + """
row(1).querySelector('[data-roster-edit]').onclick();
const swatch = row(1).querySelectorAll('[data-roster-swatch]')[7];
pendingThenFocus(swatch);
swatch.onclick();
assert.equal(row(1).querySelector('[data-roster-field="color"]').value, PALETTE.dark.swatches[7]);
assert.equal(deferredRenders.size, 0);
""", iframe=True)


def test_roster_leader_change_with_a_pending_deferred_render_renders_the_new_leader(tmp_path):
    run_roster(tmp_path, ROSTER + """
const radio = row(1).querySelector('[data-roster-leader]');
pendingThenFocus(radio);
radio.checked = true; radio.onchange();
assert.equal(row(1).querySelector('[data-roster-leader]').checked, true);
assert.equal(row(0).querySelector('[data-roster-leader]').checked, false);
""", iframe=True)


def test_roster_add_and_remove_remote_bot_with_a_pending_deferred_render_render_both_changes(tmp_path):
    run_roster(tmp_path, ROSTER + """
const count = () => editor.querySelectorAll('[data-roster-bot]').length, before = count();
const idField = editor.querySelector('[data-roster-new-bot]'); idField.value = 'remote-one'; idField.oninput();
pendingThenFocus(editor.querySelector('[data-roster-add-bot]'));
editor.querySelector('[data-roster-add-bot]').onclick();
assert.equal(count(), before + 1);
assert.equal(editor.querySelectorAll('[data-roster-bot]').at(-1).querySelector('[data-roster-id]').value, 'remote-one');
const remove = editor.querySelector('[data-roster-remove-bot]');
pendingThenFocus(remove);
remove.onclick();
assert.equal(count(), before);
""", iframe=True)


def test_roster_add_and_remove_zone_with_a_pending_deferred_render_render_both_changes(tmp_path):
    run_roster(tmp_path, ROSTER + """
const zones = () => editor.querySelectorAll('[data-roster-zone]').length, before = zones();
const idField = editor.querySelector('[data-roster-new-zone]'); idField.value = 'annex'; idField.oninput();
const labelField = editor.querySelector('[data-roster-new-zone-label]'); labelField.value = 'Annex'; labelField.oninput();
pendingThenFocus(editor.querySelector('[data-roster-add-zone]'));
editor.querySelector('[data-roster-add-zone]').onclick();
assert.equal(zones(), before + 1);
const added = editor.querySelectorAll('[data-roster-zone]').find(z => z.dataset.rosterZone === 'annex');
const remove = added.querySelector('[data-roster-remove-zone]');
pendingThenFocus(remove);
remove.onclick();
assert.equal(zones(), before);
""", iframe=True)


def test_review_confirm_with_a_pending_deferred_render_sends_one_review(tmp_path):
    run_roster(tmp_path, LIVE + """
ref.focus(); ref.value = 'typed note'; ref.oninput();
send({pixelhqLive:liveWith('Second title')});
assert.equal(deferredRenders.size, 1);
const confirm = live.querySelector('[data-review-confirm]'); confirm.focus(); flushZeroTimers();
confirm.onclick();
assert.equal(posted('pixelhqReview').length, 1);
assert.equal(posted('pixelhqReview')[0].pixelhqReview.ref, 'typed note');
flushZeroTimers();
assert.ok(live.innerHTML.includes('Second title'), 'the deferred render still happens afterwards');
assert.equal(posted('pixelhqReview').length, 1);
""", iframe=True)


def test_review_confirm_by_enter_in_the_focused_field_sends_one_review(tmp_path):
    run_roster(tmp_path, LIVE + """
ref.focus(); send({pixelhqLive:liveWith('Second title')});
ref.onkeydown({key:'Enter', preventDefault(){}});
assert.equal(posted('pixelhqReview').length, 1);
assert.ok(live.querySelector('[data-review]').innerHTML.includes('Saving review'));
""", iframe=True)


def test_blocked_comment_with_a_pending_deferred_render_sends_one_action(tmp_path):
    run_roster(tmp_path, BLOCKED + """
const comment = list.querySelector('[data-act="comment"]'); comment.focus(); flushZeroTimers();
comment.onclick();
assert.equal(posted('pixelhqAction').length, 1);
assert.equal(posted('pixelhqAction')[0].pixelhqAction.action, 'comment');
assert.ok(list.innerHTML.includes('Second reason'), 'the render shows the latest state');
assert.ok(list.innerHTML.includes('running'));
""", iframe=True)


def test_blocked_two_click_action_with_a_pending_deferred_render_sends_one_action(tmp_path):
    run_roster(tmp_path, BLOCKED + """
const retry = list.querySelector('[data-act="retry"]'); retry.focus(); flushZeroTimers();
retry.onclick(); assert.equal(posted('pixelhqAction').length, 0, 'the first click only arms the button');
retry.onclick();
assert.equal(posted('pixelhqAction').length, 1);
assert.equal(posted('pixelhqAction')[0].pixelhqAction.action, 'retry');
""", iframe=True)


def test_deferred_render_still_runs_after_the_focus_leaves_the_container(tmp_path):
    run_roster(tmp_path, ROSTER + """
const field = titleField(); field.focus();
send({pixelhq:withTitle('Server title')});
field.blur();
assert.equal(titleField(), field, 'focusout never renders synchronously');
assert.equal(zeroTimers(), 1, 'one flush is scheduled');
flushZeroTimers();
assert.notEqual(titleField(), field);
assert.equal(titleField().value, 'Server title');
assert.equal(deferredRenders.size, 0);
""", iframe=True)


def test_focus_flush_is_coalesced_and_rechecks_where_the_focus_is_when_it_runs(tmp_path):
    run_roster(tmp_path, ROSTER + """
const first = titleField(), second = row(1).querySelector('[data-roster-field="cls"]'); first.focus();
send({pixelhq:withTitle('Server title')});
second.focus(); first.focus(); second.focus(); second.blur(); first.focus();
assert.equal(zeroTimers(), 1, 'several focusout events schedule one flush');
flushZeroTimers();
assert.equal(titleField(), first, 'the focus is back inside the editor when the flush runs: still deferred');
assert.equal(deferredRenders.size, 1);
first.blur(); flushZeroTimers();
assert.notEqual(titleField(), first);
assert.equal(deferredRenders.size, 0);
""", iframe=True)


def test_direct_render_cancels_pending_deferrals_of_the_container_and_of_containers_inside_it(tmp_path):
    run_roster(tmp_path, COMMON + """
send({pixelhq:DATA});
const outer = new Element('div'), inner = new Element('div'), other = new Element('div'), field = new Element('input');
inner.parentNode = outer; field.parentNode = inner; document.activeElement = field;
const runs = [];
renderUnlessFocused(outer, () => runs.push('outer')); renderUnlessFocused(inner, () => runs.push('inner'));
deferredRenders.set(other, () => runs.push('other'));
assert.equal(deferredRenders.size, 3);
document.activeElement = null;
renderDirect(outer, () => runs.push('direct'));
assert.deepEqual(runs, ['direct']);
assert.equal(deferredRenders.size, 1, 'only the unrelated container stays pending');
fire('focusout', {target:field, relatedTarget:null}); flushZeroTimers();
assert.deepEqual(runs, ['direct', 'other']);
""", iframe=True)


def test_no_render_starts_while_a_render_of_the_same_container_is_running(tmp_path):
    run_roster(tmp_path, COMMON + """
send({pixelhq:DATA});
const box = new Element('div'), runs = [];
const nested = () => runs.push('nested');
renderDirect(box, () => { runs.push('outer start'); assert.equal(renderDirect(box, nested), false); runs.push('outer end'); });
assert.deepEqual(runs, ['outer start', 'outer end'], 'the nested request waits');
assert.equal(zeroTimers(), 1);
flushZeroTimers();
assert.deepEqual(runs, ['outer start', 'outer end', 'nested']);
""", iframe=True)


def _order_probe(spy_target):
    """Record the order of host messages and renders: the message must come first."""
    return """
const order = [];
const spy = (el, prop) => { const own = Object.getOwnPropertyDescriptor(Element.prototype, prop);
  Object.defineProperty(el, prop, {get() { return own ? own.get.call(this) : this['_' + prop]; },
    set(v) { order.push('render'); if (own) own.set.call(this, v); else this['_' + prop] = v; }}); };
const realPost = window.parent.postMessage; window.parent.postMessage = m => { order.push('post'); realPost(m); };
""" + spy_target


@pytest.mark.parametrize("flow", ["review", "open", "nudge", "chat", "roster", "reset", "action", "triage", "reload"])
def test_every_host_round_trip_posts_before_it_renders(tmp_path, flow):
    setup = {
        "review": LIVE + _order_probe("spy(live.querySelector('[data-review]'), 'innerHTML');") +
                  "const go = () => live.querySelector('[data-review-confirm]').onclick();",
        "open": LIVE + _order_probe("spy(live.querySelector('[data-jump-row]'), 'innerHTML');") +
                "const go = () => live.querySelector('[data-jump=\"Open\"]').onclick();",
        "nudge": LIVE + _order_probe("spy(live.querySelector('[data-jump-row]'), 'innerHTML');") +
                 "const go = () => live.querySelector('[data-jump=\"Nudge\"]').onclick();",
        "chat": COMMON + "send({pixelhq:DATA}); const det = document.getElementById('detail');" +
                _order_probe("spy(det.querySelector('[data-jump-row]'), 'innerHTML');") +
                "const go = () => det.querySelector('[data-jump=\"Chat\"]').onclick();",
        "roster": ROSTER + _order_probe("spy(editor, 'innerHTML');") +
                  "const go = () => editor.querySelector('[data-roster-save]').onclick();",
        "reset": ROSTER + _order_probe("spy(editor, 'innerHTML');") +
                 "const go = () => { const b = editor.querySelector('[data-roster-reset]'); b.onclick(); b.onclick(); };",
        "action": BLOCKED + _order_probe("spy(list, 'innerHTML');") +
                  "const go = () => list.querySelector('[data-act=\"comment\"]').onclick();",
        "triage": COMMON + "send({pixelhq:{...DATA, blockers:[{board:'platform', id:'t_abcdef01', title:'Sample blocked task',"
                  " assignee:DATA.bots[0].id, cat:'you', ageDays:1, openParents:[], actions:['comment'], reason:'r'}]}});"
                  "const list = document.getElementById('blist');" + _order_probe("spy(list, 'innerHTML');") +
                  "const go = () => { const b = document.getElementById('btriage'); b.onclick(); b.onclick(); };",
        "reload": COMMON + _order_probe("spy(document.getElementById('stand'), 'textContent');") +
                  "const go = () => document.getElementById('reload').onclick();",
    }[flow]
    run_roster(tmp_path, setup + """
if (typeof area !== 'undefined') { area.value = 'a note for the bot'; area.oninput(); }
const sizeBefore = messages.length; order.length = 0;
go();
assert.ok(messages.length > sizeBefore, 'a message reached the host');
assert.equal(order[0], 'post', 'the host message is posted before the first render: ' + order.join(','));
""", iframe=True)


@pytest.mark.parametrize("flow", ["review", "open", "roster", "action", "triage"])
def test_a_failing_render_cannot_swallow_the_host_message(tmp_path, flow):
    setup = {
        "review": LIVE + "const box = live.querySelector('[data-review]'); const go = () => live.querySelector('[data-review-confirm]').onclick();",
        "open": LIVE + "const box = live.querySelector('[data-jump-row]'); const go = () => live.querySelector('[data-jump=\"Open\"]').onclick();",
        "roster": ROSTER + "const box = editor; const go = () => editor.querySelector('[data-roster-save]').onclick();",
        "action": BLOCKED + "const box = list; const go = () => list.querySelector('[data-act=\"comment\"]').onclick();",
        "triage": COMMON + "send({pixelhq:{...DATA, blockers:[{board:'platform', id:'t_abcdef01', title:'Sample blocked task',"
                  " assignee:DATA.bots[0].id, cat:'you', ageDays:1, openParents:[], actions:['comment'], reason:'r'}]}});"
                  "const box = document.getElementById('blist');"
                  "const go = () => { const b = document.getElementById('btriage'); b.onclick(); b.onclick(); };",
    }[flow]
    key = {"review": "pixelhqReview", "open": "pixelhqOpen", "roster": "pixelhqRoster", "action": "pixelhqAction",
           "triage": "pixelhqTriage"}[flow]
    run_roster(tmp_path, setup + """
if (typeof area !== 'undefined') { area.value = 'a note for the bot'; area.oninput(); }
Object.defineProperty(box, 'innerHTML', {get() { return ''; }, set() { throw new Error('render exploded'); }});
try { go(); } catch (e) { assert.equal(e.message, 'render exploded'); }
assert.equal(posted(KEY).length, 1, 'the request was posted although the render threw');
""".replace("KEY", repr(key)), iframe=True)
