"""Round-two roster decisions exercised against real files and UI event payloads."""
import copy
import json
from pathlib import Path

import pytest

from pixelhq import collect, config, roster
from tests.test_roster_ui import run_roster
from tests.test_roster_save import body  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("length", [40, 41, 120])
def test_generated_recruit_role_fits_first_save(fleet, length):
    path = fleet.root / "plugin-data" / "pixel-hq" / "roster.json"
    path.unlink()
    description = "L" * length
    profile = fleet.root / "profiles" / "ops-bot" / "profile.yaml"
    profile.write_text("description: " + json.dumps(description) + "\n", encoding="utf-8")
    cfg = config.load()
    profiles = collect.read_profiles(cfg=cfg)
    bots = collect.roster_bots(profiles, cfg=cfg)
    role = next(bot["cls"] for bot in bots if bot["id"] == "ops-bot")
    assert role == (description if length <= 40 else description[:39] + "…")
    generated = config.load_roster()
    result = roster.save({"roster": {"rooms": generated["rooms"], "bots": bots}}, cfg, profiles)
    assert result == {"ok": True, "message": "Roster saved."}


@pytest.mark.parametrize("kind,entry_id,field", [("room", "hq", "label"), ("zone", "crew", "label"),
                                                ("bot", "ops-bot", "cls"), ("bot", "ops-bot", "color")])
def test_validation_error_names_the_entry_id(body, tmp_path, kind, entry_id, field):
    room = body["roster"]["rooms"][0]
    entry = {"room": room, "zone": room["zones"][0], "bot": body["roster"]["bots"][0]}[kind]
    entry[field] = "x" * 41
    result = roster.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})
    assert result["ok"] is False
    index = {"room": "rooms[0]", "zone": 'rooms[0] (id "hq").zones[0]', "bot": "bots[0]"}[kind]
    assert result["message"].startswith(f'{index} (id "{entry_id}").{field}: ')
    assert not (tmp_path / "plugin-data").exists()


def test_shipped_example_roundtrips_without_losing_schema_fields(tmp_path):
    example = json.loads((ROOT / "pixelhq" / "roster.example.json").read_text(encoding="utf-8"))
    original = copy.deepcopy(example)
    expected = copy.deepcopy(example)
    expected.pop("_doc")
    profiles = {bot["id"]: {} for bot in example["bots"] if not bot.get("remote")}
    result = roster.save({"roster": example}, {"hermes_home": str(tmp_path)}, profiles)
    assert result == {"ok": True, "message": "Roster saved."}
    assert json.loads((tmp_path / "plugin-data" / "pixel-hq" / "roster.json").read_text()) == expected
    assert example == original


@pytest.mark.parametrize("note,accepted", [("", True), ("n" * 80, True), ("n" * 81, False), (7, False)])
def test_room_note_limit(body, tmp_path, note, accepted):
    body["roster"]["rooms"][0]["note"] = note
    result = roster.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})
    assert result["ok"] is accepted
    if accepted:
        saved = json.loads((tmp_path / "plugin-data" / "pixel-hq" / "roster.json").read_text())
        assert saved["rooms"][0]["note"] == note
    else:
        assert 'rooms[0] (id "hq").note' in result["message"]
        assert not (tmp_path / "plugin-data").exists()


def test_unedited_editor_payload_saves_every_shipped_schema_field(tmp_path):
    output = run_roster(tmp_path, """
tab('roster');
const before=JSON.stringify(DATA);
const root=document.getElementById('roster-editor');
root.querySelector('[data-roster-save]').onclick();
assert.equal(JSON.stringify(DATA),before,'drafts must not mutate the snapshot');
const body=messages.find(message=>message.pixelhqRoster).pixelhqRoster;
assert.deepEqual(body.roster.rooms,DATA.cfg.rooms);
assert.ok(body.roster.rooms.some(room=>room.note));
console.log('PAYLOAD:'+JSON.stringify(body));
""", iframe=True)
    body = json.loads(next(line.removeprefix("PAYLOAD:") for line in output.splitlines() if line.startswith("PAYLOAD:")))
    expected = json.loads((ROOT / "pixelhq" / "roster.example.json").read_text())
    expected.pop("_doc")
    for bot in expected["bots"]:
        overrides = {"dev-b": "scribe", "trial-model": "rogue", "remote-ops": "medic"}
        if bot["id"] in overrides:
            bot["sprite"] = overrides[bot["id"]]
    assert body["roster"] == expected
    profiles = {bot["id"]: {} for bot in expected["bots"] if not bot.get("remote")}
    assert roster.save(body, {"hermes_home": str(tmp_path)}, profiles)["ok"]
    assert json.loads((tmp_path / "plugin-data" / "pixel-hq" / "roster.json").read_text()) == expected


# ---- D3: one roster location ------------------------------------------------------------------------------

def test_site_files_are_read_from_plugin_data_only(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "plugin-data" / "pixel-hq").mkdir(parents=True)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name in ("roster.json", "config.json"):
        (checkout / name).write_text('{"rooms": [], "bots": [], "theme_label": "CHECKOUT"}', encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(config, "_DIRS", None)
    monkeypatch.setattr(config, "HERE", checkout)
    assert config.site_file("roster.json") is None and config.site_file("config.json") is None
    assert config.load()["theme_label"] == "PIXEL HQ"
    assert config.load_roster()["rosterSource"] == "generated"


def test_reset_always_yields_the_generated_roster(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "plugin-data" / "pixel-hq").mkdir(parents=True)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "roster.json").write_text(json.dumps({"rooms": [{"id": "old", "label": "OLD", "main": True,
                                                                  "zones": []}], "bots": []}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(config, "_DIRS", None)
    monkeypatch.setattr(config, "HERE", checkout)
    saved = {"rooms": [{"id": "lab", "label": "LAB", "main": True, "zones": [{"id": "z", "label": "Z"}]}],
             "bots": [{"id": "ops-bot", "cls": "c", "title": "t", "zone": "z", "color": "#112233"}]}
    assert roster.save({"roster": saved}, {"hermes_home": str(home)}, {"ops-bot": {}})["ok"]
    assert config.load_roster()["rosterSource"] == "file"
    assert roster.save({"reset": True}, {"hermes_home": str(home)}, {})["ok"]
    after = config.load_roster()
    assert after["rosterSource"] == "generated" and [room["id"] for room in after["rooms"]] == ["hq"]


# ---- D4: ids -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("where", ["room", "zone", "bot-zone"])
@pytest.mark.parametrize("value,accepted", [("a-b", True), ("a_b", True), ("ab", True), ("a.b", False),
                                            (".", False), ("a" * 64, True), ("a" * 65, False)])
def test_room_and_zone_ids_have_no_dot(body, tmp_path, where, value, accepted):
    room = body["roster"]["rooms"][0]
    if where == "room":
        room["id"] = value
    elif where == "zone":
        old = room["zones"][0]["id"]
        room["zones"][0]["id"] = value
        for bot in body["roster"]["bots"]:
            bot["zone"] = value if bot["zone"] == old else bot["zone"]
    else:
        room["zones"].append({"id": value, "label": "extra"})
        body["roster"]["bots"][0]["zone"] = value
    result = roster.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})
    assert result["ok"] is accepted, result
    if not accepted:
        assert "ASCII letters, digits or _- only" in result["message"]


def test_bot_ids_keep_the_dot(body, tmp_path):
    body["roster"]["bots"][0]["id"] = "ops.bot-1"
    assert roster.save(body, {"hermes_home": str(tmp_path)}, {"ops.bot-1": {}})["ok"] is True


@pytest.mark.parametrize("first,second", [("a-b", "ab"), ("a.b", "ab")])
def test_leaderboard_and_office_use_raw_zone_ids(tmp_path, first, second):
    run_roster(tmp_path, """
DATA.cfg.rooms=[{id:'hq',label:'HQ',main:true,zones:[{id:FIRST,label:'First zone'},{id:SECOND,label:'Second zone'}]}];
DATA.bots=DATA.bots.slice(0,4);
DATA.bots.forEach((bot,i)=>{bot.zone=i<3?FIRST:SECOND});
tab('leaderboard');board();
const buttons=document.getElementById('bfilter').querySelectorAll('button');
assert.deepEqual(buttons.map(b=>b.dataset.z),['all',FIRST,SECOND]);
const rowsFor=id=>{buttons.find(b=>b.dataset.z===id).onclick();return document.getElementById('tb').querySelectorAll('tr').map(tr=>tr.dataset.id).sort()};
assert.deepEqual(rowsFor(FIRST),DATA.bots.slice(0,3).map(b=>b.id).sort());
assert.deepEqual(rowsFor(SECOND),[DATA.bots[3].id]);
assert.equal(bzone,SECOND,'filter state keeps the raw id');
office();
const desks=new Map(document.getElementById('floor').querySelectorAll('[data-zone]').map(el=>[el.dataset.zone,el.querySelectorAll('.desk').map(d=>d.dataset.id).sort()]));
assert.deepEqual([...desks.keys()],[FIRST,SECOND]);
assert.deepEqual(desks.get(FIRST),DATA.bots.slice(0,3).map(b=>b.id).sort());
assert.deepEqual(desks.get(SECOND),[DATA.bots[3].id]);
""".replace("FIRST", json.dumps(first)).replace("SECOND", json.dumps(second)), iframe=True)


@pytest.mark.parametrize("value,accepted", [("a.b", False), ("a-b", True)])
def test_editor_add_zone_applies_the_id_rule(tmp_path, value, accepted):
    run_roster(tmp_path, """
tab('roster');
const root=document.getElementById('roster-editor');
root.querySelector('[data-roster-new-zone]').value=VALUE;
root.querySelector('[data-roster-add-zone]').onclick();
const zones=rosterDraft.rooms.flatMap(room=>room.zones).map(zone=>zone.id);
assert.equal(zones.includes(VALUE),ACCEPTED);
assert.equal(!!rosterResult(),!ACCEPTED);
""".replace("VALUE", json.dumps(value)).replace("ACCEPTED", json.dumps(accepted)), iframe=True)


# ---- D5: one text rule -------------------------------------------------------------------------------------

TEXT_SAMPLES = [
    ("plain label", True), ("\U0001F468\u200d\U0001F469\u200d\U0001F467 family", True),
    ("a\u200cb\u200dc", True), ("\u0645\u0631\u062d\u0628\u0627", True), ("emoji \U0001F9D1\u200d\U0001F4BB", True),
    ("a\u202eb", False), ("a\u202ab", False), ("a\u202db", False), ("a\u2066b", False), ("a\u2069b", False),
    ("a\x00b", False), ("a\x1fb", False), ("a\x7fb", False), ("a\x85b", False), ("a\nb", False),
    ("a\u0378b", False), ("a\ue000b", False), ("a\ud800b", False), ("a\u2065b", False),
]


@pytest.mark.parametrize("text,accepted", TEXT_SAMPLES)
def test_server_text_rule(body, tmp_path, text, accepted):
    body["roster"]["rooms"][0]["label"] = text
    result = roster.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})
    assert result["ok"] is accepted, result
    if not accepted:
        assert "control or bidi-override characters" in result["message"]
        assert not (tmp_path / "plugin-data").exists()


def test_ui_pre_check_agrees_with_the_server_rule(tmp_path):
    texts = [text for text, _ in TEXT_SAMPLES]
    out = run_roster(tmp_path, """
const ok=rosterTextTest();
assert.ok(ok,'the host hands the rule over as cfg.textRule');
console.log('RESULT:'+JSON.stringify(TEXTS.map(text=>ok(text,40))));
console.log('LIMITS:'+JSON.stringify([ok('x'.repeat(40),40),ok('x'.repeat(41),40),ok('\\u{1F468}'.repeat(40),40),ok('\\u{1F468}'.repeat(41),40),ok(7,40)]));
""".replace("TEXTS", json.dumps(texts)), iframe=True)
    result = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
    limits = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("LIMITS:")))
    assert result == [not config.text_rejected(text) for text in texts] == [ok for _, ok in TEXT_SAMPLES]
    assert limits == [True, False, True, False, False]


def test_ui_save_refuses_rejected_text_before_the_host(tmp_path):
    run_roster(tmp_path, """
tab('roster');
rosterDraft.bots[0].cls='a\\u202eb';rosterChanged();renderRoster();
document.getElementById('roster-editor').querySelector('[data-roster-save]').onclick();
assert.equal(messages.filter(m=>m.pixelhqRoster).length,0,'nothing reaches the host');
assert.ok(rosterResult()&&!rosterResult().ok);
assert.ok(rosterResult().message.startsWith('bots[0] (id '+JSON.stringify(rosterDraft.bots[0].id)+').cls: '),rosterResult().message);
assert.ok(rosterResult().message.includes('control or bidi-override characters'));
rosterDraft.bots[0].cls='ok \\u{1F468}\\u200d\\u{1F469}';rosterChanged();renderRoster();
document.getElementById('roster-editor').querySelector('[data-roster-save]').onclick();
assert.equal(messages.filter(m=>m.pixelhqRoster).length,1,'an emoji sequence passes the pre-check');
""", iframe=True)


@pytest.mark.parametrize("description,expected", [
    ("Line one\nline two\twith  tabs", "Line one line two with tabs"),
    ("bidi \u202etrick\x00 here", "bidi trick here"),
    ("\n\x00 \t", "Hermes profile"),
])
def test_generated_recruit_role_is_always_a_saveable_label(fleet, description, expected):
    (fleet.root / "plugin-data" / "pixel-hq" / "roster.json").unlink()
    profile = fleet.root / "profiles" / "ops-bot" / "profile.yaml"
    profile.write_text("description: " + json.dumps(description) + "\n", encoding="utf-8")
    cfg = config.load()
    profiles = collect.read_profiles(cfg=cfg)
    bots = collect.roster_bots(profiles, cfg=cfg)
    role = next(bot["cls"] for bot in bots if bot["id"] == "ops-bot")
    assert role == expected
    generated = config.load_roster()
    assert roster.save({"roster": {"rooms": generated["rooms"], "bots": bots}}, cfg, profiles)["ok"]
