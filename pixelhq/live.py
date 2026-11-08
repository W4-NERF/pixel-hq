"""Pixel HQ live view: what is every bot doing right now? Read-only and fast (built for 10-s polling).

Sources: <profile>/state.db (active sessions — Hermes records `last_activity_description` per step,
e.g. "terminal command running (170s elapsed)"; last tool call from `messages`) and the Kanban boards
(running cards + heartbeat — the only source for remote bots). Free text (titles, commands) is clipped
here and rendered as text only by the UI.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfgmod  # noqa: E402

CFG = cfgmod.load()
HERMES = Path(CFG["hermes_home"])
BOARDS = HERMES / "kanban" / "boards"
EXCLUDE_BOARDS = set(CFG["exclude_boards"])
ACTIVE_S = 10 * 60      # a session counts as active if something happened in the last 10 min
STALE_STEP_S = 5 * 60   # a "running …" step without progress for > 5 min → flagged
ARG_KEYS = ("command", "path", "url", "query", "pattern", "text", "goal", "name", "message", "key", "task_id")


def clip(s, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.5)


def state_db(bot: str) -> Path:
    return HERMES / "state.db" if bot == "default" else HERMES / "profiles" / bot / "state.db"


def last_tool(con: sqlite3.Connection, sid: str) -> dict | None:
    row = con.execute("select tool_calls, timestamp from messages where session_id=? and role='assistant' "
                      "and tool_calls is not null order by timestamp desc limit 1", (sid,)).fetchone()
    if not row:
        return None
    try:
        calls = json.loads(row[0])
        fn = (calls[0].get("function") or {}) if calls else {}
        name = fn.get("name") or "?"
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        arg = ""
        if isinstance(args, dict):
            for k in ARG_KEYS:
                if isinstance(args.get(k), str) and args[k].strip():
                    arg = args[k]
                    break
            if not arg:
                arg = next((v for v in args.values() if isinstance(v, str) and v.strip()), "")
        return {"name": name, "arg": clip(arg, 160), "ts": float(row[1]), "n": len(calls)}
    except Exception:
        return None


def read_sessions(bot: str, now: float) -> dict:
    db = state_db(bot)
    out = {"active": [], "last": None, "error": None}
    if not db.exists():
        return out
    try:
        con = ro(db)
        rows = con.execute(
            "select id, title, source, started_at, coalesce(last_activity_at, started_at) as la, "
            "last_activity_description, parent_session_id, input_tokens, output_tokens, estimated_cost_usd, "
            "message_count, tool_call_count, model from sessions where ended_at is null and "
            "coalesce(last_activity_at, started_at) > ? order by la desc limit 12", (now - ACTIVE_S,)).fetchall()
        for r in rows:
            sid, title, source, started, la, desc, parent, itok, otok, cost, mc, tc, model = r
            tool = last_tool(con, sid)
            step = clip(desc or "", 120)
            out["active"].append({
                "id": sid, "title": clip(title or "(untitled)", 140), "source": source or "?",
                "startedAt": float(started or la), "lastAt": float(la), "step": step,
                "stale": bool(step and "running" in step and now - float(la) > STALE_STEP_S),
                "parent": parent, "tool": tool, "inTok": itok or 0, "outTok": otok or 0,
                "cost": round(float(cost), 3) if cost else None, "msgs": mc or 0, "toolCalls": tc or 0,
                "model": clip(model or "", 40)})
        last = con.execute("select coalesce(last_activity_at, started_at), title, last_activity_description, source "
                           "from sessions where source != 'subagent' order by 1 desc limit 1").fetchone()
        if last:
            out["last"] = {"at": float(last[0]), "title": clip(last[1] or "", 70), "step": clip(last[2] or "", 80),
                           "source": last[3]}
        for x in out["active"]:
            x["isSub"] = x["source"] == "subagent" or bool(x.get("parent")) or x["title"].startswith("Subagent:")
        con.close()
    except Exception as exc:
        out["error"] = clip(str(exc), 100)
    return out


def read_running_tasks(now: float) -> dict:
    tasks: dict[str, list] = {}
    for bdir in sorted(BOARDS.glob("*/")):
        db = bdir / "kanban.db"
        if not db.exists() or bdir.name in EXCLUDE_BOARDS:
            continue
        try:
            con = ro(db)
            for tid, title, assignee, started, hb, pid in con.execute(
                    "select id, title, assignee, started_at, last_heartbeat_at, worker_pid from tasks "
                    "where status='running'"):
                tasks.setdefault(assignee or "?", []).append({
                    "board": bdir.name, "id": tid, "title": clip(title, 90),
                    "startedAt": float(started) if started else None,
                    "heartbeatAt": float(hb) if hb else None,
                    "heartbeatAge": int(now - float(hb)) if hb else None, "pid": pid})
            con.close()
        except Exception:
            continue
    return tasks


def query(params: dict | None = None) -> dict:
    t0 = time.time()
    now = time.time()
    roster = cfgmod.load_roster()["bots"]
    tasks = read_running_tasks(now)
    bots = {}
    for r in roster:
        bid = r["id"]
        s = {"active": [], "last": None, "error": None} if r.get("remote") else read_sessions(bid, now)
        # nest sub-agents under their parent session (parent_session_id set or title "Subagent: …";
        # newer Hermes versions record them with the parent's source instead of source=subagent)
        is_sub = lambda x: x["source"] == "subagent" or bool(x.get("parent")) or x["title"].startswith("Subagent:")
        subs = [x for x in s["active"] if is_sub(x)]
        mains = [x for x in s["active"] if not is_sub(x)]
        by_id = {x["id"]: x for x in mains}
        orphans = []
        for sub in subs:
            p = by_id.get(sub.get("parent"))
            (p.setdefault("children", []) if p else orphans).append(sub)
        mains.extend(orphans)
        bt = tasks.get(bid, [])
        active = bool(mains) or any(t["heartbeatAge"] is not None and t["heartbeatAge"] < ACTIVE_S for t in bt)
        bots[bid] = {"active": active, "sessions": mains[:8], "tasks": bt, "last": s["last"], "error": s["error"],
                     "remote": bool(r.get("remote"))}
    return {"generated": now, "ms": round(1000 * (time.time() - t0)), "bots": bots,
            "unassignedTasks": {k: v for k, v in tasks.items() if k not in bots}}


if __name__ == "__main__":
    print(json.dumps(query(), ensure_ascii=False, indent=1))
