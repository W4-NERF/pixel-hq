"""The payload emitted by UI events is accepted by the real writer and collector."""
import json

from pixelhq import collect, config, roster
from pixelhq.demo import snapshot
from tests.test_roster_ui import run_roster


def test_editor_payload_roundtrips_through_fixed_file_and_fresh_collector(tmp_path, monkeypatch):
    output = run_roster(tmp_path, """
tab('roster');const root=document.getElementById('roster-editor');
root.querySelector('[data-roster-new-zone]').value='workshop';
root.querySelector('[data-roster-new-zone-label]').value='Workshop & lab';
root.querySelector('[data-roster-add-zone]').onclick();
root.querySelector('[data-roster-new-bot]').value='remote-helper';
root.querySelector('[data-roster-add-bot]').onclick();
let row=root.querySelectorAll('[data-roster-bot]').at(-1);
let input=row.querySelector('[data-roster-field="title"]');input.value='New <helper>';input.oninput();
input=row.querySelector('[data-roster-field="sprite"]');input.value='medic';input.onchange();
input=row.querySelector('[data-roster-field="zone"]');input.value='workshop';input.onchange();
row=root.querySelectorAll('[data-roster-bot]').at(-1);input=row.querySelector('[data-roster-leader]');input.checked=true;input.onchange();
root.querySelector('[data-roster-save]').onclick();
console.log('PAYLOAD:'+JSON.stringify(messages.find(m=>m.pixelhqRoster).pixelhqRoster));
""", iframe=True)
    body = json.loads(next(line.removeprefix("PAYLOAD:") for line in output.splitlines() if line.startswith("PAYLOAD:")))
    home = tmp_path / "sample-home"
    for bot in snapshot()["bots"]:
        if not bot.get("remote"):
            directory = home if bot["id"] == "default" else home / "profiles" / bot["id"]
            directory.mkdir(parents=True)
            (directory / "config.yaml").write_text("model: sample/model\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(config, "_DIRS", [home / "plugin-data" / "pixel-hq"])
    monkeypatch.setattr(config, "load_config_readonly", lambda: {})
    cfg = config.load()
    assert roster.save(body, cfg, collect.read_profiles(cfg=cfg)) == {"ok": True, "message": "Roster saved."}
    saved = json.loads((home / "plugin-data" / "pixel-hq" / "roster.json").read_text(encoding="utf-8"))
    assert saved == body["roster"]
    fresh = collect.collect()
    assert fresh["cfg"]["rosterSource"] == "file"
    helper = next(bot for bot in fresh["bots"] if bot["id"] == "remote-helper")
    assert {key: helper[key] for key in ("title", "sprite", "zone", "leader", "remote")} == {
        "title": "New <helper>", "sprite": "medic", "zone": "workshop", "leader": True, "remote": True}
    assert sum(bool(bot.get("leader")) for bot in fresh["bots"]) == 1
    assert next(zone for room in fresh["cfg"]["rooms"] for zone in room["zones"] if zone["id"] == "workshop")["label"] == "Workshop & lab"
