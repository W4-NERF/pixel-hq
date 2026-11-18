"""Invented multi-home installation for the exporter tests: two homes, one shared board database.

Home ``atlas-home`` is the ``tests.fixtures`` fleet (profiles default and ops-bot, boards platform and website).
Home ``harbor-home`` has default (a duplicate name) and harbor-bot, its own board ``harbor`` and a symlinked
board directory ``mirror`` that points at the shared database kept outside both homes (``ledger``).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from tests.fixtures import Fleet, make_home

STATE_DDL = """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY, title TEXT, source TEXT, started_at REAL,
        ended_at REAL, last_activity_at REAL, last_activity_description TEXT,
        parent_session_id TEXT, input_tokens INTEGER, output_tokens INTEGER,
        estimated_cost_usd REAL, message_count INTEGER, tool_call_count INTEGER, model TEXT
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, timestamp REAL
    );
"""
BOARD_DDL = """
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT, status TEXT NOT NULL,
        priority INTEGER DEFAULT 0, created_at INTEGER, started_at INTEGER, completed_at INTEGER,
        worker_pid INTEGER, block_recurrences INTEGER DEFAULT 0, block_kind TEXT, last_heartbeat_at INTEGER
    );
    CREATE TABLE task_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id INTEGER,
        kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL
    );
    CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT, author TEXT, body TEXT, created_at INTEGER);
    CREATE TABLE task_links (parent_id TEXT, child_id TEXT, PRIMARY KEY(parent_id, child_id));
"""
SECRET_ARG = "ls /srv/private-sample-dir"


@dataclass
class Remote:
    atlas: Fleet
    harbor: Path
    shared_db: Path
    now: float

    @property
    def homes(self) -> list[Path]:
        return [self.atlas.root, self.harbor]

    def trees(self) -> list[Path]:
        return [self.atlas.root, self.harbor, self.shared_db.parent]


def profile_home(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.yaml").write_text("model:\n  default: sample/model\n  provider: sample\n", encoding="utf-8")
    with sqlite3.connect(path / "state.db") as con:
        con.executescript(STATE_DDL)


def board_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(BOARD_DDL)
    return path


def add_task(db: Path, tid: str, title: str, assignee: str, status: str, **extra) -> None:
    row = {"id": tid, "title": title, "assignee": assignee, "status": status, "created_at": int(time.time()) - 86400, **extra}
    with sqlite3.connect(db) as con:
        con.execute(f"INSERT INTO tasks ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def add_event(db: Path, tid: str, kind: str, payload: dict | None = None, at: float | None = None) -> None:
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, 1, ?, ?, ?)",
                    (tid, kind, json.dumps(payload or {}), int(at or time.time())))


def add_session(home: Path, now: float, *, step="terminal command running (12s elapsed)", title="Check the sample service") -> None:
    """One active main session of the profile at ``home`` whose last assistant message calls a tool with arguments."""
    calls = [{"function": {"name": "terminal", "arguments": json.dumps({"command": SECRET_ARG})}}]
    with sqlite3.connect(home / "state.db") as con:
        con.execute("INSERT INTO sessions (id, title, source, started_at, last_activity_at, last_activity_description) "
                    "VALUES ('s1', ?, 'cli', ?, ?, ?)", (title, now - 60, now - 5, step))
        con.execute("INSERT INTO messages (session_id, role, content, tool_calls, timestamp) VALUES ('s1', 'assistant', '', ?, ?)",
                    (json.dumps(calls), now - 5))


def build(tmp: Path) -> Remote:
    now = time.time()
    atlas = make_home(tmp / "atlas-home")
    harbor = tmp / "harbor-home"
    profile_home(harbor)
    profile_home(harbor / "profiles" / "harbor-bot")
    shared_dir = tmp / "shared" / "ledger"
    shared = board_db(shared_dir / "kanban.db")
    board_db(harbor / "kanban" / "boards" / "harbor" / "kanban.db")
    (harbor / "kanban" / "boards" / "mirror").symlink_to(shared_dir, target_is_directory=True)
    (harbor / "plugin-data" / "pixel-hq").mkdir(parents=True)
    (harbor / "plugin-data" / "pixel-hq" / "config.json").write_text(json.dumps({"xp_pass": 50}), encoding="utf-8")
    # atlas: two completions for ops-bot, one blocked card, one card that is running, an active session with a tool call
    atlas.events("platform", "ops-bot", ["claimed", "completed"], task_id="t_00a1b2c3")
    atlas.events("platform", "ops-bot", ["claimed", "completed"], task_id="t_00a1b2c4")
    add_task(atlas.boards["platform"], "t_00aa11bb", "Approve the sample change", "ops-bot", "blocked", block_kind="needs_input")
    add_event(atlas.boards["platform"], "t_00aa11bb", "blocked",
              {"actor": "ops-bot", "reason": "Need approval for the sample change"}, now - 3 * 86400)
    add_task(atlas.boards["platform"], "t_sample_odd", "A card with a non-standard id", "ops-bot", "blocked")
    add_task(atlas.boards["website"], "t_00bb22cc", "Write the sample page", "default", "running")
    add_session(atlas.root / "profiles" / "ops-bot", now)
    # harbor + shared board: one completion (xp_pass 50 applies), one blocked card, one done today, one done long ago
    add_task(shared, "t_00cc33dd", "Wait for the sample vendor", "harbor-bot", "blocked", block_kind="transient")
    add_event(shared, "t_00cc33dd", "blocked", {"actor": "harbor-bot", "kind": "transient", "reason": "vendor offline"}, now - 86400)
    add_task(shared, "t_00dd44ee", "Ship the sample report", "harbor-bot", "done", completed_at=int(now) - 600)
    add_event(shared, "t_00dd44ee", "completed", None, now - 600)
    add_task(shared, "t_00ee55ff", "Old sample work", "harbor-bot", "done", completed_at=int(now) - 3 * 86400)
    add_task(shared, "t_00ff6600", "Next sample work", "harbor-bot", "ready")
    return Remote(atlas, harbor, shared, now)


def tree_hash(*roots: Path) -> str:
    """Digest of every path, size, mtime and file content below the roots (symlinks are listed, not followed)."""
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted([root, *root.rglob("*")]):
            info = path.lstat()
            digest.update(f"{path.relative_to(root.parent)}|{info.st_mode}|{info.st_size}|{info.st_mtime_ns}".encode())
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
    return digest.hexdigest()
