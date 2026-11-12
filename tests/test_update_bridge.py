"""Update notice, bridge side (R4-04): the `canNavigate` flag and the fixed Open Plugins route.

Same simulated Desktop host as the R4-02 bridge tests (`tests/test_profile_bridge.py`); no real gateway.
"""
import pytest

from .test_profile_bridge import run_bridge


def test_the_update_answer_says_whether_the_host_can_navigate_and_does_not_cache_that(tmp_path):
    run_bridge(tmp_path, r"""
world.plugins=[SELF];
const navigations=[];
assert.equal((await ask(updateMsg(),'pixelhqUpdateInfoResult')).canNavigate,false,'the simulated host has no navigate');
sdk.host.navigate=route=>navigations.push(route);
const again=await ask(updateMsg({rid:'fedcba9876543210fedcba9876543210'}),'pixelhqUpdateInfoResult');
assert.equal(again.canNavigate,true);
assert.equal(again.state,'available');
assert.equal(log.filter(e=>e.method==='plugins.manage').length,1,'the plugin list itself stays cached');
for(const odd of ['yes',1,{}]){
  sdk.host.navigate=odd;
  assert.equal((await ask(updateMsg({rid:'00112233445566778899aabbccddeeff'}),'pixelhqUpdateInfoResult')).canNavigate,false);
}
assert.deepEqual(navigations,[],'asking for the update never navigates');
""")


def test_open_plugins_navigates_to_the_one_fixed_route(tmp_path):
    run_bridge(tmp_path, r"""
const navigations=[];
sdk.host.navigate=(...args)=>{navigations.push(args);};
posts.length=0;log.length=0;
listeners.get('message')({source:frame,data:{pixelhqOpenPlugins:true}});
await flushFor(30);
assert.deepEqual(navigations,[['/capabilities?tab=plugins']]);
assert.deepEqual(posts,[],'no answer is posted');
assert.deepEqual(log,[],'no gateway call, no backend call');
""")


@pytest.mark.parametrize("value", ["'/capabilities?tab=plugins'", "'true'", "1", "{path:'/x'}", "['/x']", "null", "false"])
def test_open_plugins_ignores_everything_but_the_boolean_true(tmp_path, value):
    run_bridge(tmp_path, r"""
const navigations=[];
sdk.host.navigate=(...args)=>{navigations.push(args);};
listeners.get('message')({source:frame,data:{pixelhqOpenPlugins:VALUE}});
listeners.get('message')({source:{},data:{pixelhqOpenPlugins:true}});
await flushFor(30);
assert.deepEqual(navigations,[]);
""".replace("VALUE", value))


def test_open_plugins_without_navigate_or_with_a_failing_navigate_is_harmless(tmp_path):
    run_bridge(tmp_path, r"""
process.on('unhandledRejection',e=>{console.error('unhandled',e);process.exitCode=1;});
world.plugins=[SELF];
listeners.get('message')({source:frame,data:{pixelhqOpenPlugins:true}});
sdk.host.navigate=()=>{throw new Error('route refused');};
listeners.get('message')({source:frame,data:{pixelhqOpenPlugins:true}});
sdk.host.navigate=()=>Promise.reject(new Error('route refused later'));
listeners.get('message')({source:frame,data:{pixelhqOpenPlugins:true}});
await flushFor(40);
const r=await ask(updateMsg(),'pixelhqUpdateInfoResult');
assert.equal(r.state,'available');
assert.equal(r.canNavigate,true,'the flag only says the function exists');
""")
