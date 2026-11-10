"""Real SQLite/JSONL integration of the collector's scoring path."""
import datetime as dt
import json
import time


def collector(fleet, monkeypatch, **settings):
    from pixelhq import collect, config

    data = fleet.root / "plugin-data" / "pixel-hq"
    (data / "config.json").write_text(json.dumps({"hermes_home": str(fleet.root), **settings}), encoding="utf-8")
    monkeypatch.setattr(config, "site_file", lambda name: data / name if (data / name).exists() else None)
    monkeypatch.setattr(collect, "cfgmod", config)
    return collect


def test_kanban_only_collect_scores_local_and_remote_bots(fleet, monkeypatch):
    fleet.events("platform", "ops-bot", ["claimed", "completed", "completed", "completed", "changes_requested"])
    fleet.events("website", "remote-bot", ["completed"])
    module = collector(fleet, monkeypatch)
    snapshot = module.collect()
    bots = {bot["id"]: bot for bot in snapshot["bots"]}
    assert bots["ops-bot"]["xp"] == 3 * 10 + 3
    assert bots["ops-bot"]["xpBySource"] == {"kanban": 3 * 10 + 3, "reviews": 0}
    assert bots["ops-bot"]["attrsSource"] == "kanban"
    assert bots["remote-bot"]["xp"] == 10
    assert bots["default"]["hp"] is None
    assert "changes_requested" in {event["kind"] for event in snapshot["events"]}
    assert isinstance(snapshot["warnings"], list)
    assert {bot["id"]: bot["xp"] for bot in module.collect()["bots"]} == {
        bot["id"]: bot["xp"] for bot in snapshot["bots"]}


def test_collect_uses_configured_review_paths_and_returns_warnings(fleet, monkeypatch):
    current = fleet.reviews([{"agent": "ops-bot", "verdict": "pass", "source": "ui"}])
    legacy = fleet.reviews([{"agent": "worker", "parent": "ops-bot", "verdict": "revise"}], legacy=True)
    with current.open("a", encoding="utf-8") as stream:
        stream.write("{invalid}\n")
    module = collector(fleet, monkeypatch, reviews_path=str(current), legacy_ledger_path=str(legacy))
    snapshot = module.collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["xp"] == 10 + 3
    assert bot["xpBySource"] == {"kanban": 0, "reviews": 10 + 3}
    assert bot["summons"] == 1
    assert bot["attrs"] == [None] * 4
    assert any("reviews.jsonl:2:" in warning for warning in snapshot["warnings"])
    assert {e["source"] for e in snapshot["events"] if e["kind"].startswith("qc-")} == {"ui", "legacy"}


def test_collect_merges_newest_40_across_sources_without_review_prelimit(fleet, monkeypatch):
    base = time.time() - 1000
    records = [{"agent": "ops-bot", "verdict": "pass", "ref": f"Sample review {i}", "source": "tool",
                "ts": dt.datetime.fromtimestamp(base + 2 * i, dt.timezone.utc).isoformat()} for i in range(45)]
    fleet.reviews(records)
    fleet.events("platform", "ops-bot", ["changes_requested", "completed"], ts=base + 87)
    module = collector(fleet, monkeypatch)
    events = module.collect()["events"]
    assert len(events) == 40
    assert [e["ts"] for e in events] == sorted([e["ts"] for e in events], reverse=True)
    assert sum(e["kind"] == "qc-pass" for e in events) == 38
    assert {e["kind"] for e in events} == {"qc-pass", "changes_requested", "completed"}
    assert events[-1]["text"] == "Sample review 7"


def test_collect_opt_out_keeps_reviews_and_log(fleet, monkeypatch):
    fleet.events("platform", "ops-bot", ["completed"] * 3)
    fleet.reviews([{"agent": "ops-bot", "verdict": "pass", "source": "tool"}])
    module = collector(fleet, monkeypatch, kanban_xp=False)
    snapshot = module.collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["xp"] == 10
    assert bot["own"] == [1, 0, 0]
    assert bot["attrsSource"] is None
    assert any(e["kind"] == "completed" for e in snapshot["events"])


def test_collect_uses_newest_events_even_when_kanban_is_older_than_a_week(fleet, monkeypatch):
    now = time.time()
    fleet.events("platform", "ops-bot", ["completed"], ts=now - 8 * 86400)
    fleet.reviews([{"agent": "ops-bot", "verdict": "pass", "source": "tool",
                    "ts": dt.datetime.fromtimestamp(now - 9 * 86400, dt.timezone.utc).isoformat()}])
    snapshot = collector(fleet, monkeypatch).collect()
    assert [event["kind"] for event in snapshot["events"]] == ["completed", "qc-pass"]


def test_self_reviews_stay_in_log_but_do_not_set_or_advance_last_qc(fleet, monkeypatch):
    module = collector(fleet, monkeypatch)
    record = {"agent": "ops-bot", "reviewer": "ops-bot", "verdict": "pass",
              "source": "tool", "ts": "2026-01-03T00:00:00+00:00"}
    fleet.reviews([record])
    snapshot = module.collect()
    assert next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")["lastQc"] is None
    assert snapshot["events"][0]["selfReview"] is True
    legitimate = {**record, "reviewer": "operator", "ts": "2026-01-02T00:00:00+00:00"}
    fleet.reviews([legitimate, record])
    snapshot = module.collect()
    stamp = dt.datetime.fromisoformat(legitimate["ts"]).timestamp()
    assert next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")["lastQc"] == stamp
    assert [event["selfReview"] for event in snapshot["events"]] == [True, False]


def test_historical_log_does_not_expand_the_mirage_7_day_counter(fleet, monkeypatch):
    now = time.time()
    fleet.events("platform", "ops-bot", ["suspected_hallucinated_references"], ts=now - 8 * 86400)
    fleet.events("website", "ops-bot", ["suspected_hallucinated_references"], ts=now)
    snapshot = collector(fleet, monkeypatch).collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["hallu7d"] == 1
    assert len(snapshot["events"]) == 2
