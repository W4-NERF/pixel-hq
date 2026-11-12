"""Round 4 bridge (R4-02): profile describe, safe SOUL save, SOUL history proxy and update check.

`desktop/plugin.js` runs in Node against a simulated Desktop host and a simulated backend; every host call is recorded in
`log`, so the step order of the save protocol (spec round-4 §3) is asserted as an exact sequence. No real gateway is used.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r"""
const assert=require('node:assert/strict');
const nodeCrypto=require('node:crypto');
if(!globalThis.crypto)globalThis.crypto=nodeCrypto.webcrypto;
const sha=text=>nodeCrypto.createHash('sha256').update(text,'utf8').digest('hex');
const posts=[],log=[],effects=[],listeners=new Map();
const frame={postMessage:m=>posts.push(m)},window={addEventListener:(t,f)=>listeners.set(t,f),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}),useState=()=>[null,()=>{}],useCallback=f=>f;
const useEffect=f=>effects.push(f),jsx=()=>null;
const RID='0123456789abcdef0123456789abcdef';
const OLD='You are a sample bot.\nStay calm.\n';
const world={
  soul:OLD, applied:true, mangle:null, routes:[], plugins:[], onDescribe:null, onConfigure:null, onRest:null, onPlugins:null,
  describes:0
};
const rawProfile=()=>({name:'ops-bot',description:'Sample profile',soul:world.soul,model:{provider:'sample-provider',default:'sample-model'},
  skills:[{name:'alpha',enabled:true},{name:'beta',enabled:false}],
  toolsets:[{name:'files',enabled:true,label:'Files',description:'x',tool_count:3}],toolsets_pinned:true,
  mcp_servers:[{name:'docs',transport:'stdio',enabled:true}]});
async function gateway(via,method,params,options){
  log.push({via,method,params,options});
  if(method==='profiles.describe'){
    world.describes+=1;
    if(world.onDescribe){const custom=await world.onDescribe(world.describes);if(custom!==undefined)return custom;}
    return rawProfile();
  }
  if(method==='profiles.configure'){
    if(world.onConfigure){const custom=await world.onConfigure(params);if(custom!==undefined)return custom;}
    if(world.applied)world.soul=world.mangle?world.mangle(params.soul):params.soul;
    return {ok:true,applied:{soul:world.applied}};
  }
  if(method==='plugins.manage'){
    if(world.onPlugins){const custom=await world.onPlugins();if(custom!==undefined)return custom;}
    return {plugins:world.plugins,user_count:1,bundled_count:0};
  }
  throw new Error('unexpected host method '+method);
}
const sdk={useTheme:()=>({resolvedMode:'dark'}),useQuery:()=>({data:{cfg:{},bots:[]}}),
  useQueryClient:()=>({setQueryData:()=>assert.fail('no refresh')}),PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{},
  host:{
    request:(method,params)=>gateway('request',method,params),
    profileRoutes:()=>{log.push({via:'profileRoutes'});return world.routes;},
    requestProfile:(route,method,params,timeout,options)=>gateway('requestProfile:'+route.connectionId,method,params,options)
  }};
const ctx={rest:async(path,options)=>{
  if(path==='/page')return {html:'Sample'};
  const verb=(options&&options.method)||'GET';
  log.push({via:'rest',method:verb+' '+path.split('?')[0],params:options?options.body:undefined,path});
  if(world.onRest){const custom=await world.onRest(path,options);if(custom!==undefined)return custom;}
  if(verb==='POST')return {ok:true,message:'SOUL version saved.'};
  return path.startsWith('/soul-history/item')?{text:'older soul\n'}:[];
}};
let clock=1700000000000;
const trace=()=>log.map(e=>e.via==='profileRoutes'?'profileRoutes':e.via+' '+e.method);
const flushFor=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ask(data,key){
  posts.length=0;
  listeners.get('message')({source:frame,data});
  for(let i=0;i<400&&!posts.some(p=>p[key]);i++)await flushFor(5);
  const found=posts.filter(p=>p[key]);
  assert.equal(found.length,1,'exactly one '+key+' expected, got '+found.length);
  return found[0][key];
}
async function quiet(data){
  posts.length=0;log.length=0;
  listeners.get('message')({source:frame,data});
  await flushFor(60);
  assert.deepEqual(posts,[]);
  assert.deepEqual(log,[]);
}
const profileMsg=(over={})=>({pixelhqProfile:{bot:'ops-bot',remote:false,rid:RID,...over}});
const saveMsg=(over={})=>({pixelhqSoulSave:{bot:'ops-bot',remote:false,rid:RID,baseHash:sha(OLD),soul:'New soul.\n',...over}});
const historyMsg=(over={})=>({pixelhqSoulHistory:{bot:'ops-bot',remote:false,rid:RID,...over}});
const itemMsg=(over={})=>({pixelhqSoulHistoryItem:{bot:'ops-bot',remote:false,rid:RID,id:'20261112T010203Z-b8ff3045fe3af27283403b0d.md',...over}});
const updateMsg=(over={})=>({pixelhqUpdateInfo:{rid:RID,...over}});
const ROUTE={profile:'ops-bot',targetProfile:'backend-bot',connectionId:'conn-1',mode:'ssh'};
const SELF={name:'pixel-hq',key:'pixel-hq',version:'1.2.0',installed_sha:'a'.repeat(40),catalog_name:'pixel-hq',
  catalog_version:'1.3.0',catalog_sha:'b'.repeat(40),update_available:true};
"""

SAVE_STEPS = ["request profiles.describe", "rest POST /soul-history", "request profiles.configure", "request profiles.describe"]


def run_bridge(tmp_path, probe, name="profile-bridge"):
    source = (ROOT / "desktop/plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    script = tmp_path / f"{name}.cjs"
    script.write_text(
        PRELUDE + source + "\n;(async()=>{\nmakePage(ctx,{now:()=>clock})();effects.forEach(effect=>effect());\n"
        + probe + "\nconsole.log('profile bridge: ok');\n})().catch(e=>{console.error(e);process.exitCode=1});\n",
        encoding="utf-8")
    result = subprocess.run(["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# ---------------------------------------------------------------- profile describe (§1)

def test_local_describe_is_ready_with_hash_source_key_and_only_the_panel_fields(tmp_path):
    run_bridge(tmp_path, r"""
const r=await ask(profileMsg(),'pixelhqProfileResult');
assert.deepEqual(trace(),['request profiles.describe']);
assert.deepEqual(log[0].params,{name:'ops-bot'});
assert.equal(r.rid,RID);assert.equal(r.state,'ready');assert.equal(r.message,undefined);
assert.equal(r.data.soulHash,sha(OLD));assert.equal(r.data.sourceKey,'local');
assert.equal(r.data.soul,OLD);assert.equal(r.data.description,'Sample profile');assert.equal(r.data.name,'ops-bot');
assert.deepEqual(r.data.model,{provider:'sample-provider',default:'sample-model'});
assert.deepEqual(r.data.skills,[{name:'alpha',enabled:true},{name:'beta',enabled:false}]);
assert.deepEqual(r.data.toolsets,[{name:'files',enabled:true}]);
assert.equal(r.data.toolsets_pinned,true);
assert.deepEqual(r.data.mcp_servers,[{name:'docs',enabled:true,transport:'stdio'}]);
assert.deepEqual(Object.keys(r.data).sort(),['description','mcp_servers','model','name','skills','soul','soulHash','sourceKey',
  'toolsets','toolsets_pinned']);
""")


def test_remote_describe_uses_exactly_one_descriptor_and_the_backend_profile_name(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[{profile:'other',targetProfile:'other',connectionId:'conn-2'},ROUTE];
const r=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.deepEqual(trace(),['profileRoutes','requestProfile:conn-1 profiles.describe']);
assert.deepEqual(log[1].params,{name:'backend-bot'});
assert.deepEqual(log[1].options,{spawnPriority:'foreground'});
assert.equal(r.state,'ready');assert.equal(r.data.sourceKey,'conn-1');assert.equal(r.data.soulHash,sha(OLD));
world.routes=[{profile:'source-name',targetProfile:'ops-bot',connectionId:'conn-3'}];log.length=0;
const t=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.deepEqual(log[1].params,{name:'ops-bot'});assert.equal(t.data.sourceKey,'conn-3');
""")


def test_remote_bot_never_uses_the_local_gateway_and_local_bot_never_asks_for_routes(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[ROUTE];
await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.ok(log.every(e=>e.via!=='request'));
log.length=0;
await ask(profileMsg({remote:false}),'pixelhqProfileResult');
assert.deepEqual(trace(),['request profiles.describe']);
""")


def test_no_matching_descriptor_is_unreachable_and_nothing_is_called(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[{profile:'other',targetProfile:'other',connectionId:'conn-2'}];
const r=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.deepEqual(trace(),['profileRoutes']);
assert.deepEqual(r,{rid:RID,state:'unreachable',message:'Not reachable from this Desktop'});
world.routes=null;
assert.equal((await ask(profileMsg({remote:true}),'pixelhqProfileResult')).state,'unreachable');
""")


def test_two_matching_descriptors_are_ambiguous_and_nothing_is_called(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[ROUTE,{profile:'x',targetProfile:'ops-bot',connectionId:'conn-9'}];
const r=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.deepEqual(trace(),['profileRoutes']);
assert.equal(r.state,'ambiguous');assert.equal(r.data,undefined);assert.ok(r.message.includes('nothing was called'));
log.length=0;world.routes=[ROUTE,{...ROUTE}];
assert.equal((await ask(profileMsg({remote:true}),'pixelhqProfileResult')).state,'ambiguous');
""")


@pytest.mark.parametrize("setup", [
    "delete sdk.host.request;",
    "delete sdk.host.profileRoutes;world.routes=[ROUTE];",
    "delete sdk.host.requestProfile;world.routes=[ROUTE];",
    "world.onDescribe=()=>{throw new Error('unknown method: profiles.describe - client and backend are out of sync');};",
    "world.onDescribe=()=>{throw Object.assign(new Error('x'),{code:-32601});};",
], ids=["no-request", "no-profile-routes", "no-request-profile", "unknown-method-text", "unknown-method-code"])
def test_missing_host_capability_or_unknown_method_is_unsupported(tmp_path, setup):
    run_bridge(tmp_path, setup + r"""
const remote=%s;
const r=await ask(profileMsg({remote}),'pixelhqProfileResult');
assert.equal(r.state,'unsupported');assert.equal(r.message,'This Hermes version has no profile editor API');
assert.equal(r.data,undefined);
assert.ok(trace().every(step=>step==='profileRoutes'||step.endsWith('profiles.describe')));
""" % ("true" if "world.routes" in setup else "false"))


@pytest.mark.parametrize("setup", [
    "world.onDescribe=()=>{throw new Error('gateway exploded');};",
    "world.onDescribe=()=>null;",
    "world.onDescribe=()=>({name:'ops-bot',soul:42});",
    "world.onDescribe=()=>'text';",
], ids=["rejects", "null-answer", "soul-not-text", "string-answer"])
def test_gateway_failures_and_odd_answers_are_error_with_a_short_message(tmp_path, setup):
    run_bridge(tmp_path, setup + r"""
const r=await ask(profileMsg(),'pixelhqProfileResult');
assert.equal(r.state,'error');assert.equal(typeof r.message,'string');assert.ok(r.message.length<=200);assert.equal(r.data,undefined);
""")


@pytest.mark.parametrize("connection", ["'../x'", "'a b'", "5", "''", "'x'.repeat(65)", "null"])
def test_unusable_connection_id_is_an_error_before_any_remote_call(tmp_path, connection):
    run_bridge(tmp_path, "world.routes=[{...ROUTE,connectionId:%s}];" % connection + r"""
const r=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.equal(r.state,'error');assert.deepEqual(trace(),['profileRoutes']);
""")


def test_a_failing_route_inventory_is_an_error(tmp_path):
    run_bridge(tmp_path, r"""
sdk.host.profileRoutes=()=>{throw new Error('registry offline');};
const r=await ask(profileMsg({remote:true}),'pixelhqProfileResult');
assert.deepEqual(r,{rid:RID,state:'error',message:'registry offline'});
""")


def test_long_lists_and_text_are_bounded(tmp_path):
    run_bridge(tmp_path, r"""
world.onDescribe=()=>({name:'n'.repeat(500),description:'d'.repeat(5000),soul:'s',model:{provider:'p'.repeat(500),default:3},
  skills:Array.from({length:2500},(_,i)=>({name:'skill-'+i})).concat(['bad',null,7]),toolsets:'nope',mcp_servers:[{name:'m',enabled:false}]});
const r=(await ask(profileMsg(),'pixelhqProfileResult')).data;
assert.equal(r.name.length,64);assert.equal(r.description.length,2000);assert.equal(r.model.provider.length,128);
assert.equal(r.model.default,'');assert.equal(r.skills.length,2000);assert.equal(r.skills[0].enabled,true);
assert.deepEqual(r.toolsets,[]);assert.deepEqual(r.mcp_servers,[{name:'m',enabled:false,transport:''}]);
assert.equal(r.toolsets_pinned,false);
""")


@pytest.mark.parametrize("body", [
    "null", "'text'", "[]", "{bot:'ops-bot',remote:false}", "{bot:'ops-bot',remote:false,rid:'XYZ'}",
    "{bot:'ops-bot',remote:false,rid:'0123456789ABCDEF0123456789ABCDEF'}", "{bot:'../x',remote:false,rid:RID}",
    "{bot:5,remote:false,rid:RID}", "{bot:'',remote:false,rid:RID}", "{bot:'a'.repeat(65),remote:false,rid:RID}",
    "{bot:'ops-bot',remote:'false',rid:RID}", "{bot:'ops-bot',rid:RID}",
])
def test_invalid_requests_never_reach_the_host(tmp_path, body):
    run_bridge(tmp_path, r"""
for(const key of ['pixelhqProfile','pixelhqSoulSave','pixelhqSoulHistory','pixelhqSoulHistoryItem']){
  posts.length=0;log.length=0;
  listeners.get('message')({source:frame,data:{[key]:BODY}});
  await flushFor(40);
  assert.equal(posts.length,1);const result=Object.values(posts[0])[0];
  assert.equal(result.state,'error');assert.equal(typeof result.message,'string');
  assert.ok(result.rid===null||result.rid===RID);assert.deepEqual(log,[]);
}
""".replace("BODY", body))


def test_unknown_messages_and_foreign_sources_are_ignored(tmp_path):
    run_bridge(tmp_path, r"""
await quiet({pixelhqProfiles:{bot:'ops-bot',remote:false,rid:RID}});
await quiet({pixelhqsoulsave:{}});
await quiet({something:1});
await quiet('pixelhqProfile');
await quiet(null);
posts.length=0;
for(const data of [profileMsg(),saveMsg(),historyMsg(),itemMsg(),updateMsg()])listeners.get('message')({source:{},data});
await flushFor(60);
assert.deepEqual(posts,[]);assert.deepEqual(log,[]);
""")


# ---------------------------------------------------------------- save protocol (§3)

def test_successful_save_runs_the_four_steps_in_order_with_one_request_id(tmp_path):
    out = run_bridge(tmp_path, r"""
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
console.log('SEQUENCE '+JSON.stringify(trace()));
assert.deepEqual(trace(),%s);
assert.equal(r.state,'saved');assert.equal(r.rid,RID);assert.equal(r.soulHash,sha('New soul.\n'));assert.equal(r.message,'SOUL saved.');
assert.deepEqual(log[0].params,{name:'ops-bot'});
assert.deepEqual(log[1].params,{bot:'ops-bot',sourceKey:'local',text:OLD,rid:RID});
assert.equal(log[1].path,'/soul-history');
assert.deepEqual(log[2].params,{name:'ops-bot',soul:'New soul.\n'});
assert.deepEqual(log[3].params,{name:'ops-bot'});
assert.equal(world.soul,'New soul.\n');
""" % json.dumps(SAVE_STEPS))
    assert "SEQUENCE" in out


def test_remote_save_runs_the_same_steps_through_the_one_route(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[ROUTE];
const r=await ask(saveMsg({remote:true}),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),['profileRoutes','requestProfile:conn-1 profiles.describe','rest POST /soul-history',
  'requestProfile:conn-1 profiles.configure','requestProfile:conn-1 profiles.describe']);
assert.equal(r.state,'saved');
assert.deepEqual(log[2].params,{bot:'ops-bot',sourceKey:'conn-1',text:OLD,rid:RID});
assert.deepEqual(log[3].params,{name:'backend-bot',soul:'New soul.\n'});
assert.deepEqual(log[3].options,{spawnPriority:'foreground'});
""")


def test_changed_soul_is_a_conflict_and_nothing_is_backed_up_or_written(tmp_path):
    out = run_bridge(tmp_path, r"""
world.soul='Someone else edited this.\n';
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
console.log('SEQUENCE '+JSON.stringify(trace()));
assert.deepEqual(trace(),['request profiles.describe']);
assert.equal(r.state,'conflict');assert.equal(r.message,'The SOUL changed since you opened it. Reload to see the current version.');
assert.equal(r.soulHash,sha('Someone else edited this.\n'));assert.equal(world.soul,'Someone else edited this.\n');
""")
    assert "SEQUENCE" in out


@pytest.mark.parametrize("backup", [
    "world.onRest=()=>{throw new Error('500 history store unavailable');};",
    "world.onRest=()=>({ok:false,message:'text: at most 64 KiB.'});",
    "world.onRest=()=>null;",
    "world.onRest=()=>({message:'no ok flag'});",
    "world.onRest=()=>{throw new Error('404 Not Found');};",
], ids=["rejects", "refused", "null", "no-ok", "route-missing"])
def test_backup_failure_stops_before_the_profile_is_written(tmp_path, backup):
    out = run_bridge(tmp_path, backup + r"""
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
console.log('SEQUENCE '+JSON.stringify(trace()));
assert.deepEqual(trace(),['request profiles.describe','rest POST /soul-history']);
assert.equal(r.state,'failed');assert.ok(r.message.startsWith('Backup of the current SOUL failed, nothing was written'));
assert.equal(world.soul,OLD);assert.equal(r.soulHash,undefined);
""")
    assert "SEQUENCE" in out


def test_backup_route_missing_carries_the_restart_hint(tmp_path):
    run_bridge(tmp_path, r"""
world.onRest=()=>{throw new Error('404 Not Found');};
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.ok(r.message.includes('restart the Hermes gateway'));
""")


@pytest.mark.parametrize("configure", [
    "world.applied=false;",
    "world.onConfigure=()=>({ok:false,applied:{soul:true}});",
    "world.onConfigure=()=>({ok:true});",
    "world.onConfigure=()=>({ok:true,applied:null});",
    "world.onConfigure=()=>null;",
    "world.onConfigure=()=>{throw new Error('write refused');};",
    "world.onConfigure=()=>({ok:true,applied:{soul:'yes'}});",
], ids=["applied-false", "ok-false", "no-applied", "applied-null", "null", "rejects", "applied-not-true"])
def test_unapplied_write_is_failed_without_a_read_back(tmp_path, configure):
    run_bridge(tmp_path, configure + r"""
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),['request profiles.describe','rest POST /soul-history','request profiles.configure']);
assert.equal(r.state,'failed');assert.ok(r.message.startsWith('The SOUL was not written'));assert.equal(world.describes,1);
""")


def test_write_rejected_as_unknown_method_is_unsupported(tmp_path):
    run_bridge(tmp_path, r"""
world.onConfigure=()=>{throw new Error('unknown method: profiles.configure');};
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.equal(r.state,'unsupported');assert.equal(r.message,'This Hermes version has no profile editor API');
assert.equal(trace().length,3);
""")


def test_read_back_difference_is_unverified(tmp_path):
    run_bridge(tmp_path, r"""
world.mangle=text=>text.trimEnd();
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),%s);
assert.equal(r.state,'unverified');assert.equal(r.message,'Saved, but the read-back differs');assert.equal(r.soulHash,sha('New soul.'));
""" % json.dumps(SAVE_STEPS))


def test_failing_read_back_is_unverified_not_failed(tmp_path):
    run_bridge(tmp_path, r"""
world.onDescribe=count=>{if(count===2)throw new Error('gateway restarted');};
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),%s);
assert.equal(r.state,'unverified');assert.ok(r.message.startsWith('Saved, but the read-back failed'));assert.equal(world.soul,'New soul.\n');
""" % json.dumps(SAVE_STEPS))


def test_failing_first_read_stops_before_the_backup(tmp_path):
    run_bridge(tmp_path, r"""
world.onDescribe=()=>{throw new Error('gateway exploded');};
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),['request profiles.describe']);assert.equal(r.state,'error');
""")


@pytest.mark.parametrize("soul", [
    "'a'.repeat(65537)", "'é'.repeat(32769)", "'\\u20ac'.repeat(21846)", "'x\\u0000y'", "'x\\u001by'", "'x\\u0007y'", "'x\\u007fy'.replace('\\u007f','\\u0001')",
    "'x\\ud800y'", "'x\\udc00'", "42", "null", "undefined", "['a']",
], ids=["ascii-65537", "two-byte-65538", "three-byte-65538", "nul", "esc", "bell", "soh", "lone-high", "lone-low", "number", "null",
        "missing", "array"])
def test_invalid_soul_is_refused_before_any_host_call(tmp_path, soul):
    run_bridge(tmp_path, "const soul=%s;" % soul + r"""
for(const remote of [false,true]){
  world.routes=[ROUTE];
  const message=saveMsg({remote});
  if(soul===undefined)delete message.pixelhqSoulSave.soul;else message.pixelhqSoulSave.soul=soul;
  const r=await ask(message,'pixelhqSoulSaveResult');
  assert.equal(r.state,'error');assert.equal(typeof r.message,'string');assert.deepEqual(trace(),[]);
}
""")


@pytest.mark.parametrize("soul", ["'a'.repeat(65536)", "'é'.repeat(32768)", "'\\u20ac'.repeat(21845)", "''", "'tab\\there\\nline\\n'",
                                  "'a\\u00e9\\ud83d\\ude00'"],
                         ids=["ascii-65536", "two-byte-65536", "three-byte-65535", "empty", "tab-and-newline", "emoji-pair"])
def test_soul_within_the_limits_is_written_verbatim(tmp_path, soul):
    run_bridge(tmp_path, "const soul=%s;" % soul + r"""
const r=await ask(saveMsg({soul}),'pixelhqSoulSaveResult');
assert.equal(r.state,'saved');assert.equal(log[2].params.soul,soul);assert.equal(world.soul,soul);
""")


def test_line_endings_are_normalised_once_and_the_normalised_text_is_written_and_verified(tmp_path):
    run_bridge(tmp_path, r"""
const r=await ask(saveMsg({soul:'one\r\ntwo\rthree\n'}),'pixelhqSoulSaveResult');
assert.equal(log[2].params.soul,'one\ntwo\nthree\n');assert.equal(r.state,'saved');assert.equal(r.soulHash,sha('one\ntwo\nthree\n'));
""")


@pytest.mark.parametrize("override", [
    "{baseHash:'abc'}", "{baseHash:sha(OLD).toUpperCase()}", "{baseHash:5}", "{baseHash:[sha(OLD)]}", "{baseHash:undefined}",
    "{bot:'_bot'}", "{bot:'.hidden'}", "{rid:'short'}",
], ids=["short-hash", "upper-hash", "number-hash", "array-hash", "missing-hash", "bot-underscore", "bot-dot", "bad-rid"])
def test_invalid_hash_or_ids_are_refused_before_any_host_call(tmp_path, override):
    run_bridge(tmp_path, "const over=%s;" % override + r"""
const message=saveMsg(over);
for(const key of Object.keys(over))if(over[key]===undefined)delete message.pixelhqSoulSave[key];
const r=await ask(message,'pixelhqSoulSaveResult');
assert.equal(r.state,'error');assert.deepEqual(trace(),[]);
""")


def test_unreachable_or_ambiguous_remote_save_is_an_error_and_writes_nothing(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[];
let r=await ask(saveMsg({remote:true}),'pixelhqSoulSaveResult');
assert.equal(r.state,'error');assert.equal(r.message,'Not reachable from this Desktop');assert.deepEqual(trace(),['profileRoutes']);
log.length=0;world.routes=[ROUTE,{...ROUTE,connectionId:'conn-2'}];
r=await ask(saveMsg({remote:true}),'pixelhqSoulSaveResult');
assert.equal(r.state,'error');assert.ok(r.message.includes('nothing was called'));assert.deepEqual(trace(),['profileRoutes']);
""")


def test_save_without_backend_transport_or_host_rpc_is_unsupported_and_calls_nothing(tmp_path):
    run_bridge(tmp_path, r"""
const rest=ctx.rest;delete ctx.rest;
let r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.equal(r.state,'unsupported');assert.deepEqual(trace(),[]);
ctx.rest=rest;delete sdk.host.request;
r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.equal(r.state,'unsupported');assert.deepEqual(trace(),[]);
""")


def test_a_second_save_for_the_same_bot_is_refused_while_the_first_runs(tmp_path):
    run_bridge(tmp_path, r"""
let release;const gate=new Promise(resolve=>{release=resolve;});
world.onDescribe=async count=>{if(count===1)await gate;};
posts.length=0;
listeners.get('message')({source:frame,data:{...saveMsg(),}});
await flushFor(30);
const second=await ask(saveMsg({rid:'fedcba9876543210fedcba9876543210',soul:'Other.\n'}),'pixelhqSoulSaveResult');
assert.equal(second.state,'error');assert.equal(second.rid,'fedcba9876543210fedcba9876543210');assert.ok(second.message.includes('already running'));
assert.equal(log.filter(e=>e.method==='profiles.configure').length,0);
release();
for(let i=0;i<400&&!posts.some(p=>p.pixelhqSoulSaveResult&&p.pixelhqSoulSaveResult.rid===RID);i++)await flushFor(5);
assert.equal(posts.find(p=>p.pixelhqSoulSaveResult.rid===RID).pixelhqSoulSaveResult.state,'saved');
// the lock is released: a new save for the same bot runs again
world.soul=OLD;log.length=0;world.onDescribe=null;
assert.equal((await ask(saveMsg(),'pixelhqSoulSaveResult')).state,'saved');
""")


def test_a_late_answer_arrives_once_after_the_host_was_slow(tmp_path):
    run_bridge(tmp_path, r"""
world.onDescribe=async()=>{await flushFor(150);};
const r=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.equal(r.state,'saved');assert.equal(posts.filter(p=>p.pixelhqSoulSaveResult).length,1);
""")


def test_a_failed_save_releases_the_lock(tmp_path):
    run_bridge(tmp_path, r"""
world.onRest=()=>{throw new Error('500');};
assert.equal((await ask(saveMsg(),'pixelhqSoulSaveResult')).state,'failed');
world.onRest=null;
// A new attempt has a new request id; the same id would get the kept final answer (R4-D2).
assert.equal((await ask(saveMsg({rid:'fedcba9876543210fedcba9876543210'}),'pixelhqSoulSaveResult')).state,'saved');
""")


# ---------------------------------------------------------------- one save, one final answer (R4-D2)

def test_retry_during_flight_gets_no_reply_of_its_own_and_one_final_answer(tmp_path):
    run_bridge(tmp_path, r"""
let release;const blocked=new Promise(resolve=>{release=resolve;});
world.onDescribe=async n=>{if(n===2)await blocked;};
posts.length=0;
listeners.get('message')({source:frame,data:saveMsg()});
await flushFor(25);
assert.equal(world.soul,'New soul.\n');
for(let i=0;i<3;i++){listeners.get('message')({source:frame,data:saveMsg()});await flushFor(10);}
assert.equal(posts.filter(p=>p.pixelhqSoulSaveResult).length,0,'a repeat of a running request id gets no reply');
release();
for(let i=0;i<400&&!posts.some(p=>p.pixelhqSoulSaveResult);i++)await flushFor(5);
await flushFor(40);
const results=posts.filter(p=>p.pixelhqSoulSaveResult).map(p=>p.pixelhqSoulSaveResult);
assert.deepEqual(results.map(r=>[r.rid,r.state]),[[RID,'saved']]);
assert.equal(log.filter(e=>e.method==='profiles.configure').length,1,'one configure call');
assert.equal(log.filter(e=>e.method==='POST /soul-history').length,1,'one backup');
""")


def test_retry_after_completion_returns_the_kept_answer_without_a_host_call(tmp_path):
    run_bridge(tmp_path, r"""
const first=await ask(saveMsg(),'pixelhqSoulSaveResult');assert.equal(first.state,'saved');
const calls=log.length;
const again=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.deepEqual(again,first);assert.equal(log.length,calls,'no new host call');
clock+=10*60*1000-1;assert.deepEqual(await ask(saveMsg(),'pixelhqSoulSaveResult'),first);assert.equal(log.length,calls);
clock+=1;
const fresh=await ask(saveMsg(),'pixelhqSoulSaveResult');
assert.equal(fresh.state,'conflict','after 10 minutes the request id is new again (the profile has changed meanwhile)');
assert.ok(log.length>calls);
""")


def test_only_the_last_twenty_final_answers_are_kept(tmp_path):
    run_bridge(tmp_path, r"""
const rid=n=>String(n).padStart(32,'0');
for(let n=1;n<=21;n++){
  world.soul=OLD;
  assert.equal((await ask(saveMsg({rid:rid(n)}),'pixelhqSoulSaveResult')).state,'saved');
}
log.length=0;world.soul=OLD;
assert.equal((await ask(saveMsg({rid:rid(21)}),'pixelhqSoulSaveResult')).state,'saved');assert.equal(log.length,0,'kept');
assert.equal((await ask(saveMsg({rid:rid(2)}),'pixelhqSoulSaveResult')).state,'saved');assert.equal(log.length,0,'kept (20th newest)');
assert.equal((await ask(saveMsg({rid:rid(1)}),'pixelhqSoulSaveResult')).state,'saved');assert.ok(log.length>0,'the oldest was dropped');
""")


def test_a_refused_second_request_is_not_kept_as_a_final_answer(tmp_path):
    run_bridge(tmp_path, r"""
let release;const blocked=new Promise(resolve=>{release=resolve;});
world.onDescribe=async n=>{if(n===2)await blocked;};
listeners.get('message')({source:frame,data:saveMsg()});await flushFor(25);
const other='fedcba9876543210fedcba9876543210';
const refused=await ask(saveMsg({rid:other}),'pixelhqSoulSaveResult');
assert.equal(refused.state,'error');assert.match(refused.message,/already running/);
release();await flushFor(60);world.onDescribe=null;world.soul=OLD;log.length=0;
const retry=await ask(saveMsg({rid:other}),'pixelhqSoulSaveResult');
assert.equal(retry.state,'saved');assert.ok(log.length>0,'the refusal was not a save, so the id runs for real');
""")


# ---------------------------------------------------------------- SOUL history proxy (§4)

def test_history_list_proxies_the_get_route_and_keeps_only_listed_fields(tmp_path):
    run_bridge(tmp_path, r"""
world.onRest=()=>[
  {id:'20261112T010203Z-b8ff3045fe3af27283403b0d.md',savedAt:'2026-11-12T01:02:03Z',bytes:40,firstLine:'x'.repeat(200),path:'/secret'},
  {id:'../../etc/passwd',savedAt:'x',bytes:1,firstLine:'y'},{id:5},null,'text',
  {id:'20261111T010203Z-0123456789abcdef0123456789abcdef.md',savedAt:'2026-11-11T01:02:03Z',bytes:'many',firstLine:7},
  {id:'20261110T010203Z-89abcdef.md',savedAt:'2026-11-10T01:02:03Z',bytes:3,firstLine:'short id'},
  {id:'20261110T010203Z-abcdefg.md'},{id:'20261110T010203Z-'+'a'.repeat(33)+'.md'}];
const r=await ask(historyMsg(),'pixelhqSoulHistoryResult');
assert.deepEqual(trace(),['rest GET /soul-history']);
assert.equal(log[0].path,'/soul-history?bot=ops-bot&sourceKey=local');assert.equal(log[0].params,undefined);
assert.equal(r.state,'ready');assert.equal(r.rid,RID);assert.equal(r.items.length,3);
assert.deepEqual(r.items[0],{id:'20261112T010203Z-b8ff3045fe3af27283403b0d.md',savedAt:'2026-11-12T01:02:03Z',bytes:40,firstLine:'x'.repeat(80)});
assert.deepEqual(r.items[1],{id:'20261111T010203Z-0123456789abcdef0123456789abcdef.md',savedAt:'2026-11-11T01:02:03Z',bytes:0,firstLine:''});
assert.deepEqual(r.items[2],{id:'20261110T010203Z-89abcdef.md',savedAt:'2026-11-10T01:02:03Z',bytes:3,firstLine:'short id'});
""")


def test_history_list_is_limited_to_fifty_rows(tmp_path):
    run_bridge(tmp_path, r"""
world.onRest=()=>Array.from({length:80},(_,i)=>({id:'2026111'+(i%10)+'T0102'+String(i).padStart(2,'0')+'Z-b8ff3045fe3af27283403b0d.md',savedAt:'s',bytes:1,firstLine:''}));
assert.equal((await ask(historyMsg(),'pixelhqSoulHistoryResult')).items.length,50);
""")


def test_remote_history_uses_the_connection_id_as_source_key_and_never_calls_the_profile(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[ROUTE];
const r=await ask(historyMsg({remote:true}),'pixelhqSoulHistoryResult');
assert.deepEqual(trace(),['profileRoutes','rest GET /soul-history']);
assert.equal(log[1].path,'/soul-history?bot=ops-bot&sourceKey=conn-1');assert.equal(r.state,'ready');
log.length=0;
const t=await ask(itemMsg({remote:true}),'pixelhqSoulHistoryItemResult');
assert.deepEqual(trace(),['profileRoutes','rest GET /soul-history/item']);
assert.equal(log[1].path,'/soul-history/item?bot=ops-bot&sourceKey=conn-1&id=20261112T010203Z-b8ff3045fe3af27283403b0d.md');
assert.equal(t.state,'ready');
""")


def test_history_item_returns_the_text_and_the_id(tmp_path):
    run_bridge(tmp_path, r"""
const r=await ask(itemMsg(),'pixelhqSoulHistoryItemResult');
assert.deepEqual(trace(),['rest GET /soul-history/item']);
assert.equal(log[0].path,'/soul-history/item?bot=ops-bot&sourceKey=local&id=20261112T010203Z-b8ff3045fe3af27283403b0d.md');
assert.deepEqual(r,{rid:RID,state:'ready',id:'20261112T010203Z-b8ff3045fe3af27283403b0d.md',text:'older soul\n'});
""")


@pytest.mark.parametrize("version_id", [
    "'../x'", "'20261112T010203Z-0123abcd'", "'20261112T010203Z-abcdefg.md'", "'20261112T010203Z-' + 'a'.repeat(33) + '.md'",
    "'20261112T010203Z-0123ABCD.md'", "'20261112T010203Z-b8ff3045fe3af27283403b0d.md/..'", "''", "5", "undefined",
    "'20261112T010203Z-b8ff3045fe3af27283403b0d.md?x=1'",
])
def test_history_item_refuses_ids_that_are_not_version_names(tmp_path, version_id):
    run_bridge(tmp_path, "const id=%s;" % version_id + r"""
const message=itemMsg({id});
if(id===undefined)delete message.pixelhqSoulHistoryItem.id;
const r=await ask(message,'pixelhqSoulHistoryItemResult');
assert.equal(r.state,'error');assert.deepEqual(trace(),[]);
""")


def test_history_failures_are_reported_per_state(tmp_path):
    run_bridge(tmp_path, r"""
world.onRest=()=>{throw new Error('404 Not Found');};
let r=await ask(historyMsg(),'pixelhqSoulHistoryResult');
assert.equal(r.state,'error');assert.ok(r.message.includes('restart the Hermes gateway'));
r=await ask(itemMsg(),'pixelhqSoulHistoryItemResult');
assert.equal(r.state,'error');
world.onRest=()=>({rows:[]});
assert.equal((await ask(historyMsg(),'pixelhqSoulHistoryResult')).state,'error');
world.onRest=()=>[];
world.onRest=()=>({nothing:true});
assert.equal((await ask(itemMsg(),'pixelhqSoulHistoryItemResult')).state,'error');
world.onRest=null;world.routes=[];
assert.equal((await ask(historyMsg({remote:true}),'pixelhqSoulHistoryResult')).state,'unreachable');
world.routes=[ROUTE,{...ROUTE,connectionId:'c2'}];
assert.equal((await ask(itemMsg({remote:true}),'pixelhqSoulHistoryItemResult')).state,'ambiguous');
delete ctx.rest;
assert.equal((await ask(historyMsg(),'pixelhqSoulHistoryResult')).state,'unsupported');
assert.equal((await ask(itemMsg(),'pixelhqSoulHistoryItemResult')).state,'unsupported');
""")


def test_history_messages_never_write_and_a_restore_is_an_ordinary_save(tmp_path):
    run_bridge(tmp_path, r"""
await ask(historyMsg(),'pixelhqSoulHistoryResult');
const item=await ask(itemMsg(),'pixelhqSoulHistoryItemResult');
assert.ok(log.every(e=>e.method.startsWith('GET ')),'history reads only');
log.length=0;
const restored=await ask(saveMsg({soul:item.text}),'pixelhqSoulSaveResult');
assert.deepEqual(trace(),%s);assert.equal(restored.state,'saved');assert.equal(world.soul,'older soul\n');
// the replaced version is itself backed up
assert.equal(log[1].params.text,OLD);
""" % json.dumps(SAVE_STEPS))


def test_bot_ids_the_history_cannot_key_are_refused_without_calls(tmp_path):
    run_bridge(tmp_path, r"""
for(const bot of ['_bot','-bot','.bot']){
  assert.equal((await ask(historyMsg({bot}),'pixelhqSoulHistoryResult')).state,'error');
  assert.equal((await ask(itemMsg({bot}),'pixelhqSoulHistoryItemResult')).state,'error');
}
assert.deepEqual(trace(),[]);
""")


# ---------------------------------------------------------------- update check (§5)

def test_update_available_from_the_catalog_row(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[{name:'other',key:'other',update_available:true},SELF];
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.deepEqual(trace(),['request plugins.manage']);assert.deepEqual(log[0].params,{action:'list'});
assert.deepEqual(r,{rid:RID,state:'available',installed:{version:'1.2.0',sha:'a'.repeat(40)},
  available:{version:'1.3.0',sha:'b'.repeat(40)},canNavigate:false});
""")


def test_update_current_when_the_catalog_install_is_up_to_date(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[{...SELF,update_available:false,version:'1.3.0',installed_sha:'b'.repeat(40)}];
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'current');assert.deepEqual(r.installed,{version:'1.3.0',sha:'b'.repeat(40)});
assert.deepEqual(r.available,{version:'1.3.0',sha:'b'.repeat(40)});
world.plugins=[{...SELF,update_available:false,catalog_version:null,catalog_sha:null}];clock+=7*3600*1000;
const t=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(t.state,'current');assert.equal(t.available,undefined);
""")


@pytest.mark.parametrize("plugins, expected", [
    ("[]", "unavailable"),
    ("[{name:'other',key:'other',update_available:true}]", "unavailable"),
    ("[{...SELF,update_available:null}]", "unavailable"),
    ("[{...SELF,update_available:undefined}]", "unavailable"),
    ("[{...SELF,update_available:'true'}]", "unavailable"),
    ("[{...SELF,catalog_name:null,update_available:false}]", "unavailable"),
    ("[{...SELF,catalog_name:null,update_available:true}]", "unavailable"),
    ("[{...SELF,catalog_name:'',update_available:true}]", "unavailable"),
    ("[{...SELF,catalog_name:null,update_available:true,update_target:'1.4.0'}]", "available"),
    ("[{...SELF,catalog_name:null,update_available:false,update_target:'1.4.0'}]", "unavailable"),
    ("[{...SELF,catalog_name:null,catalog_version:null,catalog_sha:null,update_available:true,update_target:{version:'1.4.0',sha:'c'.repeat(40)}}]",
     "available"),
], ids=["no-row", "only-other-plugin", "null-flag", "missing-flag", "string-flag", "not-catalog-false", "not-catalog-true-no-target",
        "empty-catalog-name", "target-string-version", "target-but-false", "target-object"])
def test_update_states_follow_the_row_rules(tmp_path, plugins, expected):
    run_bridge(tmp_path, "world.plugins=%s;" % plugins + r"""
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'%s');assert.equal(r.rid,RID);
assert.equal(typeof r.installed,'object');
if(r.state==='unavailable')assert.equal(typeof r.message,'string');
if(r.state==='available')assert.ok(r.available.version||r.available.sha);
""" % expected)


def test_update_target_forms_and_version_checks(tmp_path):
    run_bridge(tmp_path, r"""
const bare={...SELF,catalog_name:null,catalog_version:null,catalog_sha:null,update_available:true};
for(const [target,want] of [['1.4.0',{version:'1.4.0',sha:null}],['abcdef1234',{version:null,sha:'abcdef1234'}],
    [{version:'1.5.0',sha:'1234567'},{version:'1.5.0',sha:'1234567'}]]){
  clock+=7*3600*1000;world.plugins=[{...bare,update_target:target}];
  const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
  assert.equal(r.state,'available');assert.deepEqual(r.available,want);
}
// a target without a usable version or sha is no target at all
clock+=7*3600*1000;world.plugins=[{...bare,update_target:{version:'bad value!',sha:'zz'}}];
assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).state,'unavailable');
clock+=7*3600*1000;
world.plugins=[{...SELF,version:'<img src=x>',installed_sha:'not a sha',catalog_version:'1.3.0 \n',catalog_sha:5}];
const t=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.deepEqual(t.installed,{version:null,sha:null});assert.deepEqual(t.available,{version:null,sha:null});
""")


def test_row_selection_prefers_the_key_then_the_name_and_never_a_partial_match(tmp_path):
    run_bridge(tmp_path, r"""
const named={name:'pixel-hq',key:'something-else',version:'9.9.9',update_available:false,catalog_name:'x'};
world.plugins=[{name:'pixel-hq-extra',key:'pixel-hq-extra',update_available:true,version:'8.8.8'},named,{...SELF,version:'1.2.0'}];
assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).installed.version,'1.2.0');
clock+=7*3600*1000;world.plugins=[{name:'pixel-hq-extra',key:'pixel-hq-extra',update_available:true},named];
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'current');assert.equal(r.installed.version,'9.9.9');
clock+=7*3600*1000;world.plugins=[{name:'pixel-hq-extra',key:'pixel-hq-extra',update_available:true}];
assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).state,'unavailable');
""")


def test_update_is_asked_at_most_once_per_six_hours_and_not_per_message(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[SELF];
const first=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(first.state,'available');
const other='fedcba9876543210fedcba9876543210';
const second=await ask(updateMsg({rid:other,force:true}),'pixelhqUpdateInfoResult');
assert.equal(second.rid,other);assert.equal(second.state,'available');
assert.equal(log.filter(e=>e.method==='plugins.manage').length,1,'a force flag is not offered');
clock+=6*3600*1000-1;
await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(log.length,1);
clock+=1;
world.plugins=[{...SELF,update_available:false}];
const refreshed=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(log.length,2);assert.equal(refreshed.state,'current');
await ask(updateMsg(),'pixelhqUpdateInfoResult');assert.equal(log.length,2);
// other traffic (snapshot-like messages, profile reads) never triggers a plugin list call
await ask(profileMsg(),'pixelhqProfileResult');
assert.equal(log.filter(e=>e.method==='plugins.manage').length,2);
""")


def test_concurrent_update_requests_share_one_call(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[SELF];
world.onPlugins=async()=>{await flushFor(60);};
posts.length=0;
for(const rid of [RID,'fedcba9876543210fedcba9876543210','00112233445566778899aabbccddeeff'])
  listeners.get('message')({source:frame,data:updateMsg({rid})});
for(let i=0;i<400&&posts.length<3;i++)await flushFor(5);
assert.equal(posts.length,3);assert.deepEqual(posts.map(p=>p.pixelhqUpdateInfoResult.rid).sort(),
  [RID,'fedcba9876543210fedcba9876543210','00112233445566778899aabbccddeeff'].sort());
assert.equal(log.filter(e=>e.method==='plugins.manage').length,1);
""")


@pytest.mark.parametrize("setup", [
    "world.onPlugins=()=>{throw new Error('gateway offline');};",
    "world.onPlugins=()=>({plugins:'none'});",
    "world.onPlugins=()=>null;",
    "world.onPlugins=()=>({});",
], ids=["rejects", "plugins-not-a-list", "null-answer", "no-plugins"])
def test_every_update_outcome_is_cached_for_six_hours_errors_included(tmp_path, setup):
    run_bridge(tmp_path, setup + r"""
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'error');assert.equal(typeof r.message,'string');assert.ok(r.message.length<=200);assert.equal(r.installed,undefined);
world.onPlugins=null;world.plugins=[SELF];
const again=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(again.state,'error');assert.equal(log.length,1,'a reopened page does not ask again');
clock+=6*3600*1000-1;assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).state,'error');assert.equal(log.length,1);
clock+=1;assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).state,'available');assert.equal(log.length,2);
""")


def test_unknown_method_or_missing_host_is_unavailable_and_cached_like_any_outcome(tmp_path):
    run_bridge(tmp_path, r"""
world.onPlugins=()=>{throw new Error('unknown method: plugins.manage');};
let r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'unavailable');assert.equal(r.message,'not supported by this Hermes Desktop version');
world.onPlugins=null;world.plugins=[SELF];
r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'unavailable');assert.equal(log.length,1);
clock+=6*3600*1000;
r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'available');
clock+=7*3600*1000;
delete sdk.host.request;log.length=0;
r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'unavailable');assert.deepEqual(log,[]);
""")


@pytest.mark.parametrize("body", ["null", "'text'", "[]", "{}", "{rid:'short'}", "{rid:5}"])
def test_update_request_needs_a_request_id(tmp_path, body):
    run_bridge(tmp_path, r"""
world.plugins=[SELF];
posts.length=0;listeners.get('message')({source:frame,data:{pixelhqUpdateInfo:BODY}});
await flushFor(40);
assert.equal(posts.length,1);const r=posts[0].pixelhqUpdateInfoResult;
assert.equal(r.state,'error');assert.equal(r.rid,null);assert.deepEqual(log,[]);
""".replace("BODY", body))


def test_the_update_cache_is_shared_across_page_remounts(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[SELF];
const Page=makePage(ctx,{now:()=>clock});
effects.length=0;Page();effects.forEach(effect=>effect());
await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(log.length,1);
// the page component mounts again (navigating away and back): same makePage closure, same cache
effects.length=0;Page();effects.forEach(effect=>effect());
await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(log.length,1);
""")


# ---------------------------------------------------------------- nothing else changes

def test_bridge_blocks_never_submit_prompts_or_touch_other_profile_sections(tmp_path):
    run_bridge(tmp_path, r"""
world.routes=[ROUTE];world.plugins=[SELF];
for(const remote of [false,true]){
  await ask(profileMsg({remote}),'pixelhqProfileResult');
  await ask(saveMsg({remote}),'pixelhqSoulSaveResult');world.soul=OLD;
  await ask(historyMsg({remote}),'pixelhqSoulHistoryResult');
  await ask(itemMsg({remote}),'pixelhqSoulHistoryItemResult');
}
await ask(updateMsg(),'pixelhqUpdateInfoResult');
const methods=new Set(log.filter(e=>e.method&&!e.method.includes(' ')).map(e=>e.method));
assert.deepEqual([...methods].sort(),['plugins.manage','profiles.configure','profiles.describe']);
for(const e of log.filter(e=>e.method==='profiles.configure'))assert.deepEqual(Object.keys(e.params).sort(),['name','soul']);
for(const e of log.filter(e=>e.method==='plugins.manage'))assert.deepEqual(e.params,{action:'list'});
""")
