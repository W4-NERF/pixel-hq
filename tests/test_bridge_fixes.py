"""Regression probes for review findings in the Desktop bridge (desktop/plugin.js) with a simulated host."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = """
const assert=require('node:assert/strict');
const posts=[], calls=[], effects=[], listeners=new Map(), cache=new Map();
const frame={postMessage:m=>posts.push(m)};
const window={addEventListener:(t,f)=>listeners.set(t,f),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}), useState=()=>[null,()=>{}], useCallback=f=>f, useEffect=f=>effects.push(f), jsx=()=>null;
const sdk={useTheme:()=>({resolvedMode:'dark'}),useQuery:()=>({data:null}),
  useQueryClient:()=>({setQueryData:(k,d)=>cache.set(JSON.stringify(k),d)}),
  host:{},PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{}};
let routes={};
const ctx={rest:async(path,options)=>{calls.push({path,options});
  const answer=routes[path]; if(answer===undefined)throw Error('unexpected '+path);
  if(answer instanceof Error)throw answer; return typeof answer==='function'?answer(options):answer;}};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const send=data=>listeners.get('message')({source:frame,data});
"""


def run_bridge(tmp_path, probe):
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    body = "(async()=>{\n makePage(ctx)();effects.forEach(f=>f());\n" + probe + \
           "\n})().catch(error=>{console.error(error);process.exitCode=1});\n"
    path = tmp_path / "bridge-probe.cjs"
    path.write_text(PRELUDE + source + ";\n" + body, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_failed_refresh_after_a_successful_action_is_not_reported_as_a_failed_action(tmp_path):
    run_bridge(tmp_path, """
routes={'/page':{html:'<sample>'},'/blocker/action':{ok:true,message:'Comment: t_abcdef12 blocked → blocked.'},
  '/snapshot?max_age=0':new Error('Sample timeout while collecting')};
send({pixelhqAction:{board:'platform',id:'t_abcdef12',action:'comment',text:'Sample'}});
await settle(); await settle();
const results=posts.filter(m=>m.pixelhqActionResult).map(m=>m.pixelhqActionResult);
assert.equal(results.length,1,'exactly one answer per action');
assert.equal(results[0].ok,true);
assert.ok(posts.some(m=>typeof m.pixelhqError==='string'&&m.pixelhqError.includes('Sample timeout')),'the refresh failure is a page error');
""")


def test_a_failed_action_is_still_reported(tmp_path):
    run_bridge(tmp_path, """
routes={'/page':{html:'<sample>'},'/blocker/action':new Error('Sample network failure')};
send({pixelhqAction:{board:'platform',id:'t_abcdef12',action:'retry'}});
await settle(); await settle();
const results=posts.filter(m=>m.pixelhqActionResult).map(m=>m.pixelhqActionResult);
assert.equal(results.length,1); assert.equal(results[0].ok,false);
assert.ok(results[0].error.includes('Sample network failure'));
""")


def test_reload_posts_the_fresh_snapshot_itself(tmp_path):
    """An unchanged snapshot keeps the query data identical; the page still needs an answer to leave 'loading …'."""
    run_bridge(tmp_path, """
const snapshot={bots:[],cfg:{},generated:1};
routes={'/page':{html:'<sample>'},'/snapshot?max_age=0':snapshot};
send({pixelhqReload:true});
await settle(); await settle();
assert.ok(posts.some(m=>m.pixelhq===snapshot),'the reload answer reaches the page');
assert.equal(cache.get(JSON.stringify(['pixel-hq','snapshot'])),snapshot,'and updates the query cache');
""")


def test_roster_answers_echo_the_request_id_but_the_backend_never_sees_it(tmp_path):
    run_bridge(tmp_path, """
const rid='0123456789abcdef01234567';
routes={'/page':{html:'<sample>'},'/roster':{ok:true,message:'Roster saved.'},'/snapshot?max_age=0':{bots:[],cfg:{}}};
send({pixelhqRoster:{reset:true,rid}});
await settle(); await settle();
assert.deepEqual(calls.find(c=>c.path==='/roster').options.body,{reset:true});
assert.deepEqual(posts.find(m=>m.pixelhqRosterResult).pixelhqRosterResult,{ok:true,message:'Roster saved.',rid});
posts.length=0;
send({pixelhqRoster:{rid}});
await settle();
assert.deepEqual(posts.find(m=>m.pixelhqRosterResult).pixelhqRosterResult,
  {ok:false,message:'Invalid roster request: expected roster or reset:true.',rid});
posts.length=0;
send({pixelhqRoster:{reset:true,rid:'NOT-HEX'}});
await settle(); await settle();
assert.equal(Object.hasOwn(posts.find(m=>m.pixelhqRosterResult).pixelhqRosterResult,'rid'),false,'an invalid id is not echoed');
""")


def test_the_triage_title_survives_an_invalid_locale_or_time_zone(tmp_path):
    run_bridge(tmp_path, """
for (const cfg of [{locale:'en_GB',timezone:'UTC'},{locale:'en-GB',timezone:'Europe/Berlinn'},{locale:'en_GB',timezone:'+99'},{}]) {
  const stamp=stampOf(cfg);
  assert.match(stamp,/\\d\\d/,JSON.stringify(cfg));
}
assert.equal(stampOf({locale:'de-DE',timezone:'Europe/Berlin'}),
  new Date().toLocaleString('de-DE',{timeZone:'Europe/Berlin',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}));
""")
