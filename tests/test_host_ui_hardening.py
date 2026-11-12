"""D20 (action buttons) and D21 (late results, review request id) in the shared plain-Node DOM model.

The fake clock and `send` helper are the ones from test_round_trips: timers are collected and fired by hand.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_roster_ui import run_roster

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = "no answer from the host (timeout)"
HOSTILE = '" onmouseover=alert(1) x="'

CLOCK = """
let now = 0, queue = [];
hostClock.now = () => now;
hostClock.later = (fn, ms) => { queue.push({fn, due:now + ms}); };
const advance = ms => { now += ms; const due = queue.filter(t => t.due <= now); queue = queue.filter(t => t.due > now); due.forEach(t => t.fn()); };
const send = data => listeners.get('message')({source:window.parent, data});
send({pixelhq:DATA});
const bot = DATA.bots[0];
const TIMEOUT = %s;
const RID = /^[0-9a-f]{16,32}$/;
""" % json.dumps(TIMEOUT)


def run(tmp_path, probe, **kwargs):
    return run_roster(tmp_path, CLOCK + probe, iframe=True, **kwargs)


BLOCKER = """
const blocker = actions => ({board:'platform', id:'t_abcdef01', title:'Sample blocked task', assignee:bot.id, cat:'you',
  ageDays:1, openParents:[], actions, reason:'Sample reason'});
const showBlocker = actions => { send({pixelhq:{...DATA, blockers:[blocker(actions)]}}); return document.getElementById('blist'); };
"""


def test_hostile_action_entries_get_no_button_and_cannot_break_out_of_an_attribute(tmp_path):
    run(tmp_path, BLOCKER + """
const list = showBlocker(['comment', HOSTILE, 'constructor', '__proto__', 'toString', 5, null, {act:'x'}, ['archive'], 'archive']);
const buttons = list.querySelectorAll('[data-act]');
assert.deepEqual(buttons.map(b => b.dataset.act), ['comment', 'archive']);
assert.ok(!list.innerHTML.includes('onmouseover'), 'the hostile entry is not rendered at all');
assert.ok(!list.innerHTML.includes('alert(1)'));
assert.equal(list.querySelectorAll('button').filter(b => Object.keys(b.attrs).some(k => k.startsWith('on'))).length, 0);
assert.ok(list.innerHTML.includes('>Comment<') && list.innerHTML.includes('>Archive<'));
""".replace("HOSTILE", json.dumps(HOSTILE)))


def test_non_array_actions_render_no_buttons(tmp_path):
    run(tmp_path, BLOCKER + """
for (const value of ['comment', {comment:true}, null, undefined, 7]) {
  const list = showBlocker(value);
  assert.equal(list.querySelectorAll('[data-act]').length, 0);
}
""")


def test_a_label_table_entry_is_the_only_way_to_get_a_button(tmp_path):
    run(tmp_path, BLOCKER + """
const list = showBlocker(Object.keys(ALAB));
assert.deepEqual(list.querySelectorAll('[data-act]').map(b => b.dataset.act), ['answer', 'retry', 'comment', 'archive']);
""")


def test_bind_actions_checks_the_trip_not_the_disabled_attribute(tmp_path):
    run(tmp_path, BLOCKER + """
const list = showBlocker(['comment']);
drafts['platform/t_abcdef01'] = 'Sample comment';
list.querySelector('[data-act="comment"]').onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 1);
const button = list.querySelector('[data-act="comment"]');
button.disabled = false;               // even with the attribute gone the busy trip blocks a second send
button.onclick(); button.onclick();
assert.equal(messages.filter(m => m.pixelhqAction).length, 1);
assert.equal(actionTrips.busy('platform/t_abcdef01'), true);
""")


def test_a_confirm_click_on_an_armed_button_is_dropped_while_another_action_runs(tmp_path):
    run(tmp_path, BLOCKER + """
const list = showBlocker(['comment', 'archive']);
drafts['platform/t_abcdef01'] = 'Sample comment';
const archive = list.querySelector('[data-act="archive"]');
archive.onclick();                                   // arms
assert.equal(messages.filter(m => m.pixelhqAction).length, 0);
actionTrips.start('platform/t_abcdef01');            // another action of the same card is now in flight
archive.onclick();                                   // the confirming click
assert.equal(messages.filter(m => m.pixelhqAction).length, 0);
""")


@pytest.mark.parametrize("kind", ["action", "triage"])
def test_late_kanban_and_triage_results_replace_the_timeout_line(tmp_path, kind):
    probe = BLOCKER + {
        "action": """
const list = showBlocker(['comment']);
drafts['platform/t_abcdef01'] = 'Sample comment';
list.querySelector('[data-act="comment"]').onclick();
advance(75000);
assert.ok(list.innerHTML.includes(TIMEOUT));
send({pixelhqActionResult:{board:'platform', id:'t_abcdef01', ok:true, message:'Comment added'}});
assert.ok(list.innerHTML.includes('Comment added') && !list.innerHTML.includes(TIMEOUT));
assert.equal(lastRes[0].text, 'Comment added');
assert.equal(drafts['platform/t_abcdef01'], undefined, 'a late success clears the draft');
""",
        "triage": """
showBlocker([]);
const button = document.getElementById('btriage');
button.onclick(); button.onclick();
advance(20000);
assert.equal(lastRes[0].text, TIMEOUT);
send({pixelhqTriageResult:{ok:true, message:'Triage chat started'}});
assert.equal(lastRes[0].text, 'Triage chat started'); assert.equal(lastRes[0].ok, true);
assert.equal(triageTrips.result('triage').ok, true);
assert.equal(triageTrips.waiting().length, 0);
""",
    }[kind]
    run(tmp_path, probe)


def test_triage_message_carries_the_filter_and_no_scope_text(tmp_path):
    run(tmp_path, BLOCKER + """
send({pixelhq:{...DATA, blockers:[{...blocker(['comment']), stale:true}]}});
bcat = 'you'; bboard = 'platform'; bstale = true; blk();
const button = document.getElementById('btriage');
button.onclick(); button.onclick();
const sent = messages.filter(m => m.pixelhqTriage);
assert.equal(sent.length, 1);
assert.deepEqual(Object.keys(sent[0].pixelhqTriage).sort(), ['filter', 'keys']);
assert.deepEqual(sent[0].pixelhqTriage.filter, {category:'you', board:'platform', stale:true});
assert.deepEqual(sent[0].pixelhqTriage.keys, ['platform/t_abcdef01']);
""")


REVIEW = """
const card = document.getElementById('detail');
const open = () => { card.querySelector('[data-rate="pass"]').onclick(); };
const confirm = () => card.querySelector('[data-review-confirm]').onclick();
const sentReviews = () => messages.filter(m => m.pixelhqReview).map(m => m.pixelhqReview);
"""


def test_review_retry_after_a_timeout_reuses_the_rid_and_a_new_draft_gets_another(tmp_path):
    run(tmp_path, REVIEW + """
open(); confirm();
let sent = sentReviews();
assert.equal(sent.length, 1); assert.match(sent[0].rid, RID);
advance(20000);
assert.ok(card.querySelector('[data-review]').innerHTML.includes(TIMEOUT));
confirm();                                   // retry of the same draft
sent = sentReviews();
assert.equal(sent.length, 2); assert.equal(sent[1].rid, sent[0].rid, 'the retry carries the same rid');
send({pixelhqReviewResult:{ok:false, message:'Sample failure', agent:bot.id, sessionId:null}});
confirm();                                   // retry after a failed answer: still the same draft
assert.equal(sentReviews()[2].rid, sent[0].rid);
send({pixelhqReviewResult:{ok:true, message:'Review saved.', agent:bot.id, sessionId:null}});
assert.equal(card.querySelector('[data-review-form]'), null, 'saved: the draft is gone');
open(); confirm();
const next = sentReviews()[3];
assert.match(next.rid, RID); assert.notEqual(next.rid, sent[0].rid, 'a new draft after success gets a new rid');
send({pixelhqReviewResult:{ok:true, message:'Review saved.', agent:bot.id, sessionId:null}});
open(); card.querySelector('[data-review-cancel]').onclick();
open(); confirm();
const afterCancel = sentReviews()[4];
assert.match(afterCancel.rid, RID); assert.notEqual(afterCancel.rid, next.rid, 'a new draft after Cancel gets a new rid');
""")


def test_changing_the_rating_on_an_open_draft_keeps_its_rid(tmp_path):
    run(tmp_path, REVIEW + """
open();
const draft = () => [...reviewDrafts.values()][0], rid = draft().rid;
assert.match(rid, RID);
card.querySelector('[data-rate="fail"]').onclick();
assert.equal(draft().verdict, 'fail'); assert.equal(draft().rid, rid);
confirm();
assert.equal(sentReviews().length, 1); assert.equal(sentReviews()[0].rid, rid); assert.equal(sentReviews()[0].verdict, 'fail');
""")


def test_review_late_ok_answer_replaces_the_timeout_line_and_closes_the_draft(tmp_path):
    run(tmp_path, REVIEW + """
open(); confirm();
advance(20000);
const row = () => card.querySelector('[data-review]');
assert.ok(row().innerHTML.includes(TIMEOUT));
send({pixelhqReviewResult:{ok:true, message:'Review saved.', agent:bot.id, sessionId:null}});
assert.ok(row().innerHTML.includes('Review saved.') && row().innerHTML.includes('res ok'));
assert.ok(!row().innerHTML.includes(TIMEOUT));
assert.equal(card.querySelector('[data-review-form]'), null);
assert.equal(reviewDrafts.size, 0);
send({pixelhqReviewResult:{ok:false, message:'Unsolicited', agent:bot.id, sessionId:null}});
assert.ok(!row().innerHTML.includes('Unsolicited'));
""")


def test_review_late_answer_after_cancel_still_reports_the_save(tmp_path):
    run(tmp_path, REVIEW + """
open(); confirm();
advance(20000);
card.querySelector('[data-review-cancel]').onclick();
send({pixelhqReviewResult:{ok:true, message:'Review saved.', agent:bot.id, sessionId:null}});
assert.ok(card.querySelector('[data-review]').innerHTML.includes('Review saved.'));
""")


@pytest.mark.parametrize("stub", [
    "undefined",
    "{}",
    "{getRandomValues: 7}",
    "{getRandomValues() { throw new Error('unavailable'); }}",
    "{getRandomValues(bytes) { bytes.fill(171); return bytes; }}",
    "{getRandomValues(bytes) { return bytes; }}",
], ids=["no-crypto", "no-method", "method-not-callable", "method-throws", "crypto-fills", "crypto-leaves-zeros"])
def test_rid_is_lowercase_hex_with_and_without_crypto(tmp_path, stub):
    # Node 22+ defines ``globalThis.crypto`` as a getter without a setter: a plain assignment is silently
    # ignored and the probe would exercise the real Web Crypto API. ``defineProperty`` replaces it everywhere.
    run(tmp_path, """
const STUB = %s;
if (STUB === undefined) delete globalThis.crypto;
else Object.defineProperty(globalThis, 'crypto', {value: STUB, configurable: true, writable: true});
assert.equal(globalThis.crypto, STUB, 'the probe replaced the crypto object');
const ids = Array.from({length:50}, () => newRid());
ids.forEach(id => assert.match(id, RID));
if (typeof crypto === 'undefined' || typeof crypto.getRandomValues !== 'function' || %s)
  assert.ok(new Set(ids).size > 45, 'the Math.random fallback does not repeat');
if (%s) assert.equal(ids[0], 'ab'.repeat(12), 'getRandomValues is the first choice');
""" % (stub, json.dumps("throw" in stub), json.dumps("fill(171)" in stub)))


def test_review_bridge_forwards_the_rid_to_the_backend(tmp_path):
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    prelude = """
const assert=require('node:assert/strict');
const posts=[], calls=[], effects=[], listeners=new Map();
const frame={postMessage:m=>posts.push(m)};
const window={addEventListener:(t,f)=>listeners.set(t,f),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}), useState=()=>[null,()=>{}], useCallback=f=>f, useEffect=f=>effects.push(f), jsx=()=>null;
const sdk={useTheme:()=>({resolvedMode:'dark'}),useQuery:()=>({data:{cfg:{},bots:[]}}),useQueryClient:()=>({setQueryData:()=>{}}),
  host:{},PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{}};
const ctx={rest:async(path,options)=>{calls.push({path,options});
  if(path==='/page')return {html:'<sample>'};
  if(path==='/review')return {ok:true,message:'Review saved.'};
  if(path==='/snapshot?max_age=0')return {fresh:true};
  throw Error('unexpected '+path);}};
"""
    probe = """
(async()=>{
 makePage(ctx)();effects.forEach(f=>f());
 const body={agent:'ops-bot',verdict:'pass',dims:{safety:5},ref:'Sample',sessionId:'sample-session',rid:'0123456789abcdef0123'};
 listeners.get('message')({source:frame,data:{pixelhqReview:body}});
 await new Promise(resolve=>setImmediate(resolve));
 const call=calls.find(c=>c.path==='/review');
 assert.deepEqual(call.options,{method:'POST',body});
 assert.equal(call.options.body.rid,'0123456789abcdef0123');
 console.log('review rid bridge: ok');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    path = tmp_path / "rid-bridge.cjs"
    path.write_text(prelude + source + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
