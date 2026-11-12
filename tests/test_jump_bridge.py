"""Execute jump messages against a fake Desktop host; no network or app."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NUDGE_TEXT = (
    "Status check: what are you working on right now, what is blocking you, "
    "and what do you need from me? Answer in three short lines."
)
COMPOSER = """
host.composer={
  getDraft:async(...args)=>{calls.push(['getDraft',...args]);return '';},
  setDraft:async(...args)=>{calls.push(['setDraft',...args]);return true;},
  focus:(...args)=>{calls.push(['focus',...args]);},
  submit:()=>assert.fail('nudge must never submit')
};
"""


def run_bridge(tmp_path, probe):
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    prelude = """
const assert = require('node:assert/strict');
const posts=[], calls=[], effects=[], listeners=new Map();
const frame={postMessage:message=>posts.push(message)};
const window={addEventListener:(type,callback)=>listeners.set(type,callback),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}), useState=()=>[null,()=>{}];
const useCallback=callback=>callback, useEffect=callback=>effects.push(callback);
const jsx=()=>null;
const sdk={useTheme:()=>({resolvedMode:'dark'}),
  useQuery:()=>({data:{cfg:{},bots:[]}}), useQueryClient:()=>({setQueryData:()=>assert.fail('no refresh')}),
  PALETTE_AREA:'', ROUTES_AREA:'', SIDEBAR_NAV_AREA:'', SandboxedFrame:{},
  host:{
    openSession:async(...args)=>{calls.push(['openSession',...args]);},
    newChat:async(...args)=>{calls.push(['newChat',...args]);},
    request:()=>assert.fail('jump actions must not send prompts or use RPC')
  }};
const ctx={rest:async path=>{assert.equal(path,'/page');return {html:'<sample>'};}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const waits=[], wait=async ms=>{waits.push(ms);};
"""
    script = prelude + source + ";\n(async()=>{\nmakePage(ctx,{wait})(); effects.forEach(callback=>callback()); posts.length=0;\n"
    script += "const onMsg=listeners.get('message');\n" + probe
    script += "\nconsole.log('desktop jump bridge: ok');\n})().catch(error=>{console.error(error);process.exitCode=1});\n"
    path = tmp_path / "jump-bridge.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_open_validated_args_and_frame_source(tmp_path):
    run_bridge(tmp_path, """
const body={profile:'ops.bot-2_4',sessionId:'sample:session._-1'};
onMsg({source:{},data:{pixelhqOpen:body}}); await flush();
assert.deepEqual(calls,[]);
onMsg({source:frame,data:{pixelhqOpen:body}}); await flush();
assert.deepEqual(calls,[['openSession',body.sessionId,{profile:body.profile,intent:'tab'}]]);
assert.deepEqual(posts,[{pixelhqOpenResult:{ok:true,message:'Session opened',sessionId:body.sessionId}}]);
""")


@pytest.mark.parametrize("second_fails", [False, True])
def test_open_retries_once_without_intent(tmp_path, second_fails):
    run_bridge(tmp_path, """
host.openSession=async(...args)=>{
  calls.push(['openSession',...args]);
  if(calls.length===1 || SECOND_FAILS)throw new Error('Sample open failure');
};
onMsg({source:frame,data:{pixelhqOpen:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[
  ['openSession','sample-session',{profile:'ops-bot',intent:'tab'}],
  ['openSession','sample-session',{profile:'ops-bot'}]
]);
assert.equal(posts.length,1);
assert.equal(posts[0].pixelhqOpenResult.ok,!SECOND_FAILS);
assert.equal(posts[0].pixelhqOpenResult.sessionId,'sample-session');
if(SECOND_FAILS)assert.ok(posts[0].pixelhqOpenResult.message.includes('Sample open failure'));
""".replace("SECOND_FAILS", json.dumps(second_fails)))


@pytest.mark.parametrize("field, value", [
    ("profile", ""), ("profile", "x" * 65), ("profile", "../ops/bot"), ("profile", "ops+bot"),
    ("profile", "ops-bot\n"), ("profile", "ops-bot\u2028"), ("profile", "ops-bot\u2029"),
    ("profile", None), ("profile", 4),
    ("sessionId", ""), ("sessionId", "x" * 129), ("sessionId", "../session"),
    ("sessionId", "sample session"), ("sessionId", "sample\n"),
    ("sessionId", "sample\u2028"), ("sessionId", "sample\u2029"),
    ("sessionId", None), ("sessionId", []),
])
@pytest.mark.parametrize("kind", ["Open", "Nudge"])
def test_session_jump_rejects_invalid_ids_without_host_calls(tmp_path, field, value, kind):
    body = {"profile": "ops-bot", "sessionId": "sample-session", field: value}
    run_bridge(tmp_path, """
onMsg({source:frame,data:{['pixelhq'+KIND]:BODY}}); await flush();
assert.deepEqual(calls,[]);
assert.equal(posts.length,1);
assert.equal(posts[0]['pixelhq'+KIND+'Result'].ok,false);
assert.match(posts[0]['pixelhq'+KIND+'Result'].message,/invalid/i);
""".replace("BODY", json.dumps(body)).replace("KIND", json.dumps(kind)))


@pytest.mark.parametrize("capability", ["undefined", "null", "false", "{}"])
def test_open_missing_capability_is_a_result_not_an_exception(tmp_path, capability):
    run_bridge(tmp_path, """
host.openSession=CAPABILITY;
onMsg({source:frame,data:{pixelhqOpen:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[]);
assert.deepEqual(posts,[{pixelhqOpenResult:{ok:false,
  message:'not supported by this Hermes Desktop version',sessionId:'sample-session'}}]);
""".replace("CAPABILITY", capability))


def test_chat_uses_only_profile_and_checks_source(tmp_path):
    run_bridge(tmp_path, """
const body={profile:'ops.bot-2_4'};
onMsg({source:{},data:{pixelhqChat:body}}); await flush(); assert.deepEqual(calls,[]);
onMsg({source:frame,data:{pixelhqChat:body}}); await flush();
assert.deepEqual(calls,[['newChat',body.profile]]);
assert.deepEqual(posts,[{pixelhqChatResult:{ok:true,message:'Chat opened',profile:body.profile}}]);
""")


@pytest.mark.parametrize("profile", ["", "x" * 65, "ops+bot", "../bot", "ops-bot\n", None, 5, []])
def test_chat_rejects_invalid_profile_without_host_calls(tmp_path, profile):
    run_bridge(tmp_path, """
onMsg({source:frame,data:{pixelhqChat:{profile:PROFILE}}}); await flush();
assert.deepEqual(calls,[]); assert.equal(posts.length,1);
assert.equal(posts[0].pixelhqChatResult.ok,false);
assert.match(posts[0].pixelhqChatResult.message,/invalid/i);
""".replace("PROFILE", json.dumps(profile)))


@pytest.mark.parametrize("capability", ["undefined", "null", "false", "{}"])
def test_chat_missing_capability_is_a_result(tmp_path, capability):
    run_bridge(tmp_path, """
host.newChat=CAPABILITY;
onMsg({source:frame,data:{pixelhqChat:{profile:'ops-bot'}}}); await flush();
assert.deepEqual(calls,[]);
assert.deepEqual(posts,[{pixelhqChatResult:{ok:false,
  message:'not supported by this Hermes Desktop version',profile:'ops-bot'}}]);
""".replace("CAPABILITY", capability))


@pytest.mark.parametrize("sync", [False, True])
def test_chat_rejection_or_sync_throw_becomes_one_result(tmp_path, sync):
    run_bridge(tmp_path, """
host.newChat=SYNC_THROW(...args)=>{calls.push(['newChat',...args]);throw Error('Sample chat failed');};
onMsg({source:frame,data:{pixelhqChat:{profile:'ops-bot'}}}); await flush();
assert.deepEqual(calls,[['newChat','ops-bot']]);
assert.deepEqual(posts,[{pixelhqChatResult:{ok:false,message:'Sample chat failed',profile:'ops-bot'}}]);
""".replace("SYNC_THROW", "" if sync else "async"))


def test_nudge_waits_for_open_then_uses_exact_session_address(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
let resolveOpen;
host.openSession=(...args)=>{
  calls.push(['openSession',...args]);return new Promise(resolve=>{resolveOpen=resolve;});
};
const body={profile:'ops-bot',sessionId:'sample-session'};
onMsg({source:{},data:{pixelhqNudge:body}}); await flush(); assert.deepEqual(calls,[]);
onMsg({source:frame,data:{pixelhqNudge:body}}); await flush();
assert.deepEqual(calls,[['openSession',body.sessionId,{profile:body.profile,intent:'tab'}]]);
assert.deepEqual(posts,[]);
resolveOpen(); await flush();
assert.deepEqual(calls,[
  ['openSession',body.sessionId,{profile:body.profile,intent:'tab'}],
  ['getDraft',body.sessionId], ['setDraft',body.sessionId,EXPECTED_TEXT], ['focus',body.sessionId]
]);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:true,sessionId:body.sessionId,
  message:'Session opened — status question is in the composer, press Enter to send'}}]);
""".replace("EXPECTED_TEXT", json.dumps(NUDGE_TEXT)))


@pytest.mark.parametrize("draft", ["Existing sample draft", "<sample> & @file:notes", " leading space"])
def test_nudge_leaves_any_nonblank_draft_byte_for_byte_untouched(tmp_path, draft):
    run_bridge(tmp_path, COMPOSER + """
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);return DRAFT;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[
  ['openSession','sample-session',{profile:'ops-bot',intent:'tab'}], ['getDraft','sample-session']
]);
assert.deepEqual(waits,[]);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:true,sessionId:'sample-session',
  message:'Session opened — your existing draft was left untouched'}}]);
""".replace("DRAFT", json.dumps(draft)))


@pytest.mark.parametrize("draft", ["", " \t\n"])
def test_nudge_treats_an_empty_or_blank_draft_as_empty(tmp_path, draft):
    run_bridge(tmp_path, COMPOSER + """
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);return DRAFT;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls.map(call=>call[0]),['openSession','getDraft','setDraft','focus']);
assert.equal(posts[0].pixelhqNudgeResult.ok,true);
""".replace("DRAFT", json.dumps(draft)))


def test_nudge_null_draft_and_unmounted_composer_succeed_on_the_third_attempt(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
let attempts=0;
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);return null;};
host.composer.setDraft=async(...args)=>{calls.push(['setDraft',...args]);attempts++;return attempts>=3;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls.map(call=>call[0]),['openSession',
  'getDraft','setDraft','getDraft','setDraft','getDraft','setDraft','focus']);
assert.deepEqual(waits,[300,300]);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:true,sessionId:'sample-session',
  message:'Session opened — status question is in the composer, press Enter to send'}}]);
""")


def test_nudge_gives_up_after_ten_attempts_with_the_exact_message(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);return null;};
host.composer.setDraft=async(...args)=>{calls.push(['setDraft',...args]);return false;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.equal(calls.filter(call=>call[0]==='getDraft').length,10);
assert.equal(calls.filter(call=>call[0]==='setDraft').length,10);
assert.equal(calls.filter(call=>call[0]==='focus').length,0);
assert.deepEqual(waits,Array(9).fill(300),'300 ms between attempts, none after the last');
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:false,sessionId:'sample-session',
  message:'Session opened, but the composer did not become ready — nothing was placed'}}]);
""")


def test_nudge_stops_when_the_user_types_a_draft_between_attempts(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
let reads=0;
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);reads++;return reads<3?null:'typed meanwhile';};
host.composer.setDraft=async(...args)=>{calls.push(['setDraft',...args]);return false;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.equal(calls.filter(call=>call[0]==='setDraft').length,2);
assert.deepEqual(waits,[300,300]);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:true,sessionId:'sample-session',
  message:'Session opened — your existing draft was left untouched'}}]);
""")


def test_nudge_never_submits_in_any_path(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
host.composer.submit=()=>assert.fail('composer.submit must never be called');
const scenarios=[async()=>'', async()=>null, async()=>'existing', async()=>{throw Error('Sample composer error');}];
for(const getDraft of scenarios){
  host.composer.getDraft=getDraft; host.composer.setDraft=async()=>false;
  onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
}
assert.equal(posts.length,4);
""")


@pytest.mark.parametrize("capability", ["openSession", "getDraft", "setDraft", "focus"])
@pytest.mark.parametrize("missing", ["undefined", "null", "false", "{}"])
def test_nudge_detects_each_missing_capability_before_side_effects(tmp_path, capability, missing):
    assignment = f"host.{capability}" if capability == "openSession" else f"host.composer.{capability}"
    run_bridge(tmp_path, COMPOSER + f"\n{assignment}={missing};\n" + """
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[]);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:false,sessionId:'sample-session',
  message:'not supported by this Hermes Desktop version'}}]);
""")


@pytest.mark.parametrize("composer", ["undefined", "null", "{}"])
def test_nudge_handles_a_missing_composer_object(tmp_path, composer):
    run_bridge(tmp_path, f"host.composer={composer};\n" + """
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[]);
assert.equal(posts[0].pixelhqNudgeResult.ok,false);
assert.equal(posts[0].pixelhqNudgeResult.message,'not supported by this Hermes Desktop version');
""")


@pytest.mark.parametrize("draft", ["undefined", "false", "0", "{}"])
def test_nudge_unavailable_draft_is_not_treated_as_empty(tmp_path, draft):
    run_bridge(tmp_path, COMPOSER + """
host.composer.getDraft=async(...args)=>{calls.push(['getDraft',...args]);return DRAFT;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls,[
  ['openSession','sample-session',{profile:'ops-bot',intent:'tab'}], ['getDraft','sample-session']
]);
assert.equal(posts.length,1); assert.equal(posts[0].pixelhqNudgeResult.ok,false);
assert.ok(posts[0].pixelhqNudgeResult.message.includes('draft is unavailable'));
""".replace("DRAFT", draft))


@pytest.mark.parametrize("verb", ["getDraft", "setDraft", "focus"])
def test_nudge_reports_composer_errors_without_further_actions(tmp_path, verb):
    expected = ["openSession", "getDraft", "setDraft", "focus"]
    expected = expected[:expected.index(verb) + 1]
    run_bridge(tmp_path, COMPOSER + """
host.composer[VERB]=(...args)=>{calls.push([VERB,...args]);throw Error('Sample composer error');};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls.map(call=>call[0]),EXPECTED);
assert.deepEqual(posts,[{pixelhqNudgeResult:{ok:false,message:'Sample composer error',sessionId:'sample-session'}}]);
""".replace("VERB", json.dumps(verb)).replace("EXPECTED", json.dumps(expected)))


def test_nudge_false_write_acknowledgement_is_not_a_success(tmp_path):
    run_bridge(tmp_path, COMPOSER + """
host.composer.setDraft=async(...args)=>{calls.push(['setDraft',...args]);return false;};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.equal(calls.filter(call=>call[0]==='focus').length,0);
assert.equal(posts.length,1); assert.equal(posts[0].pixelhqNudgeResult.ok,false);
assert.ok(!posts[0].pixelhqNudgeResult.message.includes('press Enter to send'));
""")


@pytest.mark.parametrize("second_fails", [False, True])
def test_nudge_retries_open_once_before_touching_composer(tmp_path, second_fails):
    run_bridge(tmp_path, COMPOSER + """
host.openSession=async(...args)=>{
  calls.push(['openSession',...args]);
  if(calls.length===1 || SECOND_FAILS)throw Error('Sample open failure');
};
onMsg({source:frame,data:{pixelhqNudge:{profile:'ops-bot',sessionId:'sample-session'}}}); await flush();
assert.deepEqual(calls.slice(0,2),[
  ['openSession','sample-session',{profile:'ops-bot',intent:'tab'}],
  ['openSession','sample-session',{profile:'ops-bot'}]
]);
assert.deepEqual(calls.slice(2).map(call=>call[0]),SECOND_FAILS ? [] : ['getDraft','setDraft','focus']);
assert.equal(posts.length,1); assert.equal(posts[0].pixelhqNudgeResult.ok,!SECOND_FAILS);
""".replace("SECOND_FAILS", json.dumps(second_fails)))


@pytest.mark.parametrize("kind", ["Open", "Chat", "Nudge"])
@pytest.mark.parametrize("body", [None, [], "sample", 4, {}, True])
def test_malformed_jump_body_is_rejected_without_host_calls(tmp_path, kind, body):
    run_bridge(tmp_path, COMPOSER + """
onMsg({source:frame,data:{['pixelhq'+KIND]:BODY}}); await flush();
assert.deepEqual(calls,[]); assert.equal(posts.length,1);
assert.equal(posts[0]['pixelhq'+KIND+'Result'].ok,false);
assert.match(posts[0]['pixelhq'+KIND+'Result'].message,/invalid/i);
""".replace("KIND", json.dumps(kind)).replace("BODY", json.dumps(body)))


def test_only_triage_may_submit_a_prompt_and_composer_never_submits():
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert source.count("prompt.submit") == 1
    assert source.count("composer.submit") == 0
    # the prompt is assembled (and its snapshot values validated) before the first host call, then submitted once
    assert "host.request('prompt.submit', { session_id: runtime, text })" in source
    assert source.index("const text = triagePrompt(") < source.index("host.request('session.create'")


def test_validator_has_no_redundant_line_break_test_and_still_rejects_them():
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "[\\r\\n]" not in source  # JS `$` has no multiline mode: the id pattern alone rejects line breaks
