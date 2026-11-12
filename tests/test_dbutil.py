"""SQLite reads keep available data when Hermes schemas omit optional fields."""
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_scoring_collect import collector


def live_reader(fleet, monkeypatch, module):
    from pixelhq import live

    return live


def test_older_board_still_yields_blocked_cards_and_running_tasks(fleet, monkeypatch):
    now = time.time()
    blocked = fleet.events("website", "ops-bot", ["blocked"], title="Repair sample queue", ts=now)
    running = fleet.events("website", "remote-bot", ["claimed"], title="Inspect sample job", ts=now)
    with sqlite3.connect(fleet.boards["website"]) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (blocked,))
        con.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?", (now, running))
        con.execute("UPDATE task_events SET payload=? WHERE task_id=?",
                    ('{"kind":"transient","reason":"Sample transport unavailable"}', blocked))
    module = collector(fleet, monkeypatch)
    snapshot = module.collect()
    assert len(snapshot["blockers"]) == 1
    card = snapshot["blockers"][0]
    assert (card["board"], card["id"], card["cat"]) == ("website", blocked, "technical")
    assert card["reason"] == "Sample transport unavailable"
    assert snapshot["warnings"] == []
    remote = next(bot for bot in snapshot["bots"] if bot["id"] == "remote-bot")
    assert remote["status"] == "running"
    live = live_reader(fleet, monkeypatch, module).query()
    assert live["bots"]["remote-bot"]["active"] is True
    task = live["bots"]["remote-bot"]["tasks"][0]
    assert task["id"] == running
    assert task["heartbeatAt"] is None
    assert task["heartbeatAge"] is None
    assert live["warnings"] == []


@pytest.mark.parametrize("table", ["task_events", "task_comments", "task_links"])
def test_missing_auxiliary_table_keeps_blocked_cards_and_warns(fleet, monkeypatch, table):
    tid = fleet.events("platform", "ops-bot", ["blocked"])
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked', block_kind='needs_input' WHERE id=?", (tid,))
        con.execute(f"DROP TABLE {table}")
    snapshot = collector(fleet, monkeypatch).collect()
    assert [card["id"] for card in snapshot["blockers"]] == [tid]
    assert snapshot["blockers"][0]["cat"] == "you"
    assert any("platform" in warning and table in warning for warning in snapshot["warnings"])
    assert all(len(warning) <= 120 for warning in snapshot["warnings"])


def test_scoring_queries_tolerate_missing_task_and_event_columns(fleet, monkeypatch):
    fleet.events("platform", "ops-bot", ["completed", "completed"])
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("ALTER TABLE tasks DROP COLUMN priority")
        con.execute("ALTER TABLE task_events DROP COLUMN created_at")
    snapshot = collector(fleet, monkeypatch).collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["xp"] == 20
    assert len(snapshot["events"]) == 2
    assert snapshot["warnings"] == []


def test_minimal_session_schema_preserves_activity_and_live_sessions(fleet, monkeypatch):
    now = time.time()
    with sqlite3.connect(fleet.root / "state.db") as con:
        con.execute("DROP TABLE sessions")
        con.execute("CREATE TABLE sessions (id TEXT, title TEXT, started_at REAL)")
        con.execute("INSERT INTO sessions VALUES ('s_example', 'Plan sample rollout', ?)", (now,))
    module = collector(fleet, monkeypatch)
    snapshot = module.collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "default")
    assert bot["lastActivity"] == now
    assert bot["status"] == "running"
    assert bot["quest"] == "Plan sample rollout"
    assert bot["sessions7d"] == 1
    assert snapshot["warnings"] == []
    live = live_reader(fleet, monkeypatch, module).query()
    session = live["bots"]["default"]["sessions"][0]
    assert session["id"] == "s_example"
    assert session["lastAt"] == now
    assert session["inTok"] == session["outTok"] == 0
    assert session["tool"] is None
    assert session["isSub"] is False
    assert live["warnings"] == []


def test_missing_sessions_table_warns_in_both_snapshots(fleet, monkeypatch):
    with sqlite3.connect(fleet.root / "state.db") as con:
        con.execute("DROP TABLE sessions")
    module = collector(fleet, monkeypatch)
    for snapshot in (module.collect(), live_reader(fleet, monkeypatch, module).query()):
        assert any("default" in warning and "sessions" in warning for warning in snapshot["warnings"])
        assert all(len(warning) <= 120 for warning in snapshot["warnings"])
        assert len(snapshot["bots"]) == 3


def test_missing_tasks_table_warns_without_hiding_other_boards(fleet, monkeypatch):
    tid = fleet.events("website", "remote-bot", ["claimed"])
    with sqlite3.connect(fleet.boards["website"]) as con:
        con.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("DROP TABLE tasks")
    module = collector(fleet, monkeypatch)
    snapshot = module.collect()
    assert any("platform" in warning and "tasks" in warning for warning in snapshot["warnings"])
    live = live_reader(fleet, monkeypatch, module).query()
    assert any("platform" in warning and "tasks" in warning for warning in live["warnings"])
    assert live["bots"]["remote-bot"]["tasks"][0]["id"] == tid


def test_missing_messages_table_keeps_live_session_and_warns(fleet, monkeypatch):
    now = time.time()
    with sqlite3.connect(fleet.root / "state.db") as con:
        con.execute("INSERT INTO sessions (id, title, started_at) VALUES ('s_example', 'Sample session', ?)", (now,))
        con.execute("DROP TABLE messages")
    module = collector(fleet, monkeypatch)
    live = live_reader(fleet, monkeypatch, module).query()
    assert live["bots"]["default"]["sessions"][0]["id"] == "s_example"
    assert any("default" in warning and "messages" in warning for warning in live["warnings"])


def test_events_without_identifiers_are_skipped_with_an_explicit_warning(fleet, monkeypatch):
    fleet.events("platform", "ops-bot", ["completed"] * 3)
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("ALTER TABLE task_events RENAME TO previous_events")
        con.execute("CREATE TABLE task_events AS SELECT task_id, kind, payload, created_at FROM previous_events")
    snapshot = collector(fleet, monkeypatch).collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["xp"] == 0
    assert any("platform" in warning and "event id" in warning for warning in snapshot["warnings"])


@pytest.mark.parametrize("schema", ["no-table", "no-status"])
def test_actions_fail_closed_on_incomplete_status_schema(fleet, monkeypatch, schema):
    from pixelhq import actions

    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("DROP TABLE tasks")
        if schema == "no-status":
            con.execute("CREATE TABLE tasks (id TEXT)")
            con.execute("INSERT INTO tasks VALUES ('t_abcdef')")

    def no_cli(*args, **kwargs):
        raise AssertionError("An unreadable status must never invoke the CLI")

    monkeypatch.setattr(actions.subprocess, "run", no_cli)
    result = actions.run({"board": "platform", "id": "t_abcdef", "action": "retry"})
    assert result["ok"] is False
    assert result["error"]
    if schema == "no-table":
        assert any("tasks" in warning for warning in result["warnings"])


def test_blockers_script_exposes_source_warnings_without_losing_cards(fleet):
    tid = fleet.events("platform", "ops-bot", ["blocked"])
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))
        con.execute("DROP TABLE task_comments")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "pixelhq" / "blockers.py")], cwd=root,
                            env={**os.environ, "HERMES_HOME": str(fleet.root)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert [card["id"] for card in data["cards"]] == [tid]
    assert any("task_comments" in warning for warning in data["warnings"])
    assert data["warnings"] == data["boardErrors"]


@pytest.mark.parametrize("payload", ["{invalid}", "[]"])
def test_invalid_board_event_payload_warns_without_dropping_card(fleet, monkeypatch, payload):
    tid = fleet.events("platform", "ops-bot", ["blocked"])
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))
        con.execute("UPDATE task_events SET payload=? WHERE task_id=?", (payload, tid))
    snapshot = collector(fleet, monkeypatch).collect()
    assert snapshot["blockers"][0]["id"] == tid
    assert any("platform" in warning and "payload" in warning for warning in snapshot["warnings"])


def test_invalid_live_tool_arguments_warn_without_dropping_session(fleet, monkeypatch):
    now = time.time()
    with sqlite3.connect(fleet.root / "state.db") as con:
        con.execute("INSERT INTO sessions (id, started_at) VALUES ('s_example', ?)", (now,))
        con.execute("INSERT INTO messages (session_id, role, timestamp, tool_calls) VALUES (?, 'assistant', ?, ?)",
                    ("s_example", now, json.dumps([{"function": {"name": "sample_tool", "arguments": "{invalid}"}}])))
    module = collector(fleet, monkeypatch)
    live = live_reader(fleet, monkeypatch, module).query()
    assert live["bots"]["default"]["sessions"][0]["tool"]["name"] == "sample_tool"
    assert any("default" in warning and "arguments" in warning for warning in live["warnings"])


def test_select_projects_missing_columns_in_filters_and_ordering(tmp_path):
    from pixelhq import dbutil

    path = tmp_path / "sample ?# database.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE tasks (id TEXT, status TEXT)")
        con.execute("INSERT INTO tasks VALUES ('t_example', 'running')")
    with contextlib.closing(dbutil.ro(path)) as con:
        assert dbutil.columns(con, "tasks") == {"id", "status"}
        cursor = dbutil.select(con, "tasks", ["id", "status", "last_heartbeat_at"],
                               "status=? ORDER BY last_heartbeat_at DESC", ("running",))
        assert cursor.fetchall() == [("t_example", "running", None)]
        assert [column[0] for column in cursor.description] == ["id", "status", "last_heartbeat_at"]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("DELETE FROM tasks")
    missing = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        dbutil.ro(missing)
    assert not missing.exists()
