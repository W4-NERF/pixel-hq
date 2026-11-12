"""Demo/HTML smoke and plain-Node behavior checks (no browser or network)."""
import json
import re
import subprocess
import sys
from pathlib import Path

from pixelhq.demo import snapshot
from pixelhq.page import page_html

ROOT = Path(__file__).resolve().parents[1]
NEW_KEYS = {"xpBySource", "bySource", "selfReviews", "attrsSource"}


def test_demo_and_page_include_the_scoring_schema():
    data = snapshot()
    assert data["demo"] is True
    assert data["warnings"] == []
    for bot in data["bots"]:
        assert NEW_KEYS <= bot.keys()
        assert set(bot["xpBySource"]) == {"kanban", "reviews"}
        assert sum(bot["bySource"][s]["pass"] for s in bot["bySource"]) == bot["p"]
        assert sum(bot["bySource"][s]["revise"] for s in bot["bySource"]) == bot["r"]
        assert sum(bot["bySource"][s]["fail"] for s in bot["bySource"]) == bot["f"]
    html = page_html(data)
    assert '"xpBySource"' in html
    assert '"demo": true' in html
    assert "/*PIXELHQ_DATA*/null" not in html


def test_demo_reports_signed_raw_source_xp_without_distributing_bucket_floors():
    # This seed contains a review-only failure with zero total XP.
    data = snapshot(seed=6)
    assert any(bot["xp"] == 0 and bot["f"] > 0 for bot in data["bots"])
    weights = data["cfg"]["xp"]
    for bot in data["bots"]:
        expected_sources = {
            source: sum(counts[verdict] * weights[verdict] for verdict in ("pass", "revise", "fail"))
            for source, counts in bot["bySource"].items()
        }
        assert bot["xpBySource"] == expected_sources
        for bucket, key in (("own", "xpOwn"), ("summ", "xpSummon")):
            raw = sum(count * weights[verdict] for count, verdict in zip(bot[bucket], ("pass", "revise", "fail"), strict=True))
            assert bot[key] == max(0, raw)
        assert bot["xp"] == bot["xpOwn"] + bot["xpSummon"]


def test_ui_renders_attribute_sources_and_changes_requested(tmp_path):
    data = snapshot()
    script = re.search(r"<script>(.*?)</script>", page_html(), re.S).group(1)
    prelude = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8")
    probe = """
const bot = DATA.bots[0];
for (const [source, label] of [['kanban','from Kanban'], ['reviews','from reviews']]) {
  bot.attrsSource = source;
  detail(bot);
  assert.ok(elements.get('detail').innerHTML.includes('<span class="mut">(' + label + ')</span>'));
}
bot.attrsSource = null;
detail(bot);
assert.ok(!elements.get('detail').innerHTML.includes('(from '));
assert.deepEqual(evk('changes_requested'), ['changes requested', 'warn']);
DATA.events = [{ts:0, bot:'ops-bot', kind:'changes_requested', text:'<unsafe>'}];
assert.ok(logHtml().includes('changes requested'));
assert.ok(logHtml().includes('&lt;unsafe&gt;'));
DATA.events = [{ts:0, bot:'ops-bot', kind:'qc-pass', selfReview:true, source:'ui', text:'Sample review'}];
assert.ok(logHtml().includes('self-review · no XP'));
assert.ok(!logHtml().includes('+10 XP'));
console.log('ui scoring behavior: ok');
"""
    path = tmp_path / "ui-scoring.js"
    path.write_text(prelude + script + "\nDATA = " + json.dumps(data) + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ui scoring behavior: ok" in result.stdout


def test_js_gate_checks_the_split_ui():
    result = subprocess.run([sys.executable, "tools/jscheck.py"], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "desktop/plugin.js: ok" in result.stdout
    assert "pixelhq/ui/js (bundle): ok" in result.stdout
