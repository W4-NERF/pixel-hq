"""Execute the shipped UI in Node with DOM stubs, without network or browser claims."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from pixelhq.demo import snapshot

ROOT = Path(__file__).resolve().parents[1]


def run_ui(tmp_path, probe, *, actions="?actions=1", iframe=False):
    script = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8")
    script += (ROOT / "pixelhq" / "ui" / "app.js").read_text(encoding="utf-8")
    script += "\nDATA = " + json.dumps(snapshot()) + ";\n" + probe + "\nconsole.log('ui review behavior: ok');\n"
    path = tmp_path / "review-ui.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "ACTIONS": actions, "IFRAME": "1" if iframe else "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("actions, iframe, visible", [("", False, False), ("?actions=1", False, True), ("", True, True)])
def test_rate_controls_live_sessions_not_helpers_and_character_card(tmp_path, actions, iframe, visible):
    run_ui(tmp_path, """
const bot = DATA.bots[0];
const session = {id:'sample-session', title:'A sample session', source:'desktop', startedAt:1, lastAt:2,
  msgs:3, toolCalls:1, inTok:0, outTok:0, children:[{id:'sample-child', title:'Sample helper', source:'subagent', startedAt:1}]};
LIVE = {generated:10, bots:{[bot.id]:{active:true, sessions:[session], tasks:[]}}};
liveTab(); detail(bot);
const liveControls = elements.get('lactive').querySelectorAll('[data-review]');
const cardControls = elements.get('detail').querySelectorAll('[data-review]');
assert.equal(liveControls.length, VISIBLE ? 1 : 0, 'exactly one review widget, none on child');
assert.equal(cardControls.length, VISIBLE ? 1 : 0);
if (VISIBLE) {
  assert.equal(liveControls[0].dataset.agent, bot.id);
  assert.equal(liveControls[0].querySelectorAll('[data-rate]').length, 3);
  assert.deepEqual(liveControls[0].querySelectorAll('[data-rate]').map(b => b.dataset.rate), ['pass','revise','fail']);
}
""".replace("VISIBLE", "true" if visible else "false"), actions=actions, iframe=iframe)


def test_rate_form_confirm_cancel_defaults_polling_and_results(tmp_path):
    run_ui(tmp_path, """
const bot = DATA.bots[0];
bot.quest = '<sample> "quest" ' + 'x'.repeat(100);
detail(bot);
let widget = elements.get('detail').querySelector('[data-review]');
widget.querySelector('[data-rate="revise"]').onclick();
assert.equal(messages.filter(m => m.pixelhqReview).length, 0);
let selects = widget.querySelectorAll('select');
assert.equal(selects.length, 4);
assert.deepEqual(selects.map(s => s.value), ['4','4','4','4']);
assert.deepEqual(selects[0].children.map(o => o.value), ['1','2','3','4','5']);
let ref = widget.querySelector('[data-review-ref]');
assert.equal(ref.value, bot.quest.slice(0,80));
assert.ok(widget.innerHTML.includes('&lt;sample&gt;'));
ref.value = '<edited> & "reference"'; ref.oninput();
selects[0].value = '5'; selects[0].onchange();
// Snapshot/live refreshes must not discard an unsubmitted draft.
detail(bot);
widget = elements.get('detail').querySelector('[data-review]');
assert.equal(widget.querySelector('[data-review-ref]').value, '<edited> & "reference"');
assert.equal(widget.querySelector('select').value, '5');
let form = widget.querySelector('form');
assert.equal(typeof form.onsubmit, 'function');
form.onsubmit({preventDefault:()=>{}});
form.onsubmit({preventDefault:()=>{}}); // duplicate submit is ignored
const sent = messages.filter(m => m.pixelhqReview);
assert.equal(sent.length, 1);
assert.deepEqual(sent[0].pixelhqReview, {agent:bot.id, verdict:'revise', sessionId:null,
  ref:'<edited> & "reference"', dims:{correctness:5,completeness:4,format:4,safety:4}});
assert.ok(widget.innerHTML.includes('Saving review'));
// Only the parent can resolve a pending review.
listeners.get('message')({source:{},data:{pixelhqReviewResult:{agent:bot.id,sessionId:null,ok:true,message:'spoofed'}}});
assert.ok(widget.innerHTML.includes('Saving review'));
listeners.get('message')({source:window.parent,data:{pixelhqReviewResult:{agent:bot.id,sessionId:null,ok:false,message:'<sample error>'}}});
assert.ok(widget.innerHTML.includes('res bad'));
assert.ok(widget.innerHTML.includes('&lt;sample error&gt;'));
assert.equal(widget.querySelector('[data-review-ref]').value, '<edited> & "reference"');
widget.querySelector('form').onsubmit({preventDefault:()=>{}});
listeners.get('message')({source:window.parent,data:{pixelhqReviewResult:{agent:bot.id,sessionId:null,ok:true,message:'Review saved.'}}});
assert.ok(widget.innerHTML.includes('res ok'));
assert.ok(!widget.querySelector('form'));
widget.querySelector('[data-rate="fail"]').onclick();
widget.querySelector('[data-review-cancel]').onclick();
assert.ok(!widget.querySelector('form'));
assert.equal(messages.filter(m => m.pixelhqReview).length, 2);
""", iframe=True)


def test_live_review_keeps_session_identity_and_escapes_untrusted_fields(tmp_path):
    run_ui(tmp_path, """
const bot = DATA.bots[0];
bot.id = 'sample<&"bot';
const session = {id:'session<&"sample',title:'<sample> "session"',source:'desktop',startedAt:1,msgs:0,toolCalls:0,inTok:0,outTok:0};
LIVE={generated:10,bots:{[bot.id]:{active:true,sessions:[session,{...session,id:'sample-orphan',source:'subagent'}],tasks:[]}}};
liveTab();detail(bot);
assert.equal(elements.get('lactive').querySelectorAll('[data-review]').length,1);
let widget = elements.get('lactive').querySelector('[data-review]');
assert.equal(widget.dataset.agent, bot.id);
assert.equal(widget.dataset.session, session.id);
assert.ok(!elements.get('lactive').innerHTML.includes('<sample>'));
widget.querySelector('[data-rate="pass"]').onclick();
widget.querySelector('form').onsubmit({preventDefault:()=>{}});
const body = messages.find(m=>m.pixelhqReview).pixelhqReview;
assert.equal(body.agent,bot.id);assert.equal(body.sessionId,session.id);assert.equal(body.ref,session.title);
liveTab();
widget = elements.get('lactive').querySelector('[data-review]');
listeners.get('message')({source:window.parent,data:{pixelhqReviewResult:{agent:bot.id,sessionId:session.id,ok:true,message:'Saved <sample>'}}});
assert.ok(widget.innerHTML.includes('Saved &lt;sample&gt;'));
assert.ok(!elements.get('detail').innerHTML.includes('Saved &lt;sample&gt;'));
""", iframe=True)


def test_footer_reports_signed_raw_xp_sources_and_deduplicated_warnings(tmp_path):
    run_ui(tmp_path, """
DATA.bots = DATA.bots.slice(0,2);
DATA.bots[0].xpBySource={kanban:10,reviews:-5};
DATA.bots[1].xpBySource={kanban:3,reviews:1};
DATA.warnings=['Sample <warning>','Shared warning'];
LIVE={generated:10,bots:{},warnings:['Shared warning','Live warning']};
hud();
const footer=elements.get('foot').textContent;
assert.ok(footer.includes('XP sources (raw): Kanban +13 · reviews -4'));
assert.ok(footer.includes('raw source totals may differ from floored XP'));
assert.ok(footer.includes('Warnings: Sample <warning> · Shared warning · Live warning'));
assert.equal(footer.split('Shared warning').length,2);
assert.ok(!footer.includes('ms · read-only'));
""")
