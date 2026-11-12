"""Version id contract (R4-F2): what the backend lists, the bridge and the page must all accept.

The ids come from a real save through `pixelhq/soul_history.py`; they run through the real `runHistory` / `runHistoryItem`
of `desktop/plugin.js` in Node (simulated host, `ctx.rest` answering the real list and the real item text) and through the
page's own regular expression, read from `pixelhq/ui/js/39-soul-history.js`. Nothing here repeats the rule, so a change in one
of the three copies fails this test instead of silently emptying the history again.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pixelhq import soul_history as sh
from tests.test_profile_bridge import ROOT, run_bridge

START = datetime(2026, 11, 12, 2, 29, 27, tzinfo=timezone.utc)
RIDS = {"24": "b8ff3045fe3af27283403b0d", "32": "0123456789abcdef0123456789abcdef"}


def js_pattern(relative: str, name: str) -> str:
    """The source of the regular expression literal assigned to `name` (a const) in a JavaScript file."""
    source = (ROOT / relative).read_text(encoding="utf-8")
    match = re.search(r"const " + name + r" = /(.+)/[a-z]*;?\s*$", source, flags=re.M)
    assert match, f"{name} not found in {relative}"
    return match.group(1)


@pytest.fixture
def listed(tmp_path):
    """Save once per rid length through the backend, return {id: text} exactly as the backend lists and serves it."""
    cfg = {"hermes_home": str(tmp_path / "home")}
    for step, rid in enumerate(RIDS.values()):
        sh.save({"bot": "ops-bot", "sourceKey": "local", "text": f"soul saved under {len(rid)} characters\n", "rid": rid},
                cfg, START + timedelta(seconds=step))
    rows = sh.list_versions("ops-bot", "local", cfg)
    return {row["id"]: sh.item("ops-bot", "local", row["id"], cfg)["text"] for row in rows}, rows


def test_the_three_copies_of_the_version_id_rule_are_the_same_pattern():
    backend = sh.FILE_RE.pattern.replace("(", "").replace(")", "")
    bridge = js_pattern("desktop/plugin.js", "VERSION_ID_RE")
    page = js_pattern("pixelhq/ui/js/39-soul-history.js", "CONF_VERSION_ID")
    assert bridge == page == "^" + backend + "$"


def test_backend_bridge_and_page_accept_every_version_id_the_backend_lists(tmp_path, listed):
    texts, rows = listed
    assert sorted(len(r["id"]) for r in rows) == [len("20261112T022927Z-.md") + 24, len("20261112T022927Z-.md") + 32]
    page_rule = js_pattern("pixelhq/ui/js/39-soul-history.js", "CONF_VERSION_ID")
    probe = (
        "const ROWS=" + json.dumps(rows) + ";const TEXTS=" + json.dumps(texts) + ";const PAGE=new RegExp(" + json.dumps(page_rule) + ");\n"
        + r"""
world.onRest=path=>{
  if(path.startsWith('/soul-history/item?'))return {text:TEXTS[decodeURIComponent(path.split('&id=')[1])]};
  if(path.startsWith('/soul-history?'))return ROWS;
};
const listing=await ask(historyMsg(),'pixelhqSoulHistoryResult');
assert.equal(listing.state,'ready');
assert.deepEqual(listing.items.map(i=>i.id),ROWS.map(r=>r.id),'the bridge dropped a listed version');
for(const row of ROWS){
  assert.ok(PAGE.test(row.id),'the page rejects '+row.id);
  log.length=0;
  const got=await ask(itemMsg({id:row.id}),'pixelhqSoulHistoryItemResult');
  assert.deepEqual(trace(),['rest GET /soul-history/item']);
  assert.equal(log[0].path,'/soul-history/item?bot=ops-bot&sourceKey=local&id='+row.id);
  assert.deepEqual(got,{rid:RID,state:'ready',id:row.id,text:TEXTS[row.id]});
}
""")
    run_bridge(tmp_path, probe, name="soul-history-contract")
