#!/usr/bin/env python3
"""Read-only blocked-card details, shared by the collector and the triage CLI.

Usage: python3 blockers.py [board/t_id ...]
Without arguments: every blocked card. Card texts are untrusted input.
"""
from __future__ import annotations

import collections
import contextlib
import json
import re
import sys
import time
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/blockers.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from . import config as cfgmod, dbutil
from .common import boards, clip

# The action handler enforces the same category policy server-side.
ALLOWED = {
    "you": ["answer", "comment", "archive"],
    "technical": ["retry", "comment", "archive"],
    "stale": ["retry", "comment", "archive"],
    "unknown": ["retry", "comment", "archive"],
    "upstream": ["comment"],
}
CAT_ORDER = {"you": 0, "technical": 1, "stale": 2, "unknown": 3, "upstream": 4}


def _payload(raw, warnings: list[str] | None = None, source: str = "task_events") -> dict:
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("invalid payload")
        return data
    except Exception:
        if warnings is not None:
            dbutil.warning(warnings, source, "invalid event payload")
        return {}


def _blocked_rows(db: Path, board: str, errors: list[str]) -> tuple:
    """Read and index one board, skipping auxiliary reads when nothing is blocked."""
    by_event, by_comment, by_parent = collections.defaultdict(list), {}, collections.defaultdict(list)
    with contextlib.closing(dbutil.ro(db)) as con:
        tasks = dbutil.rows(con, "tasks", ["id", "title", "body", "assignee", "created_at", "block_kind",
                                           "block_recurrences", "status"], warnings=errors, source=board)
        blocked = [task for task in tasks if task[-1] == "blocked"]
        if not blocked:
            return blocked, by_event, by_comment, by_parent
        events = dbutil.rows(con, "task_events", ["id", "task_id", "kind", "payload", "created_at"],
                             "kind IN ('blocked','gave_up','timed_out') ORDER BY id DESC",
                             warnings=errors, source=board)
        comments = dbutil.rows(con, "task_comments", ["id", "task_id", "author", "body", "created_at"],
                               "1 ORDER BY id DESC", warnings=errors, source=board)
        links = dbutil.rows(con, "task_links", ["parent_id", "child_id"], warnings=errors, source=board)
    by_id = {task[0]: task for task in tasks}
    for eid, tid, kind, payload, ts in events:
        if len(by_event[tid]) < 6:
            by_event[tid].append((kind, payload, ts))
    for cid, tid, author, body, ts in comments:
        by_comment.setdefault(tid, (author, body, ts))
    for parent, child in links:
        if parent in by_id:
            task = by_id[parent]
            by_parent[child].append((task[0], task[1], task[-1]))
    return blocked, by_event, by_comment, by_parent


def read_blockers(cfg: dict | None = None, roster: dict | None = None) -> tuple[list, list]:
    """Every blocked card on every board with reason, age, upstream cards and a category."""
    cfg = cfgmod.load() if cfg is None else cfg
    roster = cfgmod.load_roster() if roster is None else roster
    user_re = re.compile("|".join(re.escape(k) for k in cfg["needs_input_keywords"]) or r"(?!x)x", re.I)
    stale_days = cfg["stale_days"]
    remote = {bot["id"] for bot in roster["bots"] if bot.get("remote")}
    out, errors = [], []
    now = time.time()
    for board, db in boards(cfg):
        try:
            blocked, by_event, by_comment, by_parent = _blocked_rows(db, board, errors)
            for tid, title, body, assignee, created, kind, rec, status in blocked:
                blocked_at, reason, actor, tech = None, "", "", False
                for event_kind, payload, ts in by_event[tid]:
                    data = _payload(payload, errors, f"{board}/task_events")
                    if event_kind == "blocked":
                        if blocked_at is None:
                            blocked_at = ts
                            actor = data.get("actor") or ""
                            kind = kind or data.get("kind")
                            if data.get("reason") and data.get("reason") != "initial_status":
                                reason = str(data["reason"])
                    elif event_kind in ("gave_up", "timed_out"):
                        tech = True
                        if not reason and data.get("error"):
                            reason = f"{event_kind}: {data['error']}"
                comment = by_comment.get(tid)
                parents = by_parent[tid]
                open_parents = [{"id": p[0], "title": clip(p[1], 70), "status": p[2]} for p in parents if p[2] != "done"]
                since = float(blocked_at or created or now)
                age_d = int((now - since) // 86400)
                hay = f"{title} {reason}"
                if open_parents:
                    cat = "upstream"
                elif kind == "needs_input" or user_re.search(hay) or (actor == "user" and not tech and not reason):
                    cat = "you"
                elif kind in ("capability", "transient") or tech:
                    cat = "technical"
                elif age_d >= stale_days:
                    cat = "stale"
                else:
                    cat = "unknown"
                if not reason:
                    if cat == "you" and kind == "needs_input":
                        reason = "needs_input (question is in the comment/body, no reason text recorded)"
                    elif cat == "you" and user_re.search(title or ""):
                        reason = "title mentions approval/decision/gate (no reason text recorded)"
                    elif actor == "user" and not tech:
                        reason = "created as blocked (manual gate)"
                    elif comment:
                        reason = "last comment: " + str(comment[1])
                out.append({"board": board, "id": tid, "title": clip(title, 160), "assignee": assignee or "?",
                            "kind": kind or "", "cat": cat, "ageDays": age_d, "stale": age_d >= stale_days,
                            "since": since, "recurrences": rec or 0, "reason": clip(reason, 400),
                            "body": clip((body or "").strip(), 500),
                            "comment": ({"author": comment[0], "text": clip(comment[1], 400), "ts": comment[2]} if comment else None),
                            "openParents": open_parents, "actions": ALLOWED[cat],
                            "remote": (assignee or "") in remote})
        except Exception as exc:
            dbutil.warning(errors, board, exc)
    out.sort(key=lambda card: (CAT_ORDER[card["cat"]], -card["ageDays"]))
    return out, errors


def query(keys=None) -> dict:
    """Project optional board/card selectors without running on module import."""
    keys = set(keys or ())
    rows, errors = read_blockers()
    out = [{key: card[key] for key in ("board", "id", "cat", "assignee", "ageDays", "kind", "title", "reason",
                                      "comment", "openParents", "body", "actions", "remote")}
           for card in rows if not keys or f"{card['board']}/{card['id']}" in keys]
    missing = sorted(keys - {f"{card['board']}/{card['id']}" for card in rows})
    return {"count": len(out), "notBlockedAnymore": missing, "boardErrors": errors, "warnings": errors, "cards": out}


if __name__ == "__main__":
    print(json.dumps(query(sys.argv[1:]), ensure_ascii=False, indent=1))
