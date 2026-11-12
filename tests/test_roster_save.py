"""Roster writes use invented fixtures and a fixed plugin-data target."""
import copy
import importlib.util
import json

import pytest


@pytest.fixture
def writer():
    spec = importlib.util.find_spec("pixelhq.roster")
    assert spec is not None, "The roster save backend is missing"
    return __import__("pixelhq.roster", fromlist=["save"])


@pytest.fixture
def body():
    return {"roster": {
        "rooms": [{"id": "hq", "label": "Headquarters", "main": True,
                   "zones": [{"id": "crew", "label": "Crew"}]}],
        "bots": [{"id": "ops-bot", "cls": "Engineer", "title": "Recruit", "zone": "crew",
                  "loc": "Workshop", "color": "#93a1AF", "leader": True, "sprite": "engineer"}],
    }}


def target(root):
    return root / "plugin-data" / "pixel-hq" / "roster.json"


def test_save_creates_fixed_roster_and_drops_unknown_keys(writer, body, tmp_path):
    original = copy.deepcopy(body)
    body.update(path=str(tmp_path / "other.json"), hermes_home=str(tmp_path / "other"))
    body["roster"]["extra"] = "ignored"
    body["roster"]["rooms"][0]["extra"] = "ignored"
    body["roster"]["rooms"][0]["zones"][0]["extra"] = "ignored"
    body["roster"]["bots"][0]["extra"] = "ignored"
    before = copy.deepcopy(body)
    result = writer.save(body, {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})
    assert result == {"ok": True, "message": "Roster saved."}
    path = target(tmp_path / "home")
    assert json.loads(path.read_text(encoding="utf-8")) == original["roster"]
    assert not (tmp_path / "other.json").exists()
    assert not (tmp_path / "other").exists()
    assert body == before
    assert list(path.parent.iterdir()) == [path]


def test_minimal_empty_roster_has_no_implicit_lower_limits(writer, tmp_path):
    roster = {"rooms": [{"id": "r", "label": "", "main": True, "zones": []}], "bots": []}
    assert writer.save({"roster": roster}, {"hermes_home": str(tmp_path)}, {})["ok"]
    assert json.loads(target(tmp_path).read_bytes()) == roster


MISSING = object()
VALIDATION_CASES = [
    ("body-object", (), [], "body"),
    ("roster-required", ("roster",), MISSING, "roster"),
    ("roster-object", ("roster",), [], "roster"),
    ("rooms-list", ("roster", "rooms"), {}, "rooms"),
    ("bots-list", ("roster", "bots"), {}, "bots"),
    ("room-object", ("roster", "rooms", 0), [], "rooms[0]"),
    ("zones-list", ("roster", "rooms", 0, "zones"), {}, "zones"),
    ("zone-object", ("roster", "rooms", 0, "zones", 0), [], "zones[0]"),
    ("bot-object", ("roster", "bots", 0), [], "bots[0]"),
    ("main-required", ("roster", "rooms", 0, "main"), MISSING, "main"),
    ("main-boolean", ("roster", "rooms", 0, "main"), 1, "main"),
    ("main-false", ("roster", "rooms", 0, "main"), False, "main"),
    ("bot-zone-exists", ("roster", "bots", 0, "zone"), "missing", "zone"),
    ("profile-exists", ("roster", "bots", 0, "id"), "unknown", "profile"),
    ("color-required", ("roster", "bots", 0, "color"), MISSING, "color"),
    ("color-type", ("roster", "bots", 0, "color"), 7, "color"),
    ("color-pattern", ("roster", "bots", 0, "color"), "#abcdeg", "color"),
    ("color-short", ("roster", "bots", 0, "color"), "#123", "color"),
    ("color-long", ("roster", "bots", 0, "color"), "#1234567", "color"),
    ("color-newline", ("roster", "bots", 0, "color"), "#123456\n", "color"),
    ("sprite-enum", ("roster", "bots", 0, "sprite"), "auto", "sprite"),
    ("sprite-type", ("roster", "bots", 0, "sprite"), [], "sprite"),
    ("remote-boolean", ("roster", "bots", 0, "remote"), "true", "remote"),
    ("leader-boolean", ("roster", "bots", 0, "leader"), 1, "leader"),
    ("quarantine-boolean", ("roster", "rooms", 0, "zones", 0, "quarantine"), 1, "quarantine"),
    ("reset-boolean", ("reset",), "true", "reset"),
    ("reset-exclusive", ("reset",), True, "reset"),
]
for prefix, path in (
    ("room", ("roster", "rooms", 0, "id")),
    ("zone", ("roster", "rooms", 0, "zones", 0, "id")),
    ("bot", ("roster", "bots", 0, "id")),
    ("bot-zone", ("roster", "bots", 0, "zone")),
):
    for suffix, value in (("missing", MISSING), ("type", 1), ("empty", ""), ("65", "x" * 65),
                          ("slash", "../x"), ("plus", "a+b"), ("newline", "id\n")):
        VALIDATION_CASES.append((prefix + "-id-" + suffix, path, value, path[-1]))
for prefix, path in (
    ("room-label", ("roster", "rooms", 0, "label")),
    ("zone-label", ("roster", "rooms", 0, "zones", 0, "label")),
    *[(key, ("roster", "bots", 0, key)) for key in ("cls", "title", "loc")],
):
    for suffix, value in (("type", 3), ("41", "x" * 41), ("control", "bad\x00value"),
                          ("newline", "bad\nvalue"), ("c1-control", "bad\x85value")):
        VALIDATION_CASES.append((prefix + "-" + suffix, path, value, path[-1]))
    if prefix != "loc":
        VALIDATION_CASES.append((prefix + "-required", path, MISSING, path[-1]))


def mutate(body, path, value):
    if not path:
        return value
    parent = body
    for key in path[:-1]:
        parent = parent[key]
    if value is MISSING:
        parent.pop(path[-1], None)
    else:
        parent[path[-1]] = copy.deepcopy(value)
    return body


@pytest.mark.parametrize("name,path,value,problem", VALIDATION_CASES, ids=[case[0] for case in VALIDATION_CASES])
def test_validation_matrix(writer, body, tmp_path, name, path, value, problem):
    body = mutate(body, path, value)
    for existing in (True, False):
        root = tmp_path / str(existing)
        roster = target(root)
        if existing:
            roster.parent.mkdir(parents=True)
            roster.write_bytes(b"old roster")
            roster.with_suffix(".json.bak").write_bytes(b"old backup")
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        result = writer.save(body, {"hermes_home": str(root)}, {"ops-bot": {}})
        assert result["ok"] is False, name
        assert problem in result["message"], result
        assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        if not existing:
            assert not root.exists(), "Validation must precede even directory creation"


COUNT_CASES = [("bots", "200"), ("rooms", "8"), ("zones", "24"), ("zones-multi-room", "24"),
               ("mains", "main"), ("leaders", "leader"), ("bot-duplicate", "id"),
               ("room-duplicate", "id"), ("zone-duplicate", "id")]


@pytest.mark.parametrize("kind,problem", COUNT_CASES)
def test_count_and_uniqueness_matrix(writer, body, tmp_path, kind, problem):
    roster = body["roster"]
    if kind == "bots":
        roster["bots"] = [dict(roster["bots"][0], id=f"remote-{i}", remote=True, leader=False) for i in range(201)]
    elif kind == "rooms":
        roster["rooms"] = [dict(roster["rooms"][0], id=f"room-{i}", main=i == 0, zones=[]) for i in range(9)]
    elif kind == "zones":
        roster["rooms"][0]["zones"] = [{"id": f"zone-{i}", "label": "Zone"} for i in range(25)]
    elif kind == "zones-multi-room":
        roster["rooms"] = [{"id": f"room-{i}", "label": "Room", "main": i == 0,
                            "zones": [{"id": f"z-{i}-{j}", "label": "Zone"} for j in range(13 - i)]}
                           for i in range(2)]
    elif kind == "mains":
        roster["rooms"].append({"id": "annex", "label": "Annex", "main": True, "zones": []})
    elif kind in ("leaders", "bot-duplicate"):
        roster["bots"].append(dict(roster["bots"][0], **({"id": "helper", "remote": True} if kind == "leaders" else {})))
    elif kind == "room-duplicate":
        roster["rooms"].append(dict(roster["rooms"][0], main=False, zones=[]))
    else:
        roster["rooms"].append({"id": "annex", "label": "Annex", "zones": [dict(roster["rooms"][0]["zones"][0])]})
    result = writer.save(body, {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})
    assert result["ok"] is False and problem in result["message"], result
    assert not (tmp_path / "home").exists()


def test_first_violation_is_deterministic_and_does_not_echo_values(writer, body, tmp_path):
    body["roster"]["rooms"][0]["label"] = "private\nvalue"
    body["roster"]["bots"][0]["color"] = "also invalid"
    result = writer.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})
    assert not result["ok"] and 'rooms[0] (id "hq").label' in result["message"]
    assert "color" not in result["message"] and "private" not in result["message"]
