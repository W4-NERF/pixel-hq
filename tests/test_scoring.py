"""Scoring contracts from the Round 1 specification."""
import importlib
import math

import pytest

from pixelhq.config import DEFAULTS


def scoring():
    # Import inside the test so a missing implementation is a clear RED failure.
    return importlib.import_module("pixelhq.scoring")


def test_kanban_outcomes_feed_every_score_field(fleet):
    fleet.events("platform", "ops-bot", [
        "claimed", "completed", "completed", "completed", "changes_requested",
        "gave_up", "timed_out", "protocol_violation", "suspected_hallucinated_references",
    ])
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, [], DEFAULTS)["ops-bot"]
    assert score["own"] == [3, 1, 3]
    assert score["summ"] == [0, 0, 0]
    assert score["p"] == 3
    assert score["r"] == 1
    assert score["f"] == 3
    assert score["n"] == sum(score["own"])
    assert score["xp"] == score["xpOwn"] == 3 * 10 + 3 - 3 * 5
    assert score["xpSummon"] == 0
    assert score["xpBySource"] == {"kanban": score["xp"], "reviews": 0}
    assert score["bySource"] == {
        "kanban": {"pass": 3, "revise": 1, "fail": 3},
        "reviews": {"pass": 0, "revise": 0, "fail": 0},
    }
    assert score["selfReviews"] == 0
    assert index.by_bot["ops-bot"]["completed"] == 3
    assert index.by_bot["ops-bot"]["changes_requested"] == 1
    assert index.by_bot["ops-bot"]["gave_up"] == 1
    assert index.by_bot["ops-bot"]["timed_out"] == 1
    assert index.by_bot["ops-bot"]["protocol_violation"] == 1
    assert index.by_bot["ops-bot"]["mirage"] == 1
    assert index.by_bot["ops-bot"]["runs"] == 1
    assert score["hp"] == round(100 * 3 / 7)
    assert score["attrsSource"] == "kanban"


def test_board_event_ids_are_local_and_snapshots_are_idempotent(fleet):
    for board in fleet.boards:
        fleet.events(board, "ops-bot", ["claimed", "completed"])
    module = scoring()
    boards = list(fleet.boards.items())
    index = module.KanbanIndex.from_boards(boards + boards, DEFAULTS)
    first = module.compute(["ops-bot", "default"], index, [], DEFAULTS)
    assert first["ops-bot"]["own"] == [2, 0, 0]
    assert len(index.events) == 2
    assert len({(e["board"], e["id"]) for e in index.events}) == 2
    assert module.compute(["ops-bot", "default"], index, [], DEFAULTS) == first
    rebuilt = module.KanbanIndex.from_boards(boards, DEFAULTS)
    assert module.compute(["ops-bot", "default"], rebuilt, [], DEFAULTS) == first


def test_protocol_violations_are_not_xp_or_hp_events(fleet):
    fleet.events("platform", "ops-bot", ["claimed", "protocol_violation", "heartbeat", "blocked"])
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, [], DEFAULTS)["ops-bot"]
    assert score["xp"] == score["n"] == 0
    assert score["hp"] is None
    assert score["attrs"] == [None] * 4
    assert score["attrsSource"] is None


def test_kanban_attributes_match_formulas_and_clamp(fleet):
    fleet.events("platform", "ops-bot", ["completed"] * 3 + ["claimed"] * 2 + [
        "gave_up", "timed_out", "changes_requested", "protocol_violation",
        "suspected_hallucinated_references",
    ])
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, [], DEFAULTS)["ops-bot"]
    assert score["attrs"] == [round(5 - 4 / 3, 1), round(1 + 4 * 3 / 5, 1), 3.0, 4.0]
    fleet.events("platform", "ops-bot", ["protocol_violation"] * 10 + ["suspected_hallucinated_references"] * 10)
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    assert module.compute(["ops-bot"], index, [], DEFAULTS)["ops-bot"]["attrs"][::2] == [1.0, 1.0]


@pytest.mark.parametrize("completed", [0, 1, 2, 3])
def test_kanban_attribute_threshold_without_runs(fleet, completed):
    fleet.events("website", "ops-bot", ["completed"] * completed)
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, [], DEFAULTS)["ops-bot"]
    assert score["attrs"] == ([5.0] * 4 if completed >= 3 else [None] * 4)
    assert score["attrsSource"] == ("kanban" if completed >= 3 else None)


def test_kanban_opt_out_and_excluded_boards(fleet):
    for board in fleet.boards:
        fleet.events(board, "ops-bot", ["completed"] * 3)
    module = scoring()
    cfg = DEFAULTS | {"exclude_boards": ["website"]}
    index = module.KanbanIndex.from_boards(fleet.boards.items(), cfg)
    assert module.compute(["ops-bot"], index, [], cfg)["ops-bot"]["p"] == 3
    off = module.compute(["ops-bot"], index, [], cfg | {"kanban_xp": False})["ops-bot"]
    assert off["xp"] == off["n"] == 0
    assert off["hp"] is None
    assert off["attrsSource"] is None
    assert len(index.events) == 3
    assert {e["board"] for e in index.events} == {"platform"}


@pytest.mark.parametrize("xp", [0, 1, 24, 25, 26, 99, 100, 101, 224, 225, 10000])
def test_level_and_progress_formulas(xp):
    level = 1 + math.floor(math.sqrt(xp / 25))
    lo, hi = 25 * (level - 1) ** 2, 25 * level ** 2
    assert scoring().level_of(xp) == (level, round(100 * (xp - lo) / (hi - lo)))


def test_board_scan_is_read_only_and_once_per_board_not_bot(fleet, monkeypatch):
    import hashlib
    import sqlite3

    for board in fleet.boards:
        fleet.events(board, "ops-bot", ["completed"])
    before = {board: hashlib.sha256(db.read_bytes()).hexdigest() for board, db in fleet.boards.items()}
    queries = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        assert "mode=ro" in args[0]
        con = connect(*args, **kwargs)
        con.set_trace_callback(queries.append)
        return con

    monkeypatch.setattr(sqlite3, "connect", traced)
    module = scoring()
    index = module.KanbanIndex.from_boards(list(fleet.boards.items()) * 2, DEFAULTS)
    module.compute(["default", "ops-bot", "remote-bot"], index, [], DEFAULTS)
    module.compute(["default", "ops-bot", "remote-bot"], index, [], DEFAULTS)
    assert sum("FROM task_events" in q.replace('"', '') for q in queries) == len(fleet.boards)
    assert {board: hashlib.sha256(db.read_bytes()).hexdigest() for board, db in fleet.boards.items()} == before


def test_board_failures_are_short_warnings(tmp_path):
    index = scoring().KanbanIndex.from_boards([("missing", tmp_path / "missing.db")], DEFAULTS)
    assert len(index.warnings) == 1
    assert index.warnings[0].startswith("missing:")
    assert len(index.warnings[0]) <= 120
    assert not (tmp_path / "missing.db").exists()


def test_parse_reviews_supports_current_and_legacy_records(fleet):
    dims = {"correctness": 5, "completeness": 4, "format": 3, "safety": 2}
    current = fleet.reviews([
        {"agent": "ops-bot", "verdict": "pass", "dims": dims, "source": "ui", "ref": "Sample verification"},
        {"agent": "ops-bot", "verdict": "revise", "scores": dims, "source": "tool"},
    ])
    legacy = fleet.reviews([{"agent": "ops-bot", "verdict": "fail", **dims, "task": "Sample legacy task"}], legacy=True)
    records, warnings = scoring().parse_reviews([current, legacy, current, fleet.root / "absent.jsonl", ""])
    assert warnings == []
    assert len(records) == 3
    assert [r["dims"] for r in records] == [dims] * 3
    assert [r["source"] for r in records] == ["ui", "tool", "legacy"]
    assert records[-1]["ref"] == "Sample legacy task"


def test_parse_reviews_skips_bad_lines_with_bounded_warnings(fleet):
    path = fleet.reviews_path
    path.write_text('\n{broken}\n[]\n{"agent":"ops-bot","verdict":"unknown"}\n'
                    '{"verdict":"pass"}\n{"agent":"ops-bot","verdict":"pass"}\n', encoding="utf-8")
    records, warnings = scoring().parse_reviews([path])
    assert len(records) == 1
    assert records[0]["agent"] == "ops-bot"
    assert all(0 < len(warning) <= 120 for warning in warnings)
    assert len(warnings) == 3
    assert all("reviews.jsonl:" in warning for warning in warnings)


@pytest.mark.parametrize("agent,record,expected", [
    ("worker", {"parent": "ops-bot"}, ("ops-bot", True)),
    ("subagent-17", {}, ("captain-bot", True)),
    ("delegate_task/helper", {}, ("captain-bot", True)),
    ("claude-code-cli", {}, ("captain-bot", True)),
    ("OPENCODE-helper", {}, ("captain-bot", True)),
    ("codex", {}, ("captain-bot", True)),
    ("cron:sample-report", {}, ("captain-bot", True)),
    ("captain-bot-subagent42", {}, ("captain-bot", True)),
    ("ops-bot+remote-bot", {}, ("ops-bot", False)),
    ("captain-bot", {}, ("captain-bot", False)),
    ("captain-bot-extra", {}, ("captain-bot-extra", False)),
    ("", {}, (None, False)),
    ("?", {}, (None, False)),
])
def test_review_attribution_is_config_driven(agent, record, expected):
    cfg = DEFAULTS | {"orchestrator_profile": "captain-bot"}
    assert scoring().attribute(agent, record, cfg) == expected


def test_reviews_add_to_kanban_and_self_reviews_are_excluded(fleet):
    fleet.events("platform", "ops-bot", ["claimed"] * 3 + ["completed"] * 3)
    reviews = [
        {"agent": "ops-bot", "verdict": "pass", "reviewer": "operator", "source": "ui",
         "dims": dict(zip(("correctness", "completeness", "format", "safety"), (4, 3, 2, 1), strict=True))},
        {"agent": "subagent", "parent": "ops-bot", "verdict": "revise", "reviewer": "operator", "source": "tool",
         "dims": dict(zip(("correctness", "completeness", "format", "safety"), (2, 5, 4, 3), strict=True))},
        {"agent": "ops-bot", "verdict": "fail", "reviewer": "ops-bot",
         "dims": dict.fromkeys(("correctness", "completeness", "format", "safety"), 1)},
        {"agent": "unlisted-bot", "verdict": "pass"},
    ]
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    first = module.compute(["ops-bot", "default"], index, reviews, DEFAULTS)
    score = first["ops-bot"]
    assert score["own"] == [4, 0, 0]
    assert score["summ"] == [0, 1, 0]
    assert [score[k] for k in ("p", "r", "f", "n")] == [4, 1, 0, 5]
    assert score["hp"] == round(100 * 4 / 5)
    assert score["xpOwn"] == 4 * 10
    assert score["xpSummon"] == 3
    assert score["xp"] == score["xpOwn"] + score["xpSummon"]
    assert score["xpBySource"] == {"kanban": 3 * 10, "reviews": 10 + 3}
    assert score["bySource"]["reviews"] == {"pass": 1, "revise": 1, "fail": 0}
    assert score["selfReviews"] == 1
    assert score["attrs"] == [3.0, 4.0, 3.0, 2.0]
    assert score["attrsSource"] == "reviews"
    assert first["default"]["xp"] == 0
    assert first == module.compute(["ops-bot", "default"], index, reviews, DEFAULTS)


@pytest.mark.parametrize("verdict", ["pass", "revise", "fail"])
def test_self_review_alone_cannot_supply_hp_or_attributes(verdict):
    module = scoring()
    record = {"agent": "codex", "verdict": verdict, "reviewer": "codex",
              "dims": dict.fromkeys(module.DIMENSIONS, 5)}
    score = module.compute(["default"], module.KanbanIndex(), [record], DEFAULTS)["default"]
    assert score["selfReviews"] == 1
    assert score["own"] == score["summ"] == [0, 0, 0]
    assert score["xp"] == score["n"] == 0
    assert score["hp"] is None
    assert score["attrs"] == [None] * 4
    assert score["attrsSource"] is None


@pytest.mark.parametrize("record, summon, self_review", [
    ({"agent": "helper", "parent": "ops-bot", "reviewer": "ops-bot"}, True, False),
    ({"agent": "subagent-1", "reviewer": "ops-bot"}, True, False),
    ({"agent": "ops-bot-subagent1", "reviewer": "ops-bot"}, True, False),
    ({"agent": "ops-bot+context", "reviewer": "ops-bot"}, False, False),
    ({"agent": "helper", "parent": "ops-bot", "reviewer": "helper"}, True, True),
    ({"agent": "ops-bot+context", "reviewer": "ops-bot+context"}, False, True),
    ({"agent": "ops-bot", "reviewer": "ops-bot"}, False, True),
])
def test_self_review_compares_rated_agent_before_attribution(record, summon, self_review):
    module = scoring()
    cfg = DEFAULTS | {"orchestrator_profile": "ops-bot"}
    record = {**record, "verdict": "pass", "dims": dict.fromkeys(module.DIMENSIONS, 5)}
    score = module.compute(["ops-bot"], module.KanbanIndex(), [record], cfg)["ops-bot"]
    assert score["selfReviews"] == int(self_review)
    assert score["xp"] == (0 if self_review else 10)
    assert score["xpSummon"] == (10 if summon and not self_review else 0)
    assert score["hp"] == (None if self_review else 100)
    assert score["attrs"] == ([None] * 4 if self_review else [5.0] * 4)
    event, = module.review_events([record], cfg)
    assert event["bot"] == "ops-bot" and event["summon"] is summon
    assert event["selfReview"] is self_review


def test_reviewless_dimensions_fall_back_to_kanban(fleet):
    fleet.events("platform", "ops-bot", ["completed"] * 3)
    module = scoring()
    record = {"agent": "ops-bot", "verdict": "fail"}
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, [record], DEFAULTS)["ops-bot"]
    assert score["attrsSource"] == "kanban"
    assert score["attrs"] == [5.0] * 4
    assert score["hp"] == round(100 * 3 / 4)


def test_review_only_scoring_and_own_summon_zero_floors():
    module = scoring()
    records = ([{"agent": "ops-bot", "verdict": "fail"}] * 3 +
               [{"agent": "worker", "parent": "ops-bot", "verdict": "pass"}])
    cfg = DEFAULTS | {"xp_pass": 20, "xp_revise": 7, "xp_fail": -9, "kanban_xp": False}
    score = module.compute(["ops-bot"], module.KanbanIndex(), records, cfg)["ops-bot"]
    assert score["xpOwn"] == 0
    assert score["xpSummon"] == score["xp"] == 20
    assert score["xpBySource"] == {"kanban": 0, "reviews": 3 * -9 + 20}
    assert score["hp"] == round(100 / 4)
    assert (score["lvl"], score["xpPct"]) == module.level_of(20)


@pytest.mark.parametrize("kind,verdict,count,summon,expected_own,expected_summon,raw_kanban,raw_reviews", [
    ("gave_up", "pass", 1, False, 5, 0, -5, 10),
    ("completed", "fail", 1, False, 5, 0, 10, -5),
    ("completed", "fail", 3, False, 0, 0, 10, -15),
    ("gave_up", "pass", 1, True, 0, 10, -5, 10),
])
def test_mixed_sign_sources_report_raw_xp_with_separate_bucket_floors(
    fleet, kind, verdict, count, summon, expected_own, expected_summon, raw_kanban, raw_reviews,
):
    fleet.events("platform", "ops-bot", [kind])
    record = {"agent": "worker", "parent": "ops-bot"} if summon else {"agent": "ops-bot"}
    records = [{**record, "verdict": verdict} for _ in range(count)]
    module = scoring()
    index = module.KanbanIndex.from_boards(fleet.boards.items(), DEFAULTS)
    score = module.compute(["ops-bot"], index, records, DEFAULTS)["ops-bot"]
    assert score["xpOwn"] == expected_own
    assert score["xpSummon"] == expected_summon
    assert score["xp"] == expected_own + expected_summon
    assert score["xpBySource"] == {"kanban": raw_kanban, "reviews": raw_reviews}


def test_review_events_keep_flags_clip_text_and_sort():
    module = scoring()
    reviews = [
        {"agent": "ops-bot", "verdict": "pass", "ts": "2026-01-02T00:00:00Z", "source": "ui", "ref": "x" * 500},
        {"agent": "worker", "parent": "ops-bot", "verdict": "revise", "ts": "2026-01-03T00:00:00+00:00", "source": "tool"},
        {"agent": "ops-bot", "reviewer": "ops-bot", "verdict": "fail", "ts": "bad", "source": "agent"},
        {"agent": "?", "verdict": "pass"},
        {"agent": "ops-bot", "verdict": "unknown"},
    ]
    events = module.review_events(reviews, DEFAULTS)
    assert [e["kind"] for e in events] == ["qc-revise", "qc-pass", "qc-fail"]
    assert [e["source"] for e in events] == ["tool", "ui", "agent"]
    assert [e["summon"] for e in events] == [True, False, False]
    assert [e["selfReview"] for e in events] == [False, False, True]
    assert events[-1]["ts"] == 0
    assert len(events[1]["text"]) <= 90
    assert {e["bot"] for e in events} == {"ops-bot"}


@pytest.mark.parametrize("bad", [0, 6, True, "bad", None, float("nan"), float("inf")])
def test_invalid_dimensions_do_not_become_attribute_input(fleet, bad):
    path = fleet.reviews([{"agent": "ops-bot", "verdict": "pass",
                           "dims": dict.fromkeys(("correctness", "completeness", "format", "safety"), bad)}])
    module = scoring()
    records, _ = module.parse_reviews([path])
    score = module.compute(["ops-bot"], module.KanbanIndex(), records, DEFAULTS)["ops-bot"]
    assert score["xp"] == 10
    assert score["attrs"] == [None] * 4
    assert score["attrsSource"] is None


def test_malformed_encoding_does_not_hide_later_reviews(fleet):
    fleet.reviews_path.write_bytes(b'\xff\n{"agent":"ops-bot","verdict":"pass"}\n')
    records, warnings = scoring().parse_reviews([fleet.reviews_path])
    assert len(records) == 1
    assert len(warnings) == 1
    assert all(len(warning) <= 120 for warning in warnings)


def test_unparseable_deep_json_does_not_abort_review_loading(fleet):
    fleet.reviews_path.write_text('[' * 10000 + '\n{"agent":"ops-bot","verdict":"pass"}\n', encoding="utf-8")
    records, warnings = scoring().parse_reviews([fleet.reviews_path])
    assert len(records) == 1
    assert len(warnings) == 1
