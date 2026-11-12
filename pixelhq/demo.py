#!/usr/bin/env python3
"""Synthetic snapshot for screenshots and for trying the UI without a Hermes fleet.

Deterministic (seeded) data built from roster.example.json — no real sessions, cards or people.
``python3 render.py --demo`` embeds it into dist/pixel-hq.html.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/demo.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from . import config as cfgmod
from .collect import ALLOWED, achievements
from .scoring import level_of

QUESTS = ["Rotate TLS certificates on the edge proxy", "Nightly backup verification report",
          "Upgrade the reverse proxy to the current release", "Review firewall policy drift",
          "Add rate limiting to the public API", "Write the incident post-mortem template",
          "Migrate the wiki database to the new schema", "Audit container images for CVEs",
          "Implement the level editor save/load", "Fix flaky integration test in auth module",
          "Document the on-call runbook", "Benchmark the new embedding model"]
STEPS = ["terminal command running (42s elapsed)", "receiving stream response",
         "delegate_task: subagent running terminal (iteration 12/120)", "tool running: read_file",
         "sequential tool running (8s): execute_code", "starting new turn"]
TOOLS = [("terminal", "docker compose -f /srv/proxy/compose.yml ps"), ("read_file", "/srv/app/src/auth/session.py"),
         ("search_files", "TODO|FIXME"), ("write_file", "/srv/app/docs/runbook.md"), ("execute_code", "from pathlib import Path")]
REASONS = {"you": ["Waiting for approval: switch the public DNS record to the new proxy?",
                   "Decision needed: keep 30-day or 90-day log retention?",
                   "Sign-off required before the migration window on Saturday"],
           "technical": ["gave_up: worker exited cleanly (rc=0) without calling kanban_complete",
                         "timed_out: elapsed 10804s > limit 10800s", "capability: no SSH access to the storage host"],
           "stale": ["", "last comment: parked until the vendor ships the fix"],
           "unknown": [""]}


def snapshot(seed: int = 7) -> dict:
    rnd = random.Random(seed)
    roster = _demo_roster()
    cfg = cfgmod.DEFAULTS | {"theme_label": "PIXEL HQ"}
    now = time.time()
    bots, events, blockers, live = [], [], [], {}
    boards = ["platform", "website", "security"]
    for i, r in enumerate(roster["bots"]):
        p, rv, f = rnd.randint(0, 60), rnd.randint(0, 6), rnd.randint(0, 2)
        summ = (rnd.randint(50, 300), rnd.randint(0, 8), rnd.randint(0, 3)) if r.get("leader") else (0, 0, 0)
        xp_own = max(0, cfg["xp_pass"] * p + cfg["xp_revise"] * rv + cfg["xp_fail"] * f)
        xp_sum = max(0, cfg["xp_pass"] * summ[0] + cfg["xp_revise"] * summ[1] + cfg["xp_fail"] * summ[2])
        xp = xp_own + xp_sum
        kanban_pass = p // 2
        by_source = {
            "kanban": {"pass": kanban_pass, "revise": 0, "fail": 0},
            "reviews": {"pass": p - kanban_pass + summ[0], "revise": rv + summ[1], "fail": f + summ[2]},
        }
        lvl, pct = level_of(xp)
        tot = p + rv + f + sum(summ)
        status = rnd.choice(["running", "idle", "idle", "blocked"]) if not r.get("remote") else rnd.choice(["idle", "blocked"])
        nblk = rnd.randint(1, 4) if status == "blocked" else 0
        quests = [{"id": f"t_{rnd.randrange(16**8):08x}", "title": rnd.choice(QUESTS), "status": "blocked" if k < nblk else rnd.choice(["ready", "todo"]),
                  "board": rnd.choice(boards), "prio": rnd.randint(0, 3)} for k in range(nblk + rnd.randint(0, 2))]
        if status == "running":
            quests.insert(0, {"id": f"t_{rnd.randrange(16**8):08x}", "title": rnd.choice(QUESTS), "status": "running",
                              "board": rnd.choice(boards), "prio": 2})
        b = dict(r, model=rnd.choice(["local/llm-34b", "vendor/model-large", "vendor/model-small"]), gateway="running",
                 status=status, quest=quests[0]["title"] if quests else "", quests=quests, openQuests=len(quests),
                 blocked=nblk, xp=xp, xpOwn=xp_own, xpSummon=xp_sum, lvl=lvl, xpPct=pct,
                 xpBySource={source: sum(counts[v] * cfg["xp_" + v] for v in ("pass", "revise", "fail"))
                             for source, counts in by_source.items()},
                 bySource=by_source, selfReviews=0, attrsSource="reviews",
                 hp=round(100 * (p + summ[0]) / tot) if tot else None, p=p + summ[0], r=rv + summ[1], f=f + summ[2], n=tot,
                 own=[p, rv, f], summ=list(summ), summons=sum(summ), subSessions=summ[0] // 3,
                 sessions7d=rnd.randint(2, 40), attrs=[round(rnd.uniform(3.6, 4.9), 1) for _ in range(4)],
                 lastActivity=now - rnd.randint(60, 3 * 86400), lastQc=now - rnd.randint(3600, 5 * 86400), hallu7d=0)
        b["achievements"] = achievements(b)
        bots.append(b)
        for q in quests:
            if q["status"] == "blocked":
                cat = rnd.choice(["you", "technical", "stale", "unknown", "upstream"])
                age = rnd.randint(1, 30) if cat != "stale" else rnd.randint(15, 60)
                blockers.append({"board": q["board"], "id": q["id"], "title": q["title"], "assignee": r["id"], "kind": "needs_input" if cat == "you" else "",
                                 "cat": cat, "ageDays": age, "stale": age >= 14, "since": now - age * 86400, "recurrences": 0,
                                 "reason": rnd.choice(REASONS.get(cat, [""])), "body": "Acceptance criteria: see the linked spec. Report evidence with timestamps.",
                                 "comment": {"author": r["id"], "text": "Work is done and verified; waiting for the gate.", "ts": now - 3600 * rnd.randint(1, 48)} if cat == "you" else None,
                                 "openParents": [{"id": f"t_{rnd.randrange(16**8):08x}", "title": rnd.choice(QUESTS), "status": "blocked"}] if cat == "upstream" else [],
                                 "actions": ALLOWED[cat], "remote": bool(r.get("remote"))})
        for _ in range(rnd.randint(1, 3)):
            kind = rnd.choice(["qc-pass", "qc-pass", "qc-pass", "qc-revise", "completed", "created", "blocked", "changes_requested"])
            events.append({"ts": now - rnd.randint(300, 6 * 86400), "bot": r["id"], "kind": kind, "summon": kind.startswith("qc") and bool(r.get("leader")) and rnd.random() < .6,
                           "source": "ui" if kind.startswith("qc") else "kanban", "selfReview": False,
                           "text": rnd.choice(QUESTS) + (f" [{rnd.choice(boards)}/t_{rnd.randrange(16**8):08x}]" if not kind.startswith("qc") else "")})
        sessions = []
        if status == "running":
            for k in range(rnd.randint(1, 2)):
                tool = rnd.choice(TOOLS)
                s = {"id": f"s{i}{k}", "title": rnd.choice(QUESTS), "source": rnd.choice(["desktop", "kanban"]), "startedAt": now - rnd.randint(120, 7200),
                     "lastAt": now - rnd.randint(2, 60), "step": rnd.choice(STEPS), "stale": False, "parent": None,
                     "tool": {"name": tool[0], "arg": tool[1], "ts": now - rnd.randint(5, 90), "n": 1}, "inTok": rnd.randint(20000, 900000),
                     "outTok": rnd.randint(2000, 60000), "cost": round(rnd.uniform(0.2, 12), 3), "msgs": rnd.randint(10, 300), "toolCalls": rnd.randint(5, 120), "model": b["model"]}
                if r.get("leader") and k == 0:
                    s["children"] = [{"id": "sub1", "title": "Subagent: verify the backup restore on the staging host", "source": "desktop", "startedAt": now - 600,
                                      "lastAt": now - 8, "step": "terminal command running (31s elapsed)", "stale": False, "tool": {"name": "terminal", "arg": "restic snapshots --latest 1", "ts": now - 31, "n": 1},
                                      "inTok": 40000, "outTok": 3000, "cost": 0.41, "msgs": 22, "toolCalls": 9, "model": b["model"]}]
                sessions.append(s)
        tasks = [{"board": q["board"], "id": q["id"], "title": q["title"], "startedAt": now - 1500, "heartbeatAt": now - 20, "heartbeatAge": 20, "pid": 4242}
                 for q in quests if q["status"] == "running"]
        live[r["id"]] = {"active": status == "running", "sessions": sessions, "tasks": tasks,
                         "last": None if status == "running" else {"at": b["lastActivity"], "title": rnd.choice(QUESTS), "step": "", "source": "desktop"},
                         "error": None, "remote": bool(r.get("remote"))}
    _pin_floor_numbers(bots, blockers, live, now)
    events.sort(key=lambda e: e["ts"], reverse=True)
    order = {"you": 0, "technical": 1, "stale": 2, "unknown": 3, "upstream": 4}
    blockers.sort(key=lambda x: (order[x["cat"]], -x["ageDays"]))
    reactor = _reactor()
    return {"generated": now, "bots": bots, "reactor": reactor, "events": events[:40], "blockers": blockers, "boardErrors": [], "warnings": [],
            "unassigned": {}, "cfg": cfgmod.public(cfg, roster) | {"toolsDir": "<pixel-hq>/pixelhq"}, "collectMs": 12, "demo": True,
            "live": {"generated": now, "ms": 3, "bots": live, "unassignedTasks": {}}, "demoProfiles": _demo_profiles(roster)}


# The Office floor shows members / active / blocked / average HP / XP per department. Whatever the seed draws, these bots are
# pinned so that the ops and lab departments of the example roster always have non-trivial numbers (two or more members,
# at least one working, at least one blocked card, HP values, XP): two bots work, two bots own a blocked card.
FLOOR_WORKING = ("devops", "dev-a")
FLOOR_CARDS = ("netadmin", "dev-a")


def _pin_floor_numbers(bots: list, blockers: list, live: dict, now: float) -> None:
    for b in bots:
        stem = f"t_{_stable_number(b['id']) % 16**8:08x}"
        card = f"t_{_stable_number(b['id'] + '/card') % 16**8:08x}"
        title = QUESTS[len(b["id"]) % len(QUESTS)]
        if b["id"] in FLOOR_WORKING and b["status"] != "running":
            b.update(status="running", quests=[{"id": stem, "title": title, "status": "running", "board": "platform", "prio": 2}] + b["quests"])
            live[b["id"]].update(active=True, last=None, tasks=[{"board": "platform", "id": stem, "title": title, "startedAt": now - 1500,
                                                                "heartbeatAt": now - 20, "heartbeatAge": 20, "pid": 4242}])
        if b["id"] in FLOOR_CARDS and not any(c["assignee"] == b["id"] for c in blockers):
            b.update(status=b["status"] if b["status"] == "running" else "blocked", blocked=b["blocked"] + 1,
                     quests=b["quests"] + [{"id": card, "title": title, "status": "blocked", "board": "platform", "prio": 2}])
            blockers.append({"board": "platform", "id": card, "title": title, "assignee": b["id"], "kind": "", "cat": "technical",
                             "ageDays": 3, "stale": False, "since": now - 3 * 86400, "recurrences": 0, "reason": REASONS["technical"][0],
                             "body": "Acceptance criteria: see the linked spec.", "comment": None, "openParents": [],
                             "actions": ALLOWED["technical"], "remote": False})
        b.update(openQuests=len(b["quests"]), quest=b["quests"][0]["title"] if b["quests"] else "")
    _mark_stale_session(live, now)


SKILL_POOL = ["web-search", "file-ops", "code-review", "summarise", "shell-safe", "diff-reader", "docs-writer", "log-triage",
              "metrics-query", "backup-check", "tls-audit", "port-scan", "dns-tools", "git-flow", "test-runner", "release-notes"]
MESSAGING_SECTION = ("## Messaging other agents\n\nUse the message tool to ask a teammate for help. Keep requests short and name the "
                     "card they concern.\n")


def _demo_profiles(roster: dict) -> dict:
    """Synthetic ``profiles.describe`` answers for the standalone demo (read-only panel; no real profile is read)."""
    out = {}
    for i, bot in enumerate(roster["bots"]):
        leader = bool(bot.get("leader"))  # the leader shows the "+N more" collapse: 13 of 16 skills are switched off
        skills = [{"name": name, "enabled": k < 3 if leader else (k + i) % 5 != 3}
                  for k, name in enumerate(SKILL_POOL[: 16 if leader else 4 + i % 4])]
        soul = (f"You are {bot['id']}, a sample {bot['cls']} bot.\n\n## Working style\n\n- Check the facts before you answer.\n"
                "- Report what you did, with evidence.\n- Ask one clear question when something is unclear.\n")
        toolsets = [{"name": name, "enabled": k != 2 or i % 2 == 0} for k, name in enumerate(["files", "terminal", "web"])]
        servers = [{"name": "docs", "transport": "stdio", "enabled": True}, {"name": "tickets", "transport": "http", "enabled": i % 2 == 0}]
        out[bot["id"]] = {
            "name": bot["id"], "description": f"{bot['cls']} (synthetic demo profile)",
            "soul": soul + ("\n" + MESSAGING_SECTION if i % 2 == 0 else ""),
            "model": {"provider": "sample-provider", "default": ["local/llm-34b", "vendor/model-large"][i % 2]},
            "skills": skills, "toolsets": toolsets, "toolsets_pinned": i % 3 == 0, "mcp_servers": servers[: 1 + i % 2]}
    return out


def _stable_number(text: str) -> int:
    """A stable number from a string (the builtin hash() changes per process)."""
    return sum(ord(ch) * 31 ** i for i, ch in enumerate(text))


def _demo_roster() -> dict:
    roster = json.loads(Path(__file__).with_name("roster.example.json").read_text(encoding="utf-8"))
    # Explicit overrides demonstrate roles that are not inferred from profile ids.
    variants = {"dev-b": "scribe", "trial-model": "rogue", "remote-ops": "medic"}
    for bot in roster["bots"]:
        if bot["id"] in variants:
            bot.setdefault("sprite", variants[bot["id"]])
    return roster


def _mark_stale_session(live: dict, now: float) -> None:
    session = next((s for bot in live.values() for s in bot["sessions"]), None)
    if session is not None:
        session.update(stale=True, lastAt=now - 900)


def _reactor() -> dict:
    return {"nodes": [{"id": "GPU1", "util": 91, "power": 310}, {"id": "GPU2", "util": 88, "power": 298}], "model": "example/llm-34b-instruct",
            "engine": "vllm", "srv": {"decodeTps": 143.2, "prefillTps": 9100.0, "running": 3.0, "waiting": 0.0, "kv": 0.27,
                                      "specAccept": 0.71, "ttftP50": 0.9, "pairBroken": None, "pairStalled": None}}


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=False, indent=1))
