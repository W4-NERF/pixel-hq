"""Jump controls executed by the offline Node DOM harness, not a browser."""
import json

import pytest

from pixelhq.demo import snapshot
from tests.test_review_ui import run_ui

SESSIONS = """
const bot = DATA.bots[0];
const session = {id:'sample-session', title:'Sample session', source:'desktop', startedAt:1, lastAt:2,
  msgs:3, toolCalls:1, inTok:0, outTok:0, children:[
    {id:'sample-child', title:'Sample helper', source:'subagent', parent:'sample-session', startedAt:1,
     children:[{id:'sample-grandchild', title:'Nested helper', source:'subagent', startedAt:1}]}]};
LIVE = {generated:10, bots:{[bot.id]:{active:true, sessions:[session,
  {...session, id:'sample-orphan', source:'subagent', children:[]}], tasks:[]}}};
liveTab();
const root = elements.get('lactive');
"""


@pytest.mark.parametrize("actions, iframe, visible", [
    ("", False, False), ("?actions=1", False, True), ("", True, True),
])
def test_open_on_each_session_and_nested_helper_row(tmp_path, actions, iframe, visible):
    run_ui(tmp_path, SESSIONS + """
const buttons = root.querySelectorAll('[data-jump="Open"]');
assert.equal(buttons.length, VISIBLE ? 4 : 0);
if (VISIBLE) {
  assert.deepEqual(buttons.map(b => b.parentNode.parentNode.dataset.session),
    ['sample-session','sample-child','sample-grandchild','sample-orphan']);
  buttons.forEach(button => {
    assert.equal(button.attrs.type, 'button');
    assert.equal(button.parentNode.attrs.class, 'acts');
    assert.equal(button.parentNode.parentNode.dataset.profile, bot.id);
  });
  assert.equal((root.innerHTML.match(/>Open</g) || []).length, 4);
}
""".replace("VISIBLE", "true" if visible else "false"), actions=actions, iframe=iframe)


def test_open_payload_pending_parent_only_results_and_polling(tmp_path):
    run_ui(tmp_path, SESSIONS + """
const child = root.querySelectorAll('[data-jump="Open"]')[1];
child.onclick(); child.onclick();
assert.deepEqual(messages.filter(m => m.pixelhqOpen), [
  {pixelhqOpen:{profile:bot.id,sessionId:'sample-child'}}]);
assert.equal(root.querySelectorAll('[data-jump="Open"]')[1].disabled, true);
liveTab();
assert.equal(root.querySelectorAll('[data-jump="Open"]')[1].disabled, true);
const response = {pixelhqOpenResult:{ok:true,message:'Session opened <sample>',sessionId:'sample-child'}};
listeners.get('message')({source:{},data:response});
assert.equal(root.querySelectorAll('[data-jump="Open"]')[1].disabled, true);
listeners.get('message')({source:window.parent,data:response});
liveTab();
assert.equal(root.querySelectorAll('[data-jump="Open"]')[1].disabled, false);
assert.ok(root.innerHTML.includes('res ok'));
assert.ok(root.innerHTML.includes('Session opened &lt;sample&gt;'));
assert.ok(!root.innerHTML.includes('Session opened <sample>'));
""", iframe=True)


def test_standalone_open_resolves_without_a_host_message(tmp_path):
    run_ui(tmp_path, SESSIONS + """
root.querySelector('[data-jump="Open"]').onclick();
assert.equal(messages.filter(m => m.pixelhqOpen).length, 0);
liveTab();
assert.equal(root.querySelector('[data-jump="Open"]').disabled, false);
assert.ok(root.innerHTML.includes('res bad'));
assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
""")


@pytest.mark.parametrize("actions, iframe, visible", [
    ("", False, False), ("?actions=1", False, True), ("", True, True),
])
@pytest.mark.parametrize("remote", [False, True])
def test_character_chat_control_and_muted_remote_hint(tmp_path, actions, iframe, visible, remote):
    run_ui(tmp_path, """
const bot=DATA.bots[0]; bot.remote=REMOTE; detail(bot);
const root=elements.get('detail'), buttons=root.querySelectorAll('[data-jump="Chat"]');
assert.equal(buttons.length, VISIBLE && !REMOTE ? 1 : 0);
if(VISIBLE && !REMOTE)assert.ok(root.innerHTML.includes('>Talk to this bot</button>'));
if(VISIBLE && REMOTE){
  assert.ok(root.innerHTML.includes('class="mut"'));
  assert.ok(root.innerHTML.includes('runs on another host'));
}
""".replace("REMOTE", str(remote).lower()).replace("VISIBLE", str(visible).lower()),
           actions=actions, iframe=iframe)


@pytest.mark.parametrize("iframe", [False, True], ids=["standalone", "hosted"])
def test_character_chat_payload_results_and_polling(tmp_path, iframe):
    run_ui(tmp_path, """
const bot=DATA.bots[0]; bot.id='sample<&"bot'; bot.remote=false; detail(bot);
const root=elements.get('detail');
assert.ok(root.innerHTML.includes(esc(bot.id)));
root.querySelector('[data-jump="Chat"]').onclick();
if(HOSTED){
  assert.deepEqual(messages.filter(m=>m.pixelhqChat),[{pixelhqChat:{profile:bot.id}}]);
  detail(bot);
  assert.equal(root.querySelector('[data-jump="Chat"]').disabled,true);
  const result={pixelhqChatResult:{ok:false,message:'<sample error> & "details"',profile:bot.id}};
  listeners.get('message')({source:{},data:result});
  assert.equal(root.querySelector('[data-jump="Chat"]').disabled,true);
  listeners.get('message')({source:window.parent,data:result}); detail(bot);
  assert.ok(root.innerHTML.includes('res bad'));
  assert.ok(root.innerHTML.includes('&lt;sample error&gt; &amp; &quot;details&quot;'));
  assert.equal(root.querySelector('[data-jump="Chat"]').disabled,false);
}else{
  assert.equal(messages.filter(m=>m.pixelhqChat).length,0); detail(bot);
  assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
  assert.equal(root.querySelector('[data-jump="Chat"]').disabled,false);
}
""".replace("HOSTED", str(iframe).lower()), iframe=iframe)


@pytest.mark.parametrize("actions, iframe, visible", [
    ("", False, False), ("?actions=1", False, True), ("", True, True),
])
def test_nudge_only_on_strictly_stale_rows_including_helpers(tmp_path, actions, iframe, visible):
    run_ui(tmp_path, SESSIONS + """
session.stale=true;
session.children[0].stale=false;
session.children[0].children[0].stale=true;
LIVE.bots[bot.id].sessions.push({...session,id:'sample-truthy',stale:'true',children:[]});
liveTab();
const buttons=root.querySelectorAll('[data-jump="Nudge"]');
assert.equal(buttons.length,VISIBLE ? 2 : 0);
if(VISIBLE){
  assert.deepEqual(buttons.map(b=>b.parentNode.parentNode.dataset.session),['sample-session','sample-grandchild']);
  assert.equal((root.innerHTML.match(/>Ask for status</g)||[]).length,2);
}
""".replace("VISIBLE", str(visible).lower()), actions=actions, iframe=iframe)


@pytest.mark.parametrize("iframe", [False, True], ids=["standalone", "hosted"])
def test_nudge_exact_payload_row_scoped_result_and_no_submit(tmp_path, iframe):
    run_ui(tmp_path, SESSIONS + """
session.stale=true; liveTab();
const button=root.querySelector('[data-jump="Nudge"]'); button.onclick(); button.onclick();
if(HOSTED){
  assert.deepEqual(messages.filter(m=>m.pixelhqNudge),[
    {pixelhqNudge:{profile:bot.id,sessionId:'sample-session'}}]);
  liveTab();
  assert.equal(root.querySelector('[data-jump="Open"]').disabled,true);
  const result={pixelhqNudgeResult:{ok:true,message:RESULT_TEXT,sessionId:'sample-session'}};
  listeners.get('message')({source:{},data:result});
  assert.equal(root.querySelector('[data-jump="Nudge"]').disabled,true);
  listeners.get('message')({source:window.parent,data:result}); liveTab();
  assert.ok(root.innerHTML.includes('res ok'));
  assert.ok(root.innerHTML.includes(RESULT_TEXT));
}else{
  assert.equal(messages.filter(m=>m.pixelhqNudge).length,0); liveTab();
  assert.ok(root.innerHTML.includes('standalone page: no host, nothing was sent'));
}
assert.equal(root.querySelector('[data-jump="Open"]').disabled,false);
assert.equal(root.querySelector('[data-jump="Nudge"]').disabled,false);
assert.ok(!messages.some(m=>Object.keys(m).some(key=>/submit/i.test(key))));
""".replace("HOSTED", str(iframe).lower()).replace("RESULT_TEXT", json.dumps(
        "Session opened — status question is in the composer, press Enter to send")), iframe=iframe)


def test_jump_session_fields_and_result_lines_are_escaped(tmp_path):
    run_ui(tmp_path, SESSIONS + """
bot.id='sample<&"bot'; session.id='session<&"sample'; session.stale=true;
LIVE.bots={[bot.id]:{active:true,sessions:[session],tasks:[]}}; liveTab();
assert.ok(!root.innerHTML.includes('session<&"sample'));
const button=root.querySelector('[data-jump="Nudge"]');
assert.equal(button.parentNode.parentNode.dataset.profile,bot.id);
assert.equal(button.parentNode.parentNode.dataset.session,session.id);
button.onclick();
assert.deepEqual(messages.find(m=>m.pixelhqNudge),{pixelhqNudge:{profile:bot.id,sessionId:session.id}});
listeners.get('message')({source:window.parent,data:{pixelhqNudgeResult:{
  ok:false,message:'<sample error> & "details"',sessionId:session.id}}}); liveTab();
assert.ok(root.innerHTML.includes('res bad'));
assert.ok(root.innerHTML.includes('&lt;sample error&gt; &amp; &quot;details&quot;'));
""", iframe=True)


def test_demo_has_one_stale_live_session_and_a_visible_nudge(tmp_path):
    data = snapshot()
    sessions = [session for bot in data["live"]["bots"].values() for session in bot["sessions"]]
    assert sum(session["stale"] is True for session in sessions) == 1
    run_ui(tmp_path, """
LIVE=DATA.live; liveTab();
assert.equal(elements.get('lactive').querySelectorAll('[data-jump="Nudge"]').length,1);
""")
