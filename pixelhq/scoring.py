"""Stateless scoring from read-only Kanban outcomes and optional reviews."""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from . import common, dbutil
from .common import clip

VERDICTS = ("pass", "revise", "fail")
OUTCOMES = {
    "completed": "pass", "changes_requested": "revise", "gave_up": "fail",
    "timed_out": "fail", "suspected_hallucinated_references": "fail",
}
LOG_KINDS = frozenset((*OUTCOMES, "blocked", "protocol_violation", "created"))
OPEN_STATUSES = frozenset(("running", "blocked", "ready", "todo", "review", "scheduled"))


class Score(TypedDict):
    xp: int
    xpOwn: int
    xpSummon: int
    xpBySource: dict[str, int]
    lvl: int
    xpPct: int
    hp: int | None
    p: int
    r: int
    f: int
    n: int
    own: list[int]
    summ: list[int]
    bySource: dict[str, dict[str, int]]
    selfReviews: int
    attrs: list[float | None]
    attrsSource: str | None


def level_of(xp: int) -> tuple[int, int]:
    xp = max(0, xp)
    level = 1 + math.isqrt(xp // 25)
    lo, hi = 25 * (level - 1) ** 2, 25 * level ** 2
    return level, round(100 * (xp - lo) / (hi - lo))


@dataclass
class KanbanIndex:
    """One scan per board, shared by every bot in a snapshot (never a persistent cache)."""

    by_bot: dict[str, collections.Counter] = field(default_factory=lambda: collections.defaultdict(collections.Counter))
    events: list[dict] = field(default_factory=list)
    quests: dict[str, list[dict]] = field(default_factory=lambda: collections.defaultdict(list))
    warnings: list[str] = field(default_factory=list)
    _seen: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _boards: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def from_boards(cls, boards, cfg) -> KanbanIndex:
        index = cls()
        for board, path in common.boards(cfg, boards):
            index.add_board(board, path)
        index.events.sort(key=lambda e: e["ts"], reverse=True)
        return index

    def add_board(self, board: str, path: Path) -> None:
        if board in self._boards:
            return
        self._boards.add(board)
        try:
            with contextlib.closing(dbutil.ro(path)) as con:
                tasks = {}
                for tid, title, bot, status, priority in dbutil.rows(
                    con, "tasks", ["id", "title", "assignee", "status", "priority"],
                    warnings=self.warnings, source=board,
                ):
                    bot = bot or "?"
                    tasks[tid] = (bot, title)
                    if status in OPEN_STATUSES:
                        self.quests[bot].append({"id": tid, "title": clip(title, 140), "status": status,
                                                 "board": board, "prio": priority or 0})
                for eid, tid, kind, ts in dbutil.rows(
                    con, "task_events", ["id", "task_id", "kind", "created_at"], warnings=self.warnings, source=board,
                ):
                    if eid is None:
                        dbutil.warning(self.warnings, f"{board}/task_events", "missing event id; skipped unidentifiable events")
                        continue
                    key = (board, eid)
                    if key in self._seen or tid not in tasks:
                        continue
                    self._seen.add(key)
                    bot, title = tasks[tid]
                    counter = self.by_bot[bot]
                    counter[kind] += 1
                    if kind == "claimed":
                        counter["runs"] += 1
                    elif kind == "suspected_hallucinated_references":
                        counter["mirage"] += 1
                    if kind in LOG_KINDS:
                        self.events.append({"ts": float(ts or 0), "bot": bot, "kind": kind,
                                            "board": board, "id": eid,
                                            "text": clip(f"{clip(title, 90)} [{board}/{tid}]", 180)})
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self.warnings.append(clip(f"{board}: {exc}", 120))


DIMENSIONS = ("correctness", "completeness", "format", "safety")


def _dims(record: dict) -> dict[str, float]:
    raw = record.get("dims") or record.get("scores") or record
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in DIMENSIONS:
        value = raw.get(name)
        if isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(number) and 1 <= number <= 5:
            out[name] = number
    return out


def parse_reviews(paths) -> tuple[list[dict], list[str]]:
    """Normalize optional JSONL sources, reading each resolved path at most once.

    Old ledgers used ``scores`` or flat dimension keys and ``task`` instead of ``ref``.
    A record without a source is legacy; bad JSON/record lines produce short warnings,
    while unknown verdicts and missing files are intentionally ignored.
    """
    records, warnings, seen = [], [], set()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            with path.open("rb") as stream:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict) or not isinstance(record.get("agent"), str) or not record["agent"].strip():
                            raise ValueError("invalid review record")
                        if record.get("verdict") not in VERDICTS:
                            continue
                    except (ValueError, UnicodeError, RecursionError):
                        warnings.append(clip(f"{path.name}:{number}: invalid review record", 120))
                        continue
                    source = record.get("source")
                    records.append({
                        "agent": record["agent"].strip(), "verdict": record["verdict"],
                        "ts": clip(record.get("ts"), 80), "dims": _dims(record),
                        "ref": clip(record.get("ref") or record.get("task"), 200),
                        "parent": record.get("parent", ""), "reviewer": record.get("reviewer", ""),
                        "source": source if source in ("ui", "tool", "agent", "legacy") else "legacy",
                    })
        except FileNotFoundError:
            continue
        except OSError as exc:
            warnings.append(clip(f"{path.name}: {type(exc).__name__}", 120))
    return records, warnings


def _kanban_attrs(counter) -> tuple[list, str | None]:
    completed = counter.get("completed", 0)
    if completed < 3:
        return [None] * 4, None
    values = [
        5 - 4 * counter.get("mirage", 0) / max(1, completed),
        1 + 4 * completed / max(1, completed + counter.get("gave_up", 0) + counter.get("timed_out", 0)),
        1 + 4 * (1 - counter.get("protocol_violation", 0) / max(1, counter.get("runs", 0))),
        1 + 4 * (1 - counter.get("changes_requested", 0) / max(1, completed + counter.get("changes_requested", 0))),
    ]
    return [round(min(5, max(1, value)), 1) for value in values], "kanban"


HELPER_RE = re.compile(r"^(subagent|delegate_task|claude-code-cli|opencode|codex)", re.I)


def attribute(agent: str, record: dict, cfg) -> tuple[str | None, bool]:
    """Credit a review to a profile, preferring its explicit spawning parent."""
    parent = record.get("parent")
    if isinstance(parent, str) and parent.strip():
        return parent.strip(), True
    agent = agent.strip() if isinstance(agent, str) else ""
    if not agent or agent == "?":
        return None, False
    orchestrator = cfg.get("orchestrator_profile", "default")
    low = agent.lower()
    if HELPER_RE.match(agent) or low.startswith(("cron:", orchestrator.lower() + "-subagent")):
        return orchestrator, True
    return agent.split("+", 1)[0].strip() or None, False


def _self_review(record: dict) -> bool:
    """Compare identities before helper/parent attribution, not the XP recipient."""
    reviewer = record.get("reviewer")
    return isinstance(reviewer, str) and bool(reviewer) and reviewer == record.get("agent")


def review_events(reviews: list[dict], cfg) -> list[dict]:
    events = []
    for record in reviews:
        bot, summon = attribute(record.get("agent"), record, cfg)
        verdict = record.get("verdict")
        if bot is None or verdict not in VERDICTS:
            continue
        try:
            stamp = dt.datetime.fromisoformat(str(record.get("ts")))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.timezone.utc)
            ts = stamp.timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            ts = 0.0
        events.append({"ts": ts, "bot": bot, "kind": "qc-" + verdict,
                       "summon": summon, "source": record.get("source") or "legacy",
                       "selfReview": _self_review(record),
                       "text": clip(record.get("ref") or record.get("task"), 90)})
    return sorted(events, key=lambda e: e["ts"], reverse=True)


def compute(bots: list[str], kanban: KanbanIndex, reviews: list[dict], cfg) -> dict[str, Score]:
    weights = {v: cfg.get("xp_" + v, cfg.get("xp", {}).get(v, default))
               for v, default in zip(VERDICTS, (10, 3, -5))}

    def raw_xp(counts):
        return sum(weights[v] * counts.get(v, 0) for v in VERDICTS)

    known = set(bots)
    reviewed = collections.defaultdict(lambda: {
        "own": collections.Counter(), "summ": collections.Counter(), "dims": [], "selfReviews": 0,
    })
    for record in reviews:
        bot, summon = attribute(record.get("agent"), record, cfg)
        verdict = record.get("verdict")
        if bot not in known or verdict not in VERDICTS:
            continue
        stats = reviewed[bot]
        if _self_review(record):
            stats["selfReviews"] += 1
            continue
        stats["summ" if summon else "own"][verdict] += 1
        dims = _dims(record)
        if dims:
            stats["dims"].append(dims)

    scores = {}
    for bot in bots:
        counter = kanban.by_bot.get(bot, {}) if cfg.get("kanban_xp", True) else {}
        counts = {v: sum(counter.get(kind, 0) for kind, verdict in OUTCOMES.items() if verdict == v)
                  for v in VERDICTS}
        stats = reviewed[bot]
        own = {v: counts[v] + stats["own"][v] for v in VERDICTS}
        summ = {v: stats["summ"][v] for v in VERDICTS}
        totals = {v: own[v] + summ[v] for v in VERDICTS}
        xp_own, xp_summon = max(0, raw_xp(own)), max(0, raw_xp(summ))
        total_xp = xp_own + xp_summon
        level, pct = level_of(total_xp)
        n = sum(totals.values())
        attrs, attrs_source = _kanban_attrs(counter)
        if stats["dims"]:
            attrs = []
            for name in DIMENSIONS:
                values = [dims[name] for dims in stats["dims"] if name in dims]
                attrs.append(round(sum(values) / len(values), 1) if values else None)
            attrs_source = "reviews"
        scores[bot] = Score(
            xp=total_xp, xpOwn=xp_own, xpSummon=xp_summon,
            xpBySource={"kanban": raw_xp(counts), "reviews": raw_xp(stats["own"]) + raw_xp(summ)},
            lvl=level, xpPct=pct, hp=round(100 * totals["pass"] / n) if n else None,
            p=totals["pass"], r=totals["revise"], f=totals["fail"], n=n,
            own=[own[v] for v in VERDICTS], summ=[summ[v] for v in VERDICTS],
            bySource={"kanban": counts, "reviews": {v: stats["own"][v] + summ[v] for v in VERDICTS}},
            selfReviews=stats["selfReviews"], attrs=attrs, attrsSource=attrs_source,
        )
    return scores
