"""Pixel HQ live view: what is every bot doing right now? Read-only and fast (built for 10-s polling).

Sources: <profile>/state.db (active sessions — Hermes records `last_activity_description` per step,
e.g. "terminal command running (170s elapsed)"; last tool call from `messages`) and the Kanban boards
(running cards + heartbeat — the only source for remote bots). Free text (titles, commands) is clipped
here and rendered as text only by the UI.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
import time
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/live.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from . import config as cfgmod
from . import dbutil, profiles
from .collect import roster_bots
from .common import boards, clip, state_db

ACTIVE_S = 10 * 60      # a session counts as active if something happened in the last 10 min
STALE_STEP_S = 5 * 60   # a "running …" step without progress for > 5 min → flagged
ARG_KEYS = ("command", "path", "url", "query", "pattern", "text", "goal", "name", "message", "key", "task_id")


def last_tool(con: sqlite3.Connection, sid: str, warnings: list[str] | None = None, source: str = "messages") -> dict | None:
    warnings = warnings if warnings is not None else []
    rows = dbutil.rows(con, "messages", ["tool_calls", "timestamp", "session_id", "role"],
                       "session_id=? AND role='assistant' AND tool_calls IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                       (sid,), warnings=warnings, source=source)
    if not rows:
        return None
    row = rows[0]
    try:
        calls = json.loads(row[0])
        fn = (calls[0].get("function") or {}) if calls else {}
        name = fn.get("name") or "?"
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            dbutil.warning(warnings, f"{source}/messages", "invalid tool arguments")
            args = {}
        arg = ""
        if isinstance(args, dict):
            for k in ARG_KEYS:
                if isinstance(args.get(k), str) and args[k].strip():
                    arg = args[k]
                    break
            if not arg:
                arg = next((v for v in args.values() if isinstance(v, str) and v.strip()), "")
        return {"name": name, "arg": clip(arg, 160, collapse_whitespace=True),
                "ts": float(row[1]) if row[1] is not None else None, "n": len(calls)}
    except Exception as exc:
        dbutil.warning(warnings, f"{source}/messages", exc)
        return None


def read_sessions(bot: str, now: float, cfg: dict | None = None) -> dict:
    cfg = cfgmod.load() if cfg is None else cfg
    db = state_db(bot, cfg)
    out = {"active": [], "last": None, "error": None, "warnings": []}
    if not db.exists():
        return out
    try:
        with contextlib.closing(dbutil.ro(db)) as con:
            rows = dbutil.rows(
                con, "sessions", ["id", "title", "source", "started_at", "last_activity_at",
                                  "last_activity_description", "parent_session_id", "input_tokens", "output_tokens",
                                  "estimated_cost_usd", "message_count", "tool_call_count", "model", "ended_at"],
                "ended_at IS NULL AND coalesce(last_activity_at, started_at) > ? "
                "ORDER BY coalesce(last_activity_at, started_at) DESC LIMIT 12", (now - ACTIVE_S,),
                warnings=out["warnings"], source=bot)
            for row in rows:
                sid, title, source, started, last_at, desc, parent, itok, otok, cost, mc, tc, model, _ended = row
                la = last_at or started
                tool = last_tool(con, sid, out["warnings"], bot)
                step = clip(desc or "", 120, collapse_whitespace=True)
                out["active"].append({
                    "id": sid, "title": clip(title or "(untitled)", 140, collapse_whitespace=True), "source": source or "?",
                    "startedAt": float(started or la), "lastAt": float(la), "step": step,
                    "stale": bool(step and "running" in step and now - float(la) > STALE_STEP_S),
                    "parent": parent, "tool": tool, "inTok": itok or 0, "outTok": otok or 0,
                    "cost": round(float(cost), 3) if cost else None, "msgs": mc or 0, "toolCalls": tc or 0,
                    "model": clip(model or "", 40, collapse_whitespace=True)})
            last_rows = dbutil.rows(con, "sessions", ["last_activity_at", "started_at", "title",
                                                     "last_activity_description", "source"],
                                    "coalesce(source, '') != 'subagent' "
                                    "ORDER BY coalesce(last_activity_at, started_at) DESC LIMIT 1",
                                    warnings=out["warnings"], source=bot)
        if last_rows:
            last = last_rows[0]
            at = last[0] or last[1]
            out["last"] = {"at": float(at) if at is not None else None,
                           "title": clip(last[2], 70, collapse_whitespace=True),
                           "step": clip(last[3], 80, collapse_whitespace=True), "source": last[4]}
        for session in out["active"]:
            session["isSub"] = (session["source"] == "subagent" or bool(session.get("parent"))
                                or session["title"].startswith("Subagent:"))
    except Exception as exc:
        out["error"] = clip(str(exc), 100, collapse_whitespace=True)
    return out


def read_running_tasks(now: float, warnings: list[str] | None = None, cfg: dict | None = None) -> dict:
    cfg = cfgmod.load() if cfg is None else cfg
    warnings = warnings if warnings is not None else []
    tasks: dict[str, list] = {}
    for board, db in boards(cfg):
        try:
            with contextlib.closing(dbutil.ro(db)) as con:
                rows = dbutil.rows(con, "tasks", ["id", "title", "assignee", "started_at", "last_heartbeat_at",
                                                   "worker_pid", "status"], "status='running'",
                                   warnings=warnings, source=board)
            for tid, title, assignee, started, hb, pid, _status in rows:
                tasks.setdefault(assignee or "?", []).append({
                    "board": board, "id": tid, "title": clip(title, 90, collapse_whitespace=True),
                    "startedAt": float(started) if started else None,
                    "heartbeatAt": float(hb) if hb else None,
                    "heartbeatAge": int(now - float(hb)) if hb else None, "pid": pid})
        except Exception as exc:
            dbutil.warning(warnings, board, exc)
    return tasks


def query(params: dict | None = None) -> dict:
    t0 = time.time()
    now = time.time()
    cfg, roster_data = cfgmod.load(), cfgmod.load_roster()
    warnings = list(cfg.get("warnings", [])) + roster_data.get("warnings", [])
    roster = roster_bots(profiles.list_profiles(Path(cfg["hermes_home"]), warnings), warnings,
                         roster=roster_data, cfg=cfg)
    tasks = read_running_tasks(now, warnings, cfg)
    bots = {}
    for r in roster:
        bid = r["id"]
        s = {"active": [], "last": None, "error": None} if r.get("remote") else read_sessions(bid, now, cfg)
        warnings.extend(s.get("warnings", []))
        if s["error"]:
            dbutil.warning(warnings, bid, s["error"])
        # nest sub-agents under their parent session (parent_session_id set or title "Subagent: …";
        # newer Hermes versions record them with the parent's source instead of source=subagent)
        def is_sub(x):
            return x["source"] == "subagent" or bool(x.get("parent")) or x["title"].startswith("Subagent:")
        subs = [x for x in s["active"] if is_sub(x)]
        mains = [x for x in s["active"] if not is_sub(x)]
        by_id = {x["id"]: x for x in mains}
        orphans = []
        for sub in subs:
            p = by_id.get(sub.get("parent"))
            (p.setdefault("children", []) if p else orphans).append(sub)
        mains.extend(orphans)
        bt = tasks.get(bid, [])
        active = bool(mains) or bool(bt)
        bots[bid] = {"active": active, "sessions": mains[:8], "tasks": bt, "last": s["last"], "error": s["error"],
                     "remote": bool(r.get("remote"))}
    return {"generated": now, "ms": round(1000 * (time.time() - t0)), "bots": bots, "warnings": warnings,
            "unassignedTasks": {k: v for k, v in tasks.items() if k not in bots}}


if __name__ == "__main__":
    print(json.dumps(query(), ensure_ascii=False, indent=1))
