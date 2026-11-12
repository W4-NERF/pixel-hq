"""Desktop roster messages are frame-scoped; a saved write survives refresh failures."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_bridge(tmp_path, probe, mode="success"):
    source = (ROOT / "desktop/plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    prelude = """
const assert=require('node:assert/strict');
const posts=[],calls=[],cache=[],effects=[],listeners=new Map();
const frame={postMessage:m=>posts.push(m)},window={addEventListener:(t,f)=>listeners.set(t,f),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}),useState=()=>[null,()=>{}],useCallback=f=>f;
const useEffect=f=>effects.push(f),jsx=()=>null;
const sdk={useTheme:()=>({resolvedMode:'dark'}),useQuery:()=>({data:{cfg:{},bots:[]}}),
  useQueryClient:()=>({setQueryData:(key,data)=>cache.push({key,data})}),
  host:{},PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{}};
const ctx={rest:(path,options)=>{
 calls.push({path,options});
 if(path==='/page')return Promise.resolve({html:'Sample'});
 if(path==='/roster'){
  if(MODE==='transport')return Promise.reject(new Error('404 sample'));
  return Promise.resolve({ok:MODE!=='invalid',message:MODE==='invalid'?'rooms: expected a list.':'Roster saved.'});
 }
 if(path==='/snapshot?max_age=0'){
  assert.ok(posts.some(post=>post.pixelhqRosterResult&&post.pixelhqRosterResult.ok),'write result must precede the fresh snapshot request');
  if(MODE==='refresh')return Promise.reject(new Error('sample refresh failure'));
  return Promise.resolve({fresh:true});
 }
 throw Error('Unexpected REST call '+path);
}};
""".replace("MODE", json.dumps(mode))
    script = tmp_path / "roster-bridge.cjs"
    script.write_text(prelude + source + ";\n(async()=>{\n" + probe +
                      "\nconsole.log('roster bridge: ok');\n})().catch(e=>{console.error(e);process.exitCode=1});\n")
    result = subprocess.run(["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["success", "invalid", "transport", "refresh"])
@pytest.mark.parametrize("body", [{"roster": {"rooms": [], "bots": []}}, {"reset": True}], ids=["save", "reset"])
def test_roster_bridge_exact_request_result_then_snapshot(tmp_path, mode, body):
    run_bridge(tmp_path, """
makePage(ctx)();effects.forEach(effect=>effect());
posts.length=0;
const onMsg=listeners.get('message'),body=BODY;
onMsg({source:{},data:{pixelhqRoster:body}});
assert.equal(calls.filter(call=>call.path==='/roster').length,0);
onMsg({source:frame,data:{pixelhqRoster:body}});
await new Promise(resolve=>setImmediate(resolve));
const request=calls.find(call=>call.path==='/roster');assert.ok(request,'POST /roster is missing');
assert.deepEqual(request.options,{method:'POST',body});
const results=posts.filter(post=>post.pixelhqRosterResult).map(post=>post.pixelhqRosterResult);
assert.equal(results.length,1,'refresh failure cannot replace the write result');
assert.equal(results[0].ok,MODE==='success'||MODE==='refresh');
if(MODE==='transport')assert.ok(results[0].message.includes('restart the Hermes gateway'));
assert.equal(calls.filter(call=>call.path==='/snapshot?max_age=0').length,(MODE==='success'||MODE==='refresh')?1:0);
assert.equal(cache.length,MODE==='success'?1:0);
if(MODE==='success')assert.deepEqual(cache[0],{key:['pixel-hq','snapshot'],data:{fresh:true}});
if(MODE==='refresh')assert.ok(posts.some(post=>post.pixelhqError));
""".replace("BODY", json.dumps(body)).replace("MODE", json.dumps(mode)), mode)


def test_missing_roster_transport_reports_not_supported_without_throwing(tmp_path):
    run_bridge(tmp_path, """
await replyRoster({}, {reset:true}, message=>posts.push(message), ()=>assert.fail('no refresh'));
assert.deepEqual(posts,[{pixelhqRosterResult:{ok:false,message:'not supported by this Hermes Desktop version'}}]);
assert.equal(calls.length,0);
""")


@pytest.mark.parametrize("body", [None, False, "bad", [], {}, {"reset": "true"}, {"reset": False},
                                  {"roster": []}, {"roster": None}, {"roster": {}, "reset": True}])
def test_invalid_roster_message_never_reaches_backend(tmp_path, body):
    run_bridge(tmp_path, """
makePage(ctx)();effects.forEach(effect=>effect());posts.length=0;
assert.doesNotThrow(()=>listeners.get('message')({source:frame,data:{pixelhqRoster:BODY}}));
await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls.filter(call=>call.path==='/roster').length,0);
const results=posts.filter(post=>post.pixelhqRosterResult);assert.equal(results.length,1);
assert.equal(results[0].pixelhqRosterResult.ok,false);assert.ok(results[0].pixelhqRosterResult.message.includes('Invalid roster'));
""".replace("BODY", json.dumps(body)))
