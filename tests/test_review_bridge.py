"""Run the Desktop bridge with SDK/React stubs; no app or network required."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["success", "invalid", "transport", "refresh"])
def test_review_bridge_posts_only_from_its_frame_and_refreshes_on_success(tmp_path, mode):
    src = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    src = re.sub(r"^import .*?$", "", src, flags=re.M)
    src = re.sub(r"^export default", "const plugin =", src, flags=re.M)
    prelude = """
const assert=require('node:assert/strict');
const posts=[], calls=[], cache=[], effects=[], listeners=new Map();
const frame={postMessage:m=>posts.push(m)};
const window={addEventListener:(t,f)=>listeners.set(t,f),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}});
const useState=()=>[null,()=>{}];
const useCallback=f=>f;
const useEffect=f=>effects.push(f);
const jsx=()=>null;
const sdk={useTheme:()=>({resolvedMode:'dark'}),useQuery:()=>({data:{cfg:{},bots:[]}}),useQueryClient:()=>({setQueryData:(k,d)=>cache.push([k,d])}),
  host:{},PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{}};
const ctx={rest:(path, options)=>{
 calls.push({path,options});
 if(path==='/page')return Promise.resolve({html:'<sample>'});
 if(path==='/review'){
  if(MODE==='transport')return Promise.reject(new Error('404 sample'));
  return Promise.resolve({ok:MODE!=='invalid',message:MODE==='invalid'?'Invalid sample':'Review saved.'});
 }
 if(path==='/snapshot?max_age=0'){
  if(MODE==='refresh')return Promise.reject(new Error('sample refresh failed'));
  return Promise.resolve({fresh:true});
 }
 throw Error('unexpected REST call '+path);
}};
""".replace("MODE", json.dumps(mode))
    probe = """
(async()=>{
 makePage(ctx)();effects.forEach(f=>f());
 const onMsg=listeners.get('message');
 const body={agent:'ops-bot',verdict:'pass',dims:{safety:5},ref:'Sample',sessionId:'sample-session'};
 onMsg({source:{},data:{pixelhqReview:body}});
 assert.equal(calls.filter(c=>c.path==='/review').length,0);
 onMsg({source:frame,data:{pixelhqReview:body}});
 await new Promise(resolve=>setImmediate(resolve));
 const reviewCall=calls.find(c=>c.path==='/review');
 assert.ok(reviewCall,'pixelhqReview must call POST /review');
 assert.deepEqual(reviewCall.options,{method:'POST',body});
 const results=posts.filter(p=>p.pixelhqReviewResult).map(p=>p.pixelhqReviewResult);
 assert.equal(results.length,1,'a failed refresh must not replace a successful write result');
 const result=results[0];
 assert.equal(result.agent,body.agent);assert.equal(result.sessionId,body.sessionId);
 assert.equal(result.ok,MODE==='success'||MODE==='refresh');
 if(MODE==='transport')assert.ok((result.message||result.error).includes('restart the Hermes gateway'));
 const refreshes=calls.filter(c=>c.path==='/snapshot?max_age=0');
 assert.equal(refreshes.length,(MODE==='success'||MODE==='refresh')?1:0);
 assert.equal(cache.length,MODE==='success'?1:0);
 if(MODE==='refresh')assert.ok(posts.some(p=>p.pixelhqError));
 console.log('desktop review bridge: ok');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace("MODE", json.dumps(mode))
    path = tmp_path / "review-bridge.cjs"
    path.write_text(prelude + src + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
