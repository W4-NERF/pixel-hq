"""Round-3 limits: at most 8 rooms, 24 zones in total and 200 bots; each boundary is tested on both sides."""
import json

import pytest

from pixelhq import roster

BOT = {"id": "ops-bot", "cls": "Engineer", "title": "Recruit", "zone": "z-0-0", "color": "#93a1AF", "leader": True}


def build(rooms: int, zones_per_room, bots: int = 1) -> dict:
    """`zones_per_room` is an int or a list with one count per room; ids are invented and unique."""
    counts = zones_per_room if isinstance(zones_per_room, list) else [zones_per_room] * rooms
    layout = [{"id": f"room-{i}", "label": f"Room {i}", "main": i == 0,
               "zones": [{"id": f"z-{i}-{j}", "label": f"Dept {i}.{j}"} for j in range(counts[i])]}
              for i in range(rooms)]
    first = next((zone["id"] for room in layout for zone in room["zones"]), "z-0-0")
    crew = [dict(BOT, zone=first)] + [dict(BOT, id=f"remote-{i}", zone=first, remote=True, leader=False)
                                       for i in range(bots - 1)]
    return {"roster": {"rooms": layout, "bots": crew[:bots] if bots else []}}


def save(body: dict, tmp_path):
    return roster.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})


def test_limit_constants_match_the_round_3_spec():
    assert (roster.MAX_ROOMS, roster.MAX_ZONES, roster.MAX_BOTS) == (8, 24, 200)


def test_a_bot_in_a_missing_department_is_reported_with_the_word_department(tmp_path):
    body = build(1, 1)
    body["roster"]["bots"][0]["zone"] = "gone"
    result = save(body, tmp_path)
    assert result == {"ok": False, "message": "bots[0] (id \"ops-bot\").zone: department does not exist."}


@pytest.mark.parametrize("count,accepted", [(7, True), (8, True), (9, False)])
def test_room_count_boundary(tmp_path, count, accepted):
    body = build(count, [3] + [0] * (count - 1))
    result = save(body, tmp_path)
    assert result["ok"] is accepted, result
    if not accepted:
        assert result["message"] == "rooms: at most 8 rooms."
        assert not (tmp_path / "plugin-data").exists()


@pytest.mark.parametrize("count,accepted", [(23, True), (24, True), (25, False)])
def test_zone_count_boundary_in_one_room(tmp_path, count, accepted):
    result = save(build(1, count), tmp_path)
    assert result["ok"] is accepted, result
    if not accepted:
        assert "at most 24 departments in total" in result["message"]
        assert "zone" not in result["message"].split(": ", 1)[1].lower(), "the field path keeps the JSON key, the text says department"


@pytest.mark.parametrize("per_room,accepted", [(3, True), (4, False)])
def test_zone_count_boundary_is_a_total_over_all_rooms(tmp_path, per_room, accepted):
    # 8 rooms x 3 = 24 is accepted; 8 rooms x 3 plus one more department is not.
    counts = [per_room] + [3] * 7
    result = save(build(8, counts), tmp_path)
    assert result["ok"] is accepted, result


@pytest.mark.parametrize("count,accepted", [(199, True), (200, True), (201, False)])
def test_bot_count_boundary_is_unchanged(tmp_path, count, accepted):
    result = save(build(1, 1, count), tmp_path)
    assert result["ok"] is accepted, result


def test_maximum_roster_round_trips_through_the_file(tmp_path):
    body = build(8, 3, 200)
    assert save(body, tmp_path)["ok"]
    path = tmp_path / "plugin-data" / "pixel-hq" / "roster.json"
    assert json.loads(path.read_bytes()) == body["roster"]
