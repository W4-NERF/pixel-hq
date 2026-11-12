"""SDK theme messages at ready and on resolved-mode changes, using offline React stubs."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_theme_bridge(tmp_path, probe, *, theme_hook="()=>({resolvedMode:mode})"):
    source = (ROOT / "desktop/plugin.js").read_text(encoding="utf-8")
    source = re.sub(r"^import .*?$", "", source, flags=re.M)
    source = re.sub(r"^export default", "const plugin =", source, flags=re.M)
    prelude = """
const assert=require('node:assert/strict');
const posts=[],listeners=new Map(),effects=[],pending=[];
let mode='light',effectIndex=0,postCallback;
const frame={postMessage:message=>posts.push(message)},query={};
const window={addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:()=>{}};
const useRef=()=>({current:{contentWindow:frame}}),useState=()=>[null,()=>{}];
const useCallback=fn=>postCallback||(postCallback=fn);
function useEffect(callback,deps){
  const index=effectIndex++,previous=effects[index];
  if(!previous||deps.some((value,i)=>value!==previous[i])){effects[index]=deps;pending.push(callback);}
}
const cache={setQueryData:()=>{}};
const jsx=()=>null;
const sdk={useQuery:()=>query,useQueryClient:()=>cache,host:{},PALETTE_AREA:'',ROUTES_AREA:'',SIDEBAR_NAV_AREA:'',SandboxedFrame:{}};
sdk.useTheme=THEME_HOOK;
const ctx={rest:async path=>{assert.equal(path,'/page');return {html:'<sample>'};}};
""".replace("THEME_HOOK", theme_hook)
    script = prelude + source + ";\nconst Page=makePage(ctx);\n"
    script += "function render(){effectIndex=0;Page();pending.splice(0).forEach(callback=>callback());}\n"
    script += probe + "\nconsole.log('desktop theme bridge: ok');\n"
    path = tmp_path / "theme-bridge.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ready_sends_theme_even_without_a_snapshot_and_checks_frame_source(tmp_path, mode):
    run_theme_bridge(tmp_path, """
mode=MODE;render();posts.length=0;
listeners.get('message')({source:{},data:{pixelhqReady:true}});
assert.deepEqual(posts,[]);
listeners.get('message')({source:frame,data:{pixelhqReady:true}});
assert.deepEqual(posts,[{pixelhqTheme:{mode:MODE}}]);
""".replace("MODE", json.dumps(mode)))


def test_resolved_mode_changes_post_without_reload_and_ready_uses_latest_mode(tmp_path):
    run_theme_bridge(tmp_path, """
render();assert.deepEqual(posts,[{pixelhqTheme:{mode:'light'}}]);posts.length=0;
render();assert.deepEqual(posts,[]);
mode='dark';render();assert.deepEqual(posts,[{pixelhqTheme:{mode:'dark'}}]);posts.length=0;
listeners.get('message')({source:frame,data:{pixelhqReady:true}});
assert.deepEqual(posts,[{pixelhqTheme:{mode:'dark'}}]);posts.length=0;
mode='light';render();assert.deepEqual(posts,[{pixelhqTheme:{mode:'light'}}]);
""")


@pytest.mark.parametrize("mode", [None, "auto", "unknown"])
def test_sdk_unresolved_mode_never_leaks_an_invalid_frame_mode(tmp_path, mode):
    run_theme_bridge(tmp_path, """
mode=MODE;render();
assert.deepEqual(posts,[{pixelhqTheme:{mode:'dark'}}]);
""".replace("MODE", json.dumps(mode)))


def test_host_reads_the_sdk_theme_hook_through_a_namespace_import():
    source = (ROOT / "desktop/plugin.js").read_text(encoding="utf-8")
    assert re.search(r"^import \* as sdk from '@hermes/plugin-sdk'$", source, flags=re.M)
    assert not re.search(r"import \{[^}]*\}\s*from '@hermes/plugin-sdk'", source)
    assert re.search(r"typeof sdk\.useTheme === 'function'", source)


@pytest.mark.parametrize("hook", ["undefined", "null", "'dark'", "{resolvedMode:'light'}"])
def test_missing_or_non_function_theme_hook_posts_no_mode_and_nothing_else_breaks(tmp_path, hook):
    run_theme_bridge(tmp_path, """
render();assert.deepEqual(posts,[]);
listeners.get('message')({source:frame,data:{pixelhqReady:true}});
assert.deepEqual(posts,[],'without a host theme the frame keeps its own setting/default');
mode='dark';render();assert.deepEqual(posts,[]);
""", theme_hook=hook)
