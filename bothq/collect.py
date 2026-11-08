#!/usr/bin/env python3
"""Bot-HQ collector — READ-ONLY. Builds one JSON snapshot of the fleet.

Sources
  - quality ledger (JSONL)          → XP / level / HP / attributes
  - `hermes profile list`           → model + gateway state per profile
  - <profile>/state.db (mode=ro)    → last activity, sub-agent sessions
  - ~/.hermes/kanban/boards/*/kanban.db → quests (open cards), blocked cards, event log
  - Prometheus (DCGM + vLLM-style serving metrics) + an OpenAI-compatible /v1/models → "reactor"

Sub-agents / helpers are credited to the bot that spawned them (ledger field ``parent``; otherwise the
configured orchestrator profile, which is the only one writing the ledger). All free text coming from
cards or the ledger is clipped here and escaped in the UI.
"""
from __future__ import annotations

import collections
import colorsys
import datetime as dt
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfgmod  # noqa: E402

CFG = cfgmod.load()
ROSTER = cfgmod.load_roster()
HERMES = Path(CFG["hermes_home"])
LEDGER = Path(CFG["ledger_path"])
BOARDS = HERMES / "kanban" / "boards"
EXCLUDE_BOARDS = set(CFG["exclude_boards"])
ORCH = CFG["orchestrator_profile"]
STALE_DAYS = int(CFG["stale_days"])
XP = CFG["xp"]

ACTIVE_WINDOW_S = 10 * 60
EVENT_WINDOW_S = 7 * 24 * 3600

# blocked-card category -> actions the UI may offer (actions.py enforces the same list server-side)
ALLOWED = {
    "you": ["answer", "comment", "archive"],
    "technical": ["retry", "comment", "archive"],
    "stale": ["retry", "comment", "archive"],
    "unknown": ["retry", "comment", "archive"],
    "upstream": ["comment"],
}
CAT_ORDER = {"you": 0, "technical": 1, "stale": 2, "unknown": 3, "upstream": 4}


def clip(s, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def level_of(xp: int) -> tuple[int, int]:
    lvl = 1 + int(math.sqrt(max(0, xp) / 25))
    lo, hi = 25 * (lvl - 1) ** 2, 25 * lvl ** 2
    return lvl, round(100 * (xp - lo) / max(1, hi - lo))


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)


# ---------------------------------------------------------------- ledger
HELPER_RE = re.compile(r"^(subagent|delegate_task|claude-code-cli|opencode|codex)", re.I)


def attribute(agent: str, entry: dict) -> tuple[str | None, bool]:
    """-> (bot_id, is_summon). None = not attributable (ignored)."""
    a = (agent or "").strip()
    low = a.lower()
    if entry.get("parent"):
        return str(entry["parent"]).strip(), True
    if low.startswith(f"{ORCH.lower()}-subagent") or HELPER_RE.match(low) or low.startswith("cron:"):
        return ORCH, True
    if low.startswith(ORCH.lower()):
        return ORCH, False
    if "+" in a:  # "botA+botB" → first bot
        return a.split("+", 1)[0].strip(), False
    if not a or a == "?":
        return None, False
    return a, False


def read_ledger() -> tuple[dict, list]:
    stats = collections.defaultdict(lambda: {
        "own": collections.Counter(), "sum": collections.Counter(), "dims": [], "last": 0.0})
    recent = []
    if not LEDGER.exists():
        return stats, recent
    for line in LEDGER.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        bot, summon = attribute(e.get("agent", ""), e)
        if not bot:
            continue
        v = e.get("verdict")
        if v not in ("pass", "revise", "fail"):
            continue
        s = stats[bot]
        (s["sum"] if summon else s["own"])[v] += 1
        d = e.get("dims") or e.get("scores") or e
        try:
            s["dims"].append([float(d["correctness"]), float(d["completeness"]),
                              float(d["format"]), float(d["safety"])])
        except Exception:
            pass
        try:
            ts = dt.datetime.fromisoformat(str(e.get("ts"))).timestamp()
        except Exception:
            ts = 0.0
        s["last"] = max(s["last"], ts)
        recent.append({"ts": ts, "bot": bot, "kind": "qc-" + v, "summon": summon,
                       "text": clip(e.get("ref") or e.get("task") or "", 90)})
    recent.sort(key=lambda r: r["ts"], reverse=True)
    return stats, recent[:30]


# ---------------------------------------------------------------- profiles
def read_profiles() -> dict:
    out = {}
    try:
        txt = subprocess.run(["hermes", "profile", "list"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return out
    for l in txt.splitlines():
        p = l.replace("\u25c6", " ").split()
        if len(p) >= 3 and p[0] != "Profile" and not p[0].startswith("\u2500"):
            out[p[0]] = {"model": p[1], "gateway": p[2]}
    return out


def state_db(profile: str) -> Path:
    return HERMES / "state.db" if profile == "default" else HERMES / "profiles" / profile / "state.db"


def read_state(profile: str) -> dict:
    db = state_db(profile)
    res = {"last_activity": None, "last_title": None, "subagent_sessions": 0, "sessions_7d": 0, "active": 0}
    if not db.exists():
        return res
    try:
        con = ro(db)
        now = time.time()
        row = con.execute("select coalesce(last_activity_at, started_at), title, last_activity_description "
                          "from sessions where source != 'subagent' "
                          "order by coalesce(last_activity_at, started_at) desc limit 1").fetchone()
        if row:
            res["last_activity"], res["last_title"] = row[0], (row[1] or row[2])
        res["subagent_sessions"] = con.execute(
            "select count(*) from sessions where source='subagent' or title like 'Subagent:%'").fetchone()[0]
        res["sessions_7d"] = con.execute("select count(*) from sessions where started_at > ?",
                                         (now - 7 * 86400,)).fetchone()[0]
        res["active"] = con.execute("select count(*) from sessions where ended_at is null and "
                                    "coalesce(last_activity_at, started_at) > ?", (now - ACTIVE_WINDOW_S,)).fetchone()[0]
        con.close()
    except Exception as exc:  # locked / different schema → bot stays visible without state
        res["error"] = str(exc)[:120]
    return res


# ---------------------------------------------------------------- kanban
EV_KINDS = ("completed", "blocked", "gave_up", "timed_out", "protocol_violation",
            "suspected_hallucinated_references", "created")


def boards():
    for bdir in sorted(BOARDS.glob("*/")):
        db = bdir / "kanban.db"
        if db.exists() and bdir.name not in EXCLUDE_BOARDS:
            yield bdir.name, db


def read_kanban() -> tuple[dict, list]:
    quests = collections.defaultdict(list)
    events = []
    since = time.time() - EVENT_WINDOW_S
    for board, db in boards():
        try:
            con = ro(db)
            for tid, title, assignee, status, prio in con.execute(
                    "select id, title, assignee, status, priority from tasks "
                    "where status in ('running','blocked','ready','todo','review','scheduled')"):
                quests[assignee or "?"].append({"id": tid, "title": clip(title, 140), "status": status,
                                                "board": board, "prio": prio or 0})
            q = ("select e.created_at, e.kind, t.assignee, t.title, t.id from task_events e "
                 "join tasks t on t.id = e.task_id where e.created_at > ? and e.kind in (%s)"
                 % ",".join("?" * len(EV_KINDS)))
            for ts, kind, assignee, title, tid in con.execute(q, (since, *EV_KINDS)):
                events.append({"ts": float(ts), "bot": assignee or "?", "kind": kind,
                               "text": f"{clip(title, 90)} [{board}/{tid}]"})
            con.close()
        except Exception:
            continue
    events.sort(key=lambda r: r["ts"], reverse=True)
    return quests, events


# ---------------------------------------------------------------- blocked cards (read-only)
USER_RE = re.compile("|".join(re.escape(k) for k in CFG["needs_input_keywords"]) or r"(?!x)x", re.I)


def _payload(raw) -> dict:
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def read_blockers() -> tuple[list, list]:
    """Every blocked card on every board with reason, age, upstream cards and a category."""
    remote = {b["id"] for b in ROSTER["bots"] if b.get("remote")}
    out, errors = [], []
    now = time.time()
    for board, db in boards():
        try:
            con = ro(db)
            tasks = con.execute("select id, title, body, assignee, created_at, block_kind, "
                                "coalesce(block_recurrences,0) from tasks where status='blocked'").fetchall()
            for tid, title, body, assignee, created, kind, rec in tasks:
                evs = con.execute("select kind, payload, created_at from task_events where task_id=? and kind in "
                                  "('blocked','gave_up','timed_out') order by id desc limit 6", (tid,)).fetchall()
                blocked_at, reason, actor, tech = None, "", "", False
                for ek, pl, ts in evs:
                    p = _payload(pl)
                    if ek == "blocked":
                        if blocked_at is None:
                            blocked_at = ts
                            actor = p.get("actor") or ""
                            kind = kind or p.get("kind")
                            if p.get("reason") and p.get("reason") != "initial_status":
                                reason = str(p["reason"])
                    elif ek in ("gave_up", "timed_out"):
                        tech = True
                        if not reason and p.get("error"):
                            reason = f"{ek}: {p['error']}"
                cm = con.execute("select author, body, created_at from task_comments where task_id=? "
                                 "order by id desc limit 1", (tid,)).fetchone()
                parents = con.execute("select t.id, t.title, t.status from task_links l join tasks t on t.id=l.parent_id "
                                      "where l.child_id=?", (tid,)).fetchall()
                open_parents = [{"id": p[0], "title": clip(p[1], 70), "status": p[2]} for p in parents if p[2] != "done"]
                since = float(blocked_at or created or now)
                age_d = int((now - since) // 86400)
                hay = f"{title} {reason}"
                if open_parents:
                    cat = "upstream"
                elif kind == "needs_input" or USER_RE.search(hay) or (actor == "user" and not tech and not reason):
                    cat = "you"
                elif kind in ("capability", "transient") or tech:
                    cat = "technical"
                elif age_d >= STALE_DAYS:
                    cat = "stale"
                else:
                    cat = "unknown"
                if not reason:
                    if cat == "you" and kind == "needs_input":
                        reason = "needs_input (question is in the comment/body, no reason text recorded)"
                    elif cat == "you" and USER_RE.search(title or ""):
                        reason = "title mentions approval/decision/gate (no reason text recorded)"
                    elif actor == "user" and not tech:
                        reason = "created as blocked (manual gate)"
                    elif cm:
                        reason = "last comment: " + str(cm[1])
                out.append({"board": board, "id": tid, "title": clip(title, 160), "assignee": assignee or "?",
                            "kind": kind or "", "cat": cat, "ageDays": age_d, "stale": age_d >= STALE_DAYS,
                            "since": since, "recurrences": rec, "reason": clip(reason, 400),
                            "body": clip((body or "").strip(), 500),
                            "comment": ({"author": cm[0], "text": clip(cm[1], 400), "ts": cm[2]} if cm else None),
                            "openParents": open_parents, "actions": ALLOWED[cat],
                            "remote": (assignee or "") in remote})
            con.close()
        except Exception as exc:
            errors.append(f"{board}: {str(exc)[:80]}")
    out.sort(key=lambda b: (CAT_ORDER[b["cat"]], -b["ageDays"]))
    return out, errors


# ---------------------------------------------------------------- reactor (GPU + LLM serving)
def http_json(url: str, timeout: float = 4.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def prom(q: str) -> list:
    base = CFG["gpu"]["prometheus_url"].rstrip("/")
    if not base:
        return []
    try:
        d = http_json(f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": q}))
        return d.get("data", {}).get("result", [])
    except Exception:
        return []


def read_reactor() -> dict | None:
    g = CFG["gpu"]
    if not g["prometheus_url"] and not g["model_endpoint"]:
        return None
    nodes: dict[str, dict] = {}
    for r in prom("avg by (instance)(DCGM_FI_DEV_GPU_UTIL)"):
        nodes.setdefault(r["metric"].get("instance"), {})["util"] = round(float(r["value"][1]))
    for r in prom("avg by (instance)(DCGM_FI_DEV_POWER_USAGE)"):
        nodes.setdefault(r["metric"].get("instance"), {})["power"] = round(float(r["value"][1]))
    model = None
    if g["model_endpoint"]:
        try:
            model = http_json(g["model_endpoint"].rstrip("/") + "/v1/models")["data"][0]["id"]
        except Exception:
            pass

    def one(q: str):
        r = prom(q)
        try:
            return float(r[0]["value"][1]) if r else None
        except Exception:
            return None

    p = re.sub(r"[^a-zA-Z0-9_]", "", g["metrics_prefix"]) or "vllm"
    srv = {
        "decodeTps": one(f"sum(rate({p}:generation_tokens_total[5m]))"),
        "prefillTps": one(f"sum(rate({p}:prompt_tokens_total[5m]))"),
        "running": one(f"sum({p}:num_requests_running)"),
        "waiting": one(f"sum({p}:num_requests_waiting)"),
        "kv": one(f"max({p}:kv_cache_usage_ratio)"),
        "specAccept": one(f"sum(rate({p}:mtp_accepted_total[15m])) / sum(rate({p}:mtp_drafted_total[15m]))"),
        "ttftP50": one(f"histogram_quantile(0.5, sum by (le)(rate({p}:time_to_first_token_seconds_bucket[15m])))"),
        "pairBroken": one(f"max({p}:pair_broken)"),      # multi-node pair health (TensorFold); None elsewhere
        "pairStalled": one(f"max({p}:pair_stalled)"),
    }
    if srv["kv"] is None:
        srv["kv"] = one(f"max({p}:kv_cache_usage_perc)") or one(f"max({p}:gpu_cache_usage_perc)")
    if srv["kv"] is not None and srv["kv"] > 1:
        srv["kv"] = srv["kv"] / 100
    if srv["specAccept"] is None:
        srv["specAccept"] = one(f"sum(rate({p}:spec_decode_num_accepted_tokens_total[15m])) / "
                                f"sum(rate({p}:spec_decode_num_draft_tokens_total[15m]))")
    alias = g["node_aliases"] or {}
    return {"nodes": [{"id": alias.get(k, k), **v} for k, v in sorted(nodes.items())], "model": model,
            "engine": p, "srv": srv if any(v is not None for v in srv.values()) else None}


# ---------------------------------------------------------------- assemble
def achievements(b: dict) -> list:
    a = []
    tot = b["p"] + b["r"] + b["f"]
    if b["p"] >= 100:
        a.append(["Centurion", "100+ passed reviews", "good"])
    if b["p"] >= 5 and b["r"] == 0 and b["f"] == 0:
        a.append(["Clean record", f"{b['p']} pass, no revise/fail", "good"])
    if b["summons"] >= 50:
        a.append(["Summoner", f"{b['summons']} sub-agents/helpers reviewed", "good"])
    if b["hallu7d"]:
        a.append(["Mirage", f"{b['hallu7d']}× hallucinated references (7 d)", "bad"])
    if b["blocked"] >= 5:
        a.append(["Gridlock", f"{b['blocked']} blocked quests", "bad"])
    if tot and b["hp"] is not None and b["hp"] < 60:
        a.append(["Battered", f"HP {b['hp']} %", "bad"])
    return a


def _color_for(name: str) -> str:
    h = sum(ord(c) * (i + 7) for i, c in enumerate(name)) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.55, 0.28)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


def roster_bots(profiles: dict) -> list:
    """Roster entries plus any profile not listed (auto-filed into the main room's first zone)."""
    bots = [dict(b) for b in ROSTER["bots"]]
    known = {b["id"] for b in bots}
    rooms = ROSTER["rooms"]
    main = next((r for r in rooms if r.get("main")), rooms[0] if rooms else None)
    zone = main["zones"][0]["id"] if main and main.get("zones") else "ops"
    for name in sorted(profiles):
        if name not in known:
            bots.append({"id": name, "cls": "profile (not in roster)", "title": "Recruit", "zone": zone,
                         "loc": "", "color": _color_for(name), "auto": True})
    return bots


def collect() -> dict:
    t0 = time.time()
    ledger, qc_recent = read_ledger()
    profiles = read_profiles()
    quests, kevents = read_kanban()
    hallu = collections.Counter(e["bot"] for e in kevents if e["kind"] == "suspected_hallucinated_references")
    now = time.time()
    bots = []
    for r in roster_bots(profiles):
        bid = r["id"]
        s = ledger.get(bid, {"own": collections.Counter(), "sum": collections.Counter(), "dims": [], "last": 0})
        own, summ = s["own"], s["sum"]
        p, rv, f = own["pass"] + summ["pass"], own["revise"] + summ["revise"], own["fail"] + summ["fail"]

        def score(c):
            return max(0, XP["pass"] * c["pass"] + XP["revise"] * c["revise"] + XP["fail"] * c["fail"])

        xp_own, xp_sum = score(own), score(summ)
        xp = xp_own + xp_sum
        lvl, pct = level_of(xp)
        tot = p + rv + f
        dims = s["dims"]
        attrs = [round(sum(d[i] for d in dims) / len(dims), 1) if dims else None for i in range(4)]
        prof = profiles.get(bid, {})
        st = read_state(bid) if not r.get("remote") else {}
        qs = sorted(quests.get(bid, []),
                    key=lambda q: ({"running": 0, "review": 1, "blocked": 2}.get(q["status"], 3), -q["prio"]))
        running = [q for q in qs if q["status"] == "running"]
        blocked = [q for q in qs if q["status"] == "blocked"]
        last = st.get("last_activity")
        active = bool(st.get("active")) or bool(last and now - last < ACTIVE_WINDOW_S)
        if running or active:
            status = "running"
        elif blocked:
            status = "blocked"
        elif prof.get("gateway") and prof["gateway"] != "running":
            status = "offline"
        else:
            status = "idle"
        if running:
            quest = running[0]["title"]
        elif active and st.get("last_title"):
            quest = clip(st["last_title"], 140)
        elif blocked:
            quest = blocked[0]["title"]
        else:
            quest = ""
        b = dict(r, model=prof.get("model") or ("remote" if r.get("remote") else "?"),
                 gateway=prof.get("gateway"), status=status, quest=quest,
                 quests=qs[:12], openQuests=len(qs), blocked=len(blocked),
                 xp=xp, xpOwn=xp_own, xpSummon=xp_sum, lvl=lvl, xpPct=pct,
                 hp=round(100 * p / tot) if tot else None,
                 p=p, r=rv, f=f, n=tot,
                 own=[own["pass"], own["revise"], own["fail"]],
                 summ=[summ["pass"], summ["revise"], summ["fail"]],
                 summons=sum(summ.values()), subSessions=st.get("subagent_sessions", 0),
                 sessions7d=st.get("sessions_7d"), attrs=attrs,
                 lastActivity=last, lastQc=s["last"] or None, hallu7d=hallu.get(bid, 0))
        b["achievements"] = achievements(b)
        bots.append(b)
    blockers, berrs = read_blockers()
    known = {b["id"] for b in bots}
    events = [e for e in (qc_recent + kevents) if e["bot"] in known]
    events.sort(key=lambda e: e["ts"], reverse=True)
    return {"generated": now, "bots": bots, "reactor": read_reactor(), "events": events[:40],
            "blockers": blockers, "boardErrors": berrs,
            "unassigned": {k: len(v) for k, v in quests.items() if k not in known},
            "cfg": cfgmod.public(CFG, ROSTER), "collectMs": round(1000 * (time.time() - t0))}


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=1))
