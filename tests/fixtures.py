"""Small, invented Hermes installations backed by real SQLite files."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class Fleet:
    root: Path
    boards: dict[str, Path]
    reviews_path: Path
    legacy_path: Path

    def events(self, board, bot, kinds, *, task_id=None, title="Verify the sample service", ts=None):
        """Append fixture events; each board has an independent event-id sequence."""
        ts = time.time() if ts is None else ts
        with sqlite3.connect(self.boards[board]) as con:
            if task_id is None:
                count = con.execute("SELECT count(*) FROM tasks").fetchone()[0]
                task_id = f"t_sample_{count}"
            con.execute(
                "INSERT OR IGNORE INTO tasks (id, title, assignee, status, created_at) VALUES (?, ?, ?, 'done', ?)",
                (task_id, title, bot, ts),
            )
            con.executemany(
                "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, 1, ?, '{}', ?)",
                [(task_id, kind, ts + i) for i, kind in enumerate(kinds)],
            )
        return task_id

    def reviews(self, records, *, legacy=False):
        path = self.legacy_path if legacy else self.reviews_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path


def make_home(root: Path) -> Fleet:
    root.mkdir()
    for home in (root, root / "profiles" / "ops-bot"):
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("model:\n  default: sample/model\n  provider: sample\n", encoding="utf-8")
        (home / "profile.yaml").write_text("description: Sample operator\n", encoding="utf-8")
        with sqlite3.connect(home / "state.db") as con:
            con.executescript("""
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, title TEXT, source TEXT, started_at REAL,
                    ended_at REAL, last_activity_at REAL, last_activity_description TEXT,
                    parent_session_id TEXT, input_tokens INTEGER, output_tokens INTEGER,
                    estimated_cost_usd REAL, message_count INTEGER, tool_call_count INTEGER, model TEXT
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
                    tool_calls TEXT, timestamp REAL
                );
            """)
    boards = {}
    for board in ("platform", "website"):
        db = root / "kanban" / "boards" / board / "kanban.db"
        db.parent.mkdir(parents=True)
        optional = ", block_kind TEXT, last_heartbeat_at INTEGER" if board == "platform" else ""
        with sqlite3.connect(db) as con:
            con.executescript(f"""
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
                    status TEXT NOT NULL, priority INTEGER DEFAULT 0, created_at INTEGER,
                    started_at INTEGER, worker_pid INTEGER, block_recurrences INTEGER DEFAULT 0
                    {optional}
                );
                CREATE TABLE task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id INTEGER,
                    kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL
                );
                CREATE TABLE task_comments (
                    id INTEGER PRIMARY KEY, task_id TEXT, author TEXT, body TEXT, created_at INTEGER
                );
                CREATE TABLE task_links (parent_id TEXT, child_id TEXT, PRIMARY KEY(parent_id, child_id));
            """)
        boards[board] = db
    data = root / "plugin-data" / "pixel-hq"
    data.mkdir(parents=True)
    roster = {
        "rooms": [{"id": "hq", "label": "HEADQUARTERS", "main": True,
                   "zones": [{"id": "crew", "label": "CREW"}]}],
        "bots": [{"id": bot, "title": "Recruit", "cls": "Sample operator", "zone": "crew",
                  "color": "#93A1AF", **({"remote": True} if bot == "remote-bot" else {})}
                 for bot in ("default", "ops-bot", "remote-bot")],
    }
    (data / "roster.json").write_text(json.dumps(roster), encoding="utf-8")
    (data / "config.json").write_text(json.dumps({"hermes_home": str(root)}), encoding="utf-8")
    return Fleet(root, boards, data / "reviews.jsonl", root / "quality" / "ledger.jsonl")


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    fixture = make_home(tmp_path / "hermes")
    monkeypatch.setenv("HERMES_HOME", str(fixture.root))
    return fixture
