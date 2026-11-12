#!/usr/bin/env python3
"""Pixel HQ collector — READ-ONLY. Builds one JSON snapshot of the fleet.

Sources
  - Kanban outcomes + reviews (JSONL) → XP / level / HP / attributes
  - profile YAML + gateway.pid     → model + gateway state per profile
  - <profile>/state.db (mode=ro)    → last activity, sub-agent sessions
  - ~/.hermes/kanban/boards/*/kanban.db → quests (open cards), blocked cards, event log
  - Prometheus (DCGM + vLLM-style serving metrics) + an OpenAI-compatible /v1/models → "reactor"

Sub-agents / helpers are credited to the bot that spawned them (review field ``parent``; otherwise the
configured orchestrator profile). All free text coming from cards or reviews is clipped here and escaped
in the UI.
"""
from __future__ import annotations

import collections
import colorsys
import contextlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/collect.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from . import config as cfgmod, dbutil, profiles as profilemod, scoring
from .blockers import ALLOWED, read_blockers
from .common import boards, clip, state_db

ACTIVE_WINDOW_S = 10 * 60
EVENT_WINDOW_S = 7 * 24 * 3600

# ---------------------------------------------------------------- profiles
def context() -> tuple[dict, dict]:
    """Read configuration once per request, never while importing a module."""
    return cfgmod.load(), cfgmod.load_roster()


def read_profiles(warnings: list[str] | None = None, cfg: dict | None = None) -> dict:
    cfg = cfgmod.load() if cfg is None else cfg
    return profilemod.list_profiles(Path(cfg["hermes_home"]), warnings)


def read_state(profile: str, cfg: dict | None = None) -> dict:
    cfg = cfgmod.load() if cfg is None else cfg
    db = state_db(profile, cfg)
    res = {"last_activity": None, "last_title": None, "subagent_sessions": 0, "sessions_7d": 0,
           "active": 0, "warnings": []}
    if not db.exists():
        return res
    try:
        with contextlib.closing(dbutil.ro(db)) as con:
            sessions = dbutil.rows(con, "sessions", ["title", "source", "started_at", "last_activity_at",
                                                    "last_activity_description", "ended_at"],
                                   warnings=res["warnings"], source=profile)
        now = time.time()
        mains = [session for session in sessions if session[1] != "subagent"]
        if mains:
            last = max(mains, key=lambda row: row[3] or row[2] or 0)
            res["last_activity"], res["last_title"] = last[3] or last[2], last[0] or last[4]
        res["subagent_sessions"] = sum(source == "subagent" or (title or "").lower().startswith("subagent:")
                                       for title, source, *_ in sessions)
        res["sessions_7d"] = sum((row[2] or 0) > now - 7 * 86400 for row in sessions)
        res["active"] = sum(row[5] is None and (row[3] or row[2] or 0) > now - ACTIVE_WINDOW_S for row in sessions)
    except Exception as exc:  # a failing profile stays visible without activity
        res["error"] = clip(str(exc), 120)
    return res


# ---------------------------------------------------------------- kanban

def read_kanban(cfg: dict | None = None) -> scoring.KanbanIndex:
    cfg = cfgmod.load() if cfg is None else cfg
    return scoring.KanbanIndex.from_boards(boards(cfg), cfg)


# ---------------------------------------------------------------- reactor (GPU + LLM serving)
def http_json(url: str, timeout: float = 4.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def prom(q: str, cfg: dict) -> list:
    base = cfg["prometheus_url"].rstrip("/")
    if not base:
        return []
    try:
        d = http_json(f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": q}))
        return d.get("data", {}).get("result", [])
    except Exception:
        return []


def read_reactor(cfg: dict | None = None) -> dict | None:
    cfg = cfgmod.load() if cfg is None else cfg
    if not cfg["prometheus_url"] and not cfg["model_endpoint"]:
        return None
    nodes: dict[str, dict] = {}
    for r in prom("avg by (instance)(DCGM_FI_DEV_GPU_UTIL)", cfg):
        nodes.setdefault(r["metric"].get("instance"), {})["util"] = round(float(r["value"][1]))
    for r in prom("avg by (instance)(DCGM_FI_DEV_POWER_USAGE)", cfg):
        nodes.setdefault(r["metric"].get("instance"), {})["power"] = round(float(r["value"][1]))
    model = None
    if cfg["model_endpoint"]:
        try:
            model = http_json(cfg["model_endpoint"].rstrip("/") + "/v1/models")["data"][0]["id"]
        except Exception:
            pass

    def one(q: str):
        r = prom(q, cfg)
        try:
            return float(r[0]["value"][1]) if r else None
        except Exception:
            return None

    p = re.sub(r"[^a-zA-Z0-9_]", "", cfg["metrics_prefix"]) or "vllm"
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
    alias = cfg["node_aliases"] or {}
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


def default_department(rooms: list) -> str | None:
    """Department for a profile that is not in the roster (R3-D1): the first one of the main room, else the first
    in file order (rooms in order, departments in order). Never an id that does not exist; None without departments."""
    found = cfgmod.departments(rooms)
    in_main = [zone for room, zone in found if room.get("main")]
    ordered = in_main or [zone for _room, zone in found]
    return ordered[0]["id"] if ordered else None


def roster_bots(profiles: dict, warnings: list[str] | None = None, *,
                roster: dict | None = None, cfg: dict | None = None) -> list:
    """Keep real/remote entries and auto-recruit local profiles missing from the roster."""
    roster = cfgmod.load_roster() if roster is None else roster
    cfg = cfgmod.load() if cfg is None else cfg
    warnings = warnings if warnings is not None else []
    bots = []
    for bot in roster["bots"]:
        if bot["id"] in profiles or bot.get("remote"):
            bots.append(dict(bot))
        else:
            warnings.append(clip(f"roster: dropped nonexistent profile {bot['id']}", 120))
    known = {b["id"] for b in bots}
    rooms = roster["rooms"]
    zone = default_department(rooms)
    generated = roster.get("rosterSource") == "generated"
    for name in sorted(profiles):
        if name not in known:
            if not generated and zone is None:
                warnings.append(clip(f"roster: no department for new profile {name}", 120))
                continue
            leader = generated and name == cfg["orchestrator_profile"]
            role = "".join(ch for ch in " ".join(str(profiles[name].get("description") or "").split())
                           if not cfgmod.text_rejected(ch))
            bots.append({"id": name, "cls": clip(role, 40) or "Hermes profile",
                         "title": "Recruit", "zone": ("command" if leader else "crew") if generated else zone,
                         **({"leader": True} if leader else {}),
                         "loc": "", "color": _color_for(name), "auto": True})
    return bots


def collect() -> dict:
    t0 = time.time()
    cfg, roster_data = context()
    reviews, warnings = scoring.parse_reviews([cfg["reviews_path"], cfg["legacy_ledger_path"]])
    warnings.extend(cfg.get("warnings", []))
    warnings.extend(roster_data.get("warnings", []))
    qc_recent = scoring.review_events(reviews, cfg)
    last_qc = {}
    for event in qc_recent:
        if not event["selfReview"]:
            last_qc[event["bot"]] = max(last_qc.get(event["bot"], 0), event["ts"])
    profiles = read_profiles(warnings, cfg)
    kanban = read_kanban(cfg)
    quests = kanban.quests
    since = time.time() - EVENT_WINDOW_S
    kevents = kanban.events
    warnings.extend(kanban.warnings)
    roster = roster_bots(profiles, warnings, roster=roster_data, cfg=cfg)
    scores = scoring.compute([bot["id"] for bot in roster], kanban, reviews, cfg)
    hallu = collections.Counter(e["bot"] for e in kevents
                                if e["kind"] == "suspected_hallucinated_references" and e["ts"] > since)
    now = time.time()
    bots = []
    for r in roster:
        bid = r["id"]
        score = scores[bid]
        prof = {} if r.get("remote") else profiles.get(bid, {})
        st = read_state(bid, cfg) if not r.get("remote") else {}
        warnings.extend(st.get("warnings", []))
        if st.get("error"):
            warnings.append(clip(f"{bid}: {st['error']}", 120))
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
                 **score, summons=sum(score["summ"]), subSessions=st.get("subagent_sessions", 0),
                 sessions7d=st.get("sessions_7d"),
                 lastActivity=last, lastQc=last_qc.get(bid) or None, hallu7d=hallu.get(bid, 0))
        b["achievements"] = achievements(b)
        bots.append(b)
    blockers, berrs = read_blockers(cfg, roster_data)
    warnings.extend(clip(error, 120) for error in berrs)
    known = {b["id"] for b in bots}
    events = [e for e in (qc_recent + kevents) if e["bot"] in known]
    events.sort(key=lambda e: e["ts"], reverse=True)
    return {"generated": now, "bots": bots, "reactor": read_reactor(cfg), "events": events[:40],
            "blockers": blockers, "boardErrors": berrs, "warnings": warnings,
            "unassigned": {k: len(v) for k, v in quests.items() if k not in known},
            "cfg": cfgmod.public(cfg, roster_data), "collectMs": round(1000 * (time.time() - t0))}


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=1))
