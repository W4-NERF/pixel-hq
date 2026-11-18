"""Merge the remote documents into the snapshot (round 5 §2). Read-only, and never a source for any prompt.

Remote bots are keyed ``<source>/<id>`` everywhere (so a remote ``default`` never meets a local one), remote blockers
and boards carry their ``source``. They are returned in their own lists: the snapshot's ``blockers`` stay local, which
is what the triage selection, its briefing and every other prompt are built from.
"""
from __future__ import annotations

import collections
from collections.abc import Callable

from . import remote, scoring
from .blockers import CAT_ORDER
from .common import clip

ZERO_COUNTS = {"pass": 0, "revise": 0, "fail": 0}
MAX_DOC_WARNINGS = 3  # per source; the rest stays in the document


def _status(doc_status: str, stale: bool) -> str:
    """The office statuses; a stale document never shows a bot as working, an unknown one is not claimed to be idle."""
    if doc_status == "unknown":
        return "offline"
    return "idle" if stale and doc_status == "running" else doc_status


def _bot(entry: dict, key: str, doc: dict | None, info: dict, blocked: int = 0) -> dict:
    """One snapshot bot of another host. ``doc`` is None for a roster entry that its source delivered nothing for."""
    doc = doc or {}
    xp = doc.get("xp", 0)
    stale = info["stale"] or not doc
    return dict(
        entry, id=key, name=key.partition("/")[2], source=info["source"], remote=True,
        model=doc.get("model") or "remote", gateway=None, status=_status(doc.get("status", "unknown"), stale),
        remoteStatus=doc.get("status", "unknown"), quest=doc.get("quest", ""), currentStep=doc.get("currentStep", ""),
        lastTool=doc.get("lastTool", ""), quests=[], openQuests=blocked, blocked=blocked,
        xp=xp, xpOwn=xp, xpSummon=0, lvl=doc.get("level", 1), xpPct=scoring.level_of(xp)[1],
        xpBySource={"kanban": 0, "reviews": 0}, bySource={"kanban": dict(ZERO_COUNTS), "reviews": dict(ZERO_COUNTS)},
        selfReviews=0, attrs=[None] * 4, attrsSource=None, hp=doc.get("hp"), p=0, r=0, f=0, n=0,
        own=[0, 0, 0], summ=[0, 0, 0], summons=0, subSessions=0, sessions7d=None,
        lastActivity=doc.get("lastActive"), lastQc=None, hallu7d=0, achievements=[],
        asOf=info["observed"], stale=stale, sourceState=info["state"])


class Matcher:
    """Roster entry of a remote bot: ``source`` + id exactly; else a ``remote`` entry without ``source`` whose id is
    present in exactly one source. An entry that names a source is only ever matched by the first rule."""

    def __init__(self, roster_data: dict, local: list, live: list[remote.Source]):
        self.exact = {(e["source"], e["id"]): e for e in roster_data["bots"] if e.get("source")}
        self.loose = {e["id"]: e for e in local if e.get("remote") and not e.get("source")}
        self.counts = collections.Counter(bot["id"] for src in live for bot in src.doc["bots"])
        self.consumed: set[str] = set()  # ids of the loose entries a document replaced

    def find(self, label: str, rid: str) -> dict | None:
        entry = self.exact.get((label, rid))
        if entry is None and self.counts[rid] == 1 and rid in self.loose:
            entry = self.loose[rid]
            self.consumed.add(rid)
        return entry


def _blocker(src: remote.Source, card: dict, info: dict, stale_days: int, ids: set) -> dict:
    return {"source": src.label, "board": card["board"], "id": card["id"],
            "key": f"{src.label}/{card['board']}/{card['id']}", "title": card["title"], "cat": card["category"],
            "assignee": card["assignee"], "bot": f"{src.label}/{card['assignee']}" if card["assignee"] in ids else None,
            "ageDays": card["ageDays"], "stale": card["ageDays"] >= stale_days, "kind": "", "reason": card["reason"],
            "actions": [], "remote": True, "asOf": info["observed"], "sourceStale": info["stale"]}


def _source_bots(src: remote.Source, info: dict, matcher: Matcher, recruit: Callable, warnings: list[str]) -> list[dict]:
    blocked = collections.Counter(card["assignee"] for card in src.doc["blockers"])
    bots = []
    for doc in src.doc["bots"]:
        key = f"{src.label}/{doc['id']}"
        entry = matcher.find(src.label, doc["id"]) or recruit(key, doc.get("cls", ""), warnings)
        if entry is not None:
            bots.append(_bot(entry, key, doc, info, blocked[doc["id"]]))
    return bots


def _placeholders(matcher: Matcher, bots: list[dict], infos: dict) -> list[dict]:
    """Roster entries that name a source but got nothing from it: kept, shown as offline, without data."""
    taken = {bot["id"] for bot in bots}
    out = []
    for (label, rid), entry in sorted(matcher.exact.items()):
        key = f"{label}/{rid}"
        if key not in taken:
            info = infos.get(label) or {"source": label, "state": "unconfigured", "stale": True, "observed": None}
            out.append(_bot(entry, key, None, info))
    return out


def merge(sources: list[remote.Source], roster_data: dict, local: list, *, recruit: Callable, stale_days: int,
          stale_after: int, now: float, warnings: list[str]) -> dict:
    """Remote bots, blockers, boards and the footer status of every source.

    ``recruit(key, role, warnings)`` is the collector's recruit rule for a bot without a roster entry (``None``: no
    department to put it in). ``consumed`` lists the ids of the local ``remote: true`` placeholder entries that a
    document replaced; the caller drops them from its own roster.
    """
    statuses = [remote.status(src, now, stale_after) for src in sources]
    infos = {src.label: {"source": src.label, "state": st["state"], "stale": st["state"] != "ok", "observed": src.observed}
             for src, st in zip(sources, statuses, strict=True)}
    live = [src for src in sources if src.doc]
    matcher = Matcher(roster_data, local, live)
    bots, blockers, boards = [], [], []
    for src in live:
        info = infos[src.label]
        bots.extend(_source_bots(src, info, matcher, recruit, warnings))
        ids = {bot["id"] for bot in src.doc["bots"]}
        blockers.extend(_blocker(src, card, info, stale_days, ids) for card in src.doc["blockers"])
        boards.extend({"source": src.label, "key": f"{src.label}/{b['slug']}", "asOf": info["observed"], **b}
                      for b in src.doc["boards"])
        warnings.extend(clip(f"{src.label}: {text}", 120) for text in src.doc["warnings"][:MAX_DOC_WARNINGS])
    bots.extend(_placeholders(matcher, bots, infos))
    order = {src.label: index for index, src in enumerate(live)}
    blockers.sort(key=lambda card: (order[card["source"]], CAT_ORDER[card["cat"]], -card["ageDays"]))
    return {"bots": bots, "blockers": blockers, "boards": boards, "sources": statuses, "consumed": matcher.consumed}
