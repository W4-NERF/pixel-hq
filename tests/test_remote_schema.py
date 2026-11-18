"""R5-01: the shared ``pixelhq-remote/1`` validator (also used by the collector of R5-02) on hostile input."""
import calendar
import copy
import json

import pytest

from pixelhq import remote_schema as rs


def bot(**over):
    return {"id": "ops-bot", "model": "sample/model", "status": "idle", "lastActive": 1700000000, "xp": 10, "level": 1,
            "hp": None, **over}


def card(**over):
    return {"board": "platform", "id": "t_00aa11bb", "title": "Sample", "category": "you", "assignee": "ops-bot",
            "ageDays": 2, "reason": "waiting", **over}


def board(**over):
    return {"slug": "platform", "ready": 1, "running": 2, "blocked": 3, "todo": 4, "done24h": 5, **over}


def document(**over):
    return {"schema": "pixelhq-remote/1", "source": "atlas", "generated": "2026-11-17T10:00:00Z", "pixelhq": "1.4.0",
            "bots": [bot()], "blockers": [card()], "boards": [board()], "warnings": ["a warning"], **over}


def refused(doc, fragment=""):
    with pytest.raises(rs.SchemaError) as caught:
        rs.validate(doc)
    assert fragment in str(caught.value) and len(str(caught.value)) <= 80
    return str(caught.value)


def test_valid_document_is_returned_unchanged_and_the_copy_is_independent():
    doc = document()
    out = rs.validate(doc)
    assert out == doc and out is not doc and out["bots"][0] is not doc["bots"][0]
    assert rs.validate(out) == out  # cleaning is idempotent
    assert json.loads(json.dumps(out)) == out


def test_unknown_fields_are_dropped_at_every_level():
    doc = document()
    doc["extra"] = 1
    doc["bots"][0]["cmd"] = "x"
    doc["blockers"][0]["body"] = "x"
    doc["boards"][0]["note"] = "x"
    assert rs.validate(doc) == document()


def test_optional_fields_may_be_absent_or_null_but_required_ones_may_not():
    out = rs.validate(document(bots=[bot(currentStep="step", quest="q", lastTool="t", cls="Role"), bot(id="b", quest=None)]))
    assert out["bots"][0]["currentStep"] == "step" and "quest" not in out["bots"][1]
    for key in ("id", "model", "status", "xp", "level"):
        broken = bot()
        del broken[key]
        refused(document(bots=[broken]), f"bots[0].{key}: missing")
    broken = bot()
    del broken["hp"]
    refused(document(bots=[broken]), "hp: missing")
    assert rs.validate(document(bots=[bot(hp=0, lastActive=None)]))["bots"][0]["hp"] == 0


def test_last_active_never_lies_after_the_document_was_generated():
    generated = calendar.timegm((2026, 11, 17, 10, 0, 0))  # the stamp of `document()`: 2026-11-17T10:00:00Z
    assert document()["generated"] == "2026-11-17T10:00:00Z"
    bots = [bot(id="late", lastActive=generated + 500), bot(id="exact", lastActive=generated),
            bot(id="early", lastActive=generated - 500), bot(id="none", lastActive=None), bot(id="zero", lastActive=0)]
    out = {b["id"]: b["lastActive"] for b in rs.validate(document(bots=bots))["bots"]}
    assert out == {"late": generated, "exact": generated, "early": generated - 500, "none": None, "zero": 0}


@pytest.mark.parametrize("stamp", ["1969-12-31T23:59:59Z", "1900-01-01T00:00:00Z", "0001-01-01T00:00:00Z",
                                   "\u0661\u0669\u0666\u0669-12-31T23:59:59Z"])
def test_generated_before_1970_is_refused(stamp):
    """R5-D11: a pre-epoch `generated` would let the `lastActive` clamp produce a negative, schema-invalid value."""
    refused(document(generated=stamp, bots=[bot(lastActive=0)]), "generated: before 1970")


def test_generated_at_the_epoch_is_valid_and_the_clamp_stays_in_range():
    out = rs.validate(document(generated="1970-01-01T00:00:00Z", bots=[bot(lastActive=500)]))
    assert out["generated"] == "1970-01-01T00:00:00Z" and out["bots"][0]["lastActive"] == 0
    assert rs.validate(out) == out


def test_validation_is_idempotent_on_a_normal_document():
    once = rs.validate(document())
    assert once == document() and rs.validate(once) == once


@pytest.mark.parametrize("doc, fragment", [
    ([], "expected an object"), (None, "expected an object"),
    (document(schema="pixelhq-remote/2"), "schema"), (document(schema=None), "schema"),
    (document(source="Atlas"), "source"), (document(source="-a"), "source"), (document(source="a" * 33), "source"),
    (document(source=5), "source"), (document(generated="yesterday"), "generated"),
    (document(generated="2026-11-17T10:00:00+01:00"), "generated"), (document(pixelhq=1), "pixelhq"),
    (document(bots={}), "bots: expected a list"), (document(blockers=None), "blockers"), (document(boards="x"), "boards"),
    (document(warnings="x"), "warnings"), (document(warnings=[1]), "warnings"),
    (document(bots=["x"]), "expected an object"),
])
def test_top_level_shape_errors_are_refused(doc, fragment):
    refused(doc, fragment)


@pytest.mark.parametrize("entry, section, fragment", [
    (bot(id="bad id"), "bots", "bots[0].id"), (bot(id=""), "bots", "bots[0].id"), (bot(id="a" * 65), "bots", "id"),
    (bot(status="offline"), "bots", "status"), (bot(status=1), "bots", "status"), (bot(model=3), "bots", "model"),
    (bot(xp=-1), "bots", "xp"), (bot(xp=1.5), "bots", "xp"), (bot(xp=True), "bots", "xp"), (bot(xp="9"), "bots", "xp"),
    (bot(xp=float("nan")), "bots", "xp"), (bot(level=0), "bots", "level"), (bot(hp=101), "bots", "hp"),
    (bot(hp=-1), "bots", "hp"), (bot(lastActive="now"), "bots", "lastActive"), (bot(lastActive=-5), "bots", "lastActive"),
    (bot(currentStep=7), "bots", "currentStep"), (bot(cls=["x"]), "bots", "cls"),
    (card(id="t_sample"), "blockers", "id"), (card(id="x_00aa11bb"), "blockers", "id"), (card(id="t_00AA11BB"), "blockers", "id"),
    (card(board="Platform"), "blockers", "board"), (card(board="../x"), "blockers", "board"),
    (card(category="other"), "blockers", "category"), (card(ageDays=-1), "blockers", "ageDays"),
    (card(title=None), "blockers", "title"), (card(reason=5), "blockers", "reason"), (card(assignee=None), "blockers", "assignee"),
    (board(slug="A b"), "boards", "slug"), (board(ready=-1), "boards", "ready"), (board(done24h="3"), "boards", "done24h"),
    (board(todo=None), "boards", "todo"),
])
def test_field_type_enum_and_pattern_errors_are_refused(entry, section, fragment):
    doc = document(bots=[], blockers=[], boards=[])
    doc[section] = [entry]
    refused(doc, fragment)


def test_text_is_clipped_not_refused_and_cleaned():
    out = rs.validate(document(
        bots=[bot(model="m" * 200, currentStep="s" * 300, quest="q" * 300, lastTool="t" * 300, cls="c" * 300)],
        blockers=[card(title="t" * 300, reason="r" * 300, assignee="a" * 300)], warnings=["w" * 300],
        pixelhq="v" * 90))
    assert [len(out["bots"][0][key]) for key in ("model", "currentStep", "quest", "lastTool", "cls")] == [80, 160, 80, 160, 40]
    assert [len(out["blockers"][0][key]) for key in ("title", "reason", "assignee")] == [120, 160, 64]
    assert len(out["warnings"][0]) == 160 and len(out["pixelhq"]) == 32
    hostile = "a\u202eb\x00c\x1b[31md\ne\tf\u200bg"
    cleaned = rs.validate(document(bots=[bot(quest=hostile)]))["bots"][0]["quest"]
    assert cleaned == "abc[31md e f\u200bg"  # control and bidi-override characters go, zero-width joiners stay allowed


def test_list_limits_are_enforced():
    refused(document(bots=[bot(id=f"b{number}") for number in range(201)]), "more than 200")
    refused(document(blockers=[card() for _ in range(501)]), "more than 500")
    refused(document(boards=[board(slug=f"b{number}") for number in range(65)]), "more than 64")
    refused(document(warnings=["w"] * 21), "more than 20")
    assert len(rs.validate(document(bots=[bot(id=f"b{number}") for number in range(200)]))["bots"]) == 200
    assert len(rs.validate(document(blockers=[card() for _ in range(500)]))["blockers"]) == 500
    assert len(rs.validate(document(boards=[board(slug=f"b{number}") for number in range(64)]))["boards"]) == 64
    assert len(rs.validate(document(warnings=["w"] * 20))["warnings"]) == 20


def test_duplicate_bot_ids_and_board_slugs_are_refused():
    refused(document(bots=[bot(), bot()]), "duplicate id")
    refused(document(boards=[board(), board()]), "duplicate slug")
    assert len(rs.validate(document(blockers=[card(), card()]))["blockers"]) == 2  # the same card on two boards is not our concern


def test_error_message_is_at_most_80_characters_even_for_long_names():
    doc = document()
    doc["bots"][0]["id"] = "x" * 500 + " bad"
    message = refused(doc, "bots[0].id")
    assert len(message) <= 80
    assert "x" * 100 not in message


def test_the_validator_does_not_modify_its_input():
    doc = document(bots=[bot(quest="a\x00b" + "q" * 300)])
    snapshot = copy.deepcopy(doc)
    rs.validate(doc)
    assert doc == snapshot


def test_limits_are_the_ones_of_the_spec():
    assert rs.SCHEMA == "pixelhq-remote/1" and rs.MAX_BYTES == 1024 * 1024
    assert rs.MAX_LIST == {"bots": 200, "blockers": 500, "boards": 64}
    assert (rs.MAX_WARNINGS, rs.MAX_WARNING) == (20, 160)
    assert rs.STATUSES == ("running", "idle", "blocked", "unknown")
