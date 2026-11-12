"""Roster rules never invent local profiles or discard declared remote bots."""

import json
import re
import subprocess
from pathlib import Path

from pixelhq import config
from pixelhq.demo import snapshot as demo_snapshot
from pixelhq.page import page_html
from tests.test_scoring_collect import collector


def test_file_roster_drops_ghost_adds_recruit_and_keeps_remote(fleet, monkeypatch):
    module = collector(fleet, monkeypatch)
    roster = config.load_roster()
    roster["bots"] = [bot for bot in roster["bots"] if bot["id"] != "ops-bot"]
    roster["bots"].append({"id": "missing-bot", "title": "Phantom", "zone": "crew"})
    config.roster_path().write_text(json.dumps(roster), encoding="utf-8")

    state = module.read_state

    def only_local(bot, cfg):
        assert bot != "remote-bot", "Remote entries must not read local state"
        return state(bot, cfg)

    monkeypatch.setattr(module, "read_state", only_local)
    snapshot = module.collect()
    bots = {bot["id"]: bot for bot in snapshot["bots"]}
    assert set(bots) == {"default", "ops-bot", "remote-bot"}
    assert snapshot["cfg"]["rosterSource"] == "file"
    assert any("missing-bot" in warning for warning in snapshot["warnings"])
    assert all(len(warning) <= 120 for warning in snapshot["warnings"])
    recruit = bots["ops-bot"]
    assert recruit["auto"] is True
    assert recruit["title"] == "Recruit"
    assert recruit["cls"] == "Sample operator"
    assert recruit["color"] == next(bot["color"] for bot in module.collect()["bots"] if bot["id"] == "ops-bot")
    assert bots["remote-bot"]["model"] == "remote"


def test_live_uses_the_same_ghost_recruit_and_remote_rules(fleet, monkeypatch):
    from pixelhq import live

    collector(fleet, monkeypatch)
    roster = config.load_roster()
    roster["bots"] = [bot for bot in roster["bots"] if bot["id"] != "ops-bot"]
    roster["bots"].append({"id": "missing-bot"})
    config.roster_path().write_text(json.dumps(roster), encoding="utf-8")
    state = live.read_sessions

    def only_local(bot, now, cfg):
        assert bot != "remote-bot", "Remote entries must not read local state"
        return state(bot, now, cfg)

    monkeypatch.setattr(live, "read_sessions", only_local)
    snapshot = live.query()
    assert set(snapshot["bots"]) == {"default", "ops-bot", "remote-bot"}
    assert any("missing-bot" in warning for warning in snapshot["warnings"])
    assert snapshot["bots"]["remote-bot"]["remote"] is True


def test_profile_failure_is_visible_in_collected_warnings(fleet, monkeypatch):
    module = collector(fleet, monkeypatch)
    (fleet.root / "profiles" / "ops-bot" / "config.yaml").write_text("model: [", encoding="utf-8")
    snapshot = module.collect()
    assert any("ops-bot/config.yaml" in warning for warning in snapshot["warnings"])
    assert "ops-bot" in {bot["id"] for bot in snapshot["bots"]}


def test_remote_entry_never_inherits_a_same_named_local_gateway(fleet, monkeypatch):
    module = collector(fleet, monkeypatch)
    roster = config.load_roster()
    next(bot for bot in roster["bots"] if bot["id"] == "ops-bot")["remote"] = True
    config.roster_path().write_text(json.dumps(roster), encoding="utf-8")
    (fleet.root / "profiles" / "ops-bot" / "gateway.pid").write_text("invalid", encoding="utf-8")
    snapshot = module.collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["status"] == "idle"
    assert bot["model"] == "remote"
    assert bot["gateway"] is None


def test_footer_warnings_and_no_heartbeat_tasks_are_visible_in_ui(tmp_path):
    script = re.search(r"<script>(.*?)</script>", page_html(), re.S).group(1)
    prelude = (Path(__file__).parent / "ui_dom.cjs").read_text(encoding="utf-8")
    probe = """
DATA.warnings = ['sample profile: <img src=x onerror=bad()>'];
LIVE = {generated:DATA.generated, warnings:['sample board: missing sessions'], bots:{}};
hud();
const footer = elements.get('foot');
assert.ok(footer.textContent.includes(DATA.warnings[0]));
assert.ok(footer.textContent.includes(LIVE.warnings[0]));
assert.equal(footer.innerHTML, '');
const bot = DATA.bots[0];
LIVE.bots[bot.id] = {active:true, sessions:[], tasks:[{id:'t_example', board:'sample',
  title:'Inspect sample job', heartbeatAt:null, heartbeatAge:null, startedAt:null, pid:null}]};
assert.equal(liveStatus(bot).status, 'running');
assert.ok(liveStatus(bot).label.includes('no heartbeat'));
liveTab();
assert.ok(elements.get('lactive').innerHTML.includes('Inspect sample job'));
assert.ok(elements.get('lactive').innerHTML.includes('no heartbeat'));
console.log('roster warnings and legacy live UI: ok');
"""
    path = tmp_path / "roster-ui.js"
    path.write_text(prelude + script + "\nDATA = " + json.dumps(demo_snapshot()) + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "roster warnings and legacy live UI: ok" in result.stdout


def test_missing_roster_generates_headquarters_without_example_bots(fleet, monkeypatch):
    module = collector(fleet, monkeypatch, orchestrator_profile="ops-bot")
    (fleet.root / "plugin-data" / "pixel-hq" / "roster.json").unlink()
    roster = config.load_roster()


    assert roster["rooms"] == [{"id": "hq", "label": "HEADQUARTERS", "main": True,
                                "zones": [{"id": "command", "label": "COMMAND"},
                                          {"id": "crew", "label": "CREW"}]}]
    snapshot = module.collect()
    assert snapshot["cfg"]["rosterSource"] == "generated"
    bots = {bot["id"]: bot for bot in snapshot["bots"]}
    assert set(bots) == {"default", "ops-bot"}
    assert bots["ops-bot"]["zone"] == "command"
    assert bots["ops-bot"]["leader"] is True
    assert bots["default"]["zone"] == "crew"
    assert all(bot["auto"] for bot in bots.values())
