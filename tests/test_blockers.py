"""Blocker refactoring retains category precedence, fallbacks and bounded histories."""
import json
import sqlite3

import pytest

from pixelhq import blockers, collect, config

NOW = 1800000000.0


@pytest.mark.parametrize("kind,payload,title,days,parent_status,category,reason", [
    ("needs_input", {"reason": "Sample fault"}, "Sample task", 20, "running", "upstream", "Sample fault"),
    ("needs_input", {}, "Sample task", 20, "done", "you",
     "needs_input (question is in the comment/body, no reason text recorded)"),
    ("transient", {"reason": "Approval required"}, "Sample task", 20, None, "you", "Approval required"),
    (None, {"actor": "user", "reason": "initial_status"}, "Sample task", 0, None, "you",
     "created as blocked (manual gate)"),
    (None, {}, "Approval for sample task", 0, None, "you",
     "title mentions approval/decision/gate (no reason text recorded)"),
    ("capability", {}, "Sample task", 20, None, "technical", "last comment: New sample note"),
    ("transient", {}, "Sample task", 20, None, "technical", "last comment: New sample note"),
    (None, {}, "Sample task", 14, None, "stale", "last comment: New sample note"),
    (None, {}, "Sample task", 13, None, "unknown", "last comment: New sample note"),
])
def test_category_precedence_and_reason_fallbacks_remain_unchanged(
        fleet, monkeypatch, kind, payload, title, days, parent_status, category, reason):
    monkeypatch.setattr(blockers.time, "time", lambda: NOW)
    since = NOW - days * 86400
    tid = fleet.events("platform", "remote-bot", ["blocked"], title=title, ts=since)
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked', body=?, block_kind=?, block_recurrences=2 WHERE id=?",
                    ("  Sample\nbody  ", kind, tid))
        con.execute("UPDATE task_events SET payload=? WHERE task_id=?", (json.dumps(payload), tid))
        con.executemany("INSERT INTO task_comments VALUES (?, ?, 'operator', ?, ?)",
                        [(1, tid, "Old sample note", NOW), (2, tid, "New sample note", since)])
        if parent_status:
            con.execute("INSERT INTO tasks (id, title, status) VALUES ('t_parent', 'Sample parent', ?)",
                        (parent_status,))
            con.execute("INSERT INTO task_links VALUES ('t_parent', ?)", (tid,))
    cards, warnings = collect.read_blockers(config.load(), config.load_roster())
    assert warnings == []
    assert cards == [{
        "board": "platform", "id": tid, "title": title, "assignee": "remote-bot",
        "kind": kind or "", "cat": category, "ageDays": days, "stale": days >= 14,
        "since": since, "recurrences": 2, "reason": reason, "body": "Sample\nbody",
        "comment": {"author": "operator", "text": "New sample note", "ts": since},
        "openParents": ([{"id": "t_parent", "title": "Sample parent", "status": parent_status}]
                        if parent_status and parent_status != "done" else []),
        "actions": blockers.ALLOWED[category], "remote": True,
    }]


def test_only_the_latest_six_block_events_contribute(fleet, monkeypatch):
    monkeypatch.setattr(blockers.time, "time", lambda: NOW)
    tid = fleet.events("platform", "ops-bot", ["blocked"] + ["timed_out"] * 6, ts=NOW - 20 * 86400)
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))
        con.execute("UPDATE task_events SET payload=? WHERE kind='blocked'", ('{"reason":"Approval required"}',))
        con.execute("UPDATE task_events SET payload=? WHERE kind='timed_out'", ('{"error":"Sample failure"}',))
    cards, warnings = blockers.read_blockers()
    assert warnings == []
    assert len(cards) == 1
    assert cards[0]["cat"] == "technical"
    assert cards[0]["reason"] == "timed_out: Sample failure"
    assert cards[0]["since"] == NOW - 20 * 86400


def test_unblocked_boards_do_not_query_missing_auxiliary_tables(fleet):
    for path in fleet.boards.values():
        with sqlite3.connect(path) as con:
            for table in ("task_events", "task_comments", "task_links"):
                con.execute(f"DROP TABLE {table}")
    assert blockers.read_blockers() == ([], [])
