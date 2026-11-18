#!/usr/bin/env python3
"""Pixel HQ exporter — READ-ONLY. Prints one ``pixelhq-remote/1`` JSON document describing this host.

A remote Pixel HQ runs this program through an SSH forced command and shows the bots, blocked Kanban cards and
board counts of this host next to its own. Usage::

    python3 -B /path/to/pixelhq/export.py [--home PATH[=NAME[,NAME...]]]... [--kanban-db PATH]... [--label NAME]
                                          [--include-tool-args]

``--home PATH=NAME[,NAME...]`` reads only the listed profiles of that home (split on the last ``=``; each NAME follows
the profile-name rule, an unknown NAME is a warning). Every home has a root ``default`` profile: on a server with one
account per bot, list the wanted profiles so the unused root ``default`` is neither exported nor reported as a duplicate.
Plain ``--home PATH`` reads every profile of the home.

stdout carries the document and the exit code is 0; every error goes to stderr with exit code 1. Nothing is
written: no cache, no plugin data, no log. Every SQLite file is opened with ``mode=ro``, and ``immutable=1`` when it
has no ``-wal``/``-shm`` file (a plain read-only open of a WAL database would create them). The supported entry point
is the script with ``-B``; ``python3 -B -m pixelhq.export`` is equivalent. Without ``-B``, ``-m`` imports the package
before this module can stop bytecode writing, so Python may write ``.pyc`` files (accepted, documented in the README).
Profiles, activity, XP and blocked cards come from the collector's own readers, once per home.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True  # a library import (the Hermes backend) must not change this process
if __name__ == "__main__" and not __package__:  # run as a script: python3 pixelhq/export.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "pixelhq"
from . import config as cfgmod
from . import dbutil, live, remote_schema, scoring
from . import profiles as profilemod
from .blockers import CAT_ORDER, read_blockers
from .common import boards, state_db
from .remote_schema import clean_text

BOARD_FALLBACK = "board"
PATH_RE = re.compile(r"(?<![\w.-])(?:/[\w.@+~ -]+)+|[A-Za-z]:[\\/][^\s'\"]+")
LIST_ORDER = ("blockers", "bots", "boards")  # truncated in this order when the document is too large
DAY_S = 86400
NO_ROSTER = {"bots": []}


class ExportError(Exception):
    """A usage or input error: printed to stderr, exit code 1."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExportError(message)


@dataclass
class HomeArg:
    """One ``--home`` value: the directory and, optionally, the only profiles to read from it."""
    path: Path
    names: tuple[str, ...] | None = None


@dataclass
class Home:
    index: int
    path: Path
    cfg: dict
    profiles: dict = field(default_factory=dict)


@dataclass
class Board:
    slug: str
    path: Path
    home: int  # index of the home whose settings apply to this board


def parse_home(value: str) -> HomeArg:
    """``PATH`` or ``PATH=NAME[,NAME...]``: split on the last ``=``; every NAME must be a valid profile name."""
    path, sep, raw = value.rpartition("=")
    if not sep:
        return HomeArg(Path(value).expanduser())
    names = tuple(dict.fromkeys(raw.split(",")))
    if not path or any(remote_schema.BOT_ID_RE.fullmatch(name) is None for name in names):
        raise ExportError("--home PATH=NAME[,NAME...]: every NAME must match [A-Za-z0-9._-]{1,64}")
    return HomeArg(Path(path).expanduser(), names)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(prog="pixelhq-export", description="Print one read-only pixelhq-remote/1 JSON document.")
    parser.add_argument("--home", action="append", default=[], metavar="PATH[=NAME,...]", type=parse_home,
                        help="Hermes home to read (repeatable; default: the usual root home). PATH=NAME[,NAME...] reads "
                             "only the listed profiles of that home (split on the last '=')")
    parser.add_argument("--kanban-db", action="append", default=[], metavar="PATH", dest="kanban_db",
                        help="extra Kanban board database (repeatable)")
    parser.add_argument("--label", metavar="NAME", help="source label shown to the reader (default: short host name)")
    parser.add_argument("--include-tool-args", action="store_true", dest="include_tool_args",
                        help="add the main argument of the last tool call (off by default)")
    args = parser.parse_args(argv)
    if args.label is not None and remote_schema.SOURCE_RE.fullmatch(args.label) is None:
        raise ExportError("--label must match [a-z0-9][a-z0-9._-]{0,31}")
    args.label = args.label or default_label()
    return args


def default_label() -> str:
    """The short host name as a valid label."""
    name = re.sub(r"[^a-z0-9._-]+", "-", socket.gethostname().split(".")[0].lower()).strip("-._")[:32]
    return name or "host"


# ---------------------------------------------------------------- homes and boards
def _slug(raw: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")[:64] or BOARD_FALLBACK


def _wanted(found: dict, names: tuple[str, ...] | None, number: int, warnings: list[str]) -> dict:
    """The profiles of one home the filter keeps (all without a filter); a listed name the home lacks is a warning."""
    if names is None:
        return found
    for name in names:
        if name not in found:
            warnings.append(f"profile {name} not found in home {number}")
    return {name: found[name] for name in names if name in found}


def read_homes(specs: list[HomeArg], warnings: list[str]) -> list[Home]:
    """Profiles of every home; a name seen in an earlier home is kept once and reported."""
    homes: list[Home] = []
    seen: dict[str, int] = {}
    resolved: set[Path] = set()
    for spec in specs:
        path = spec.path
        if path.resolve() in resolved:
            warnings.append(f"home {len(homes) + 1} listed twice: ignored")
            continue
        resolved.add(path.resolve())
        home = Home(len(homes), path, cfgmod.load_home(path, warnings))
        found = _wanted(profilemod.list_profiles(path, warnings), spec.names, home.index + 1, warnings)
        for name, profile in found.items():
            if remote_schema.BOT_ID_RE.fullmatch(name) is None:
                warnings.append(f"profile {name}: not exportable (invalid name)")
            elif name in seen:
                warnings.append(f"duplicate profile {name}: kept from home {seen[name] + 1}, ignored in home {home.index + 1}")
            else:
                seen[name] = home.index
                home.profiles[name] = profile
        homes.append(home)
    return homes


def gather_boards(homes: list[Home], extra: list[Path], warnings: list[str]) -> list[Board]:
    """Boards of every home plus the extra databases; one database is listed once, slugs are made unique."""
    found: list[Board] = []
    paths: set[Path] = set()
    slugs: set[str] = set()

    def add(raw: str, path: Path, home: int) -> None:
        if path.resolve() in paths:
            return
        paths.add(path.resolve())
        slug = base = _slug(raw)
        count = 1
        while slug in slugs:
            count += 1
            slug = f"{base[:60]}-{count}"
        if slug != base:
            warnings.append(f"board slug {base} used twice: second database exported as {slug}")
        slugs.add(slug)
        found.append(Board(slug, path, home))

    for home in homes:
        for slug, path in boards(home.cfg):
            add(slug, path, home.index)
    for path in extra:
        add(path.parent.name if path.name == "kanban.db" else path.stem, path, 0)
    return found


def board_counts(board: Board, now: float, warnings: list[str]) -> dict | None:
    """Card counts of one board; ``None`` (with a warning) when the database cannot be read."""
    try:
        with contextlib.closing(dbutil.ro(board.path)) as con:
            rows = dbutil.select(con, "tasks", ["status", "completed_at"]).fetchall()
    except Exception as exc:
        dbutil.warning(warnings, board.slug, exc)
        return None
    counts = {key: 0 for key in ("ready", "running", "blocked", "todo")}
    done = 0
    for status, completed in rows:
        if status in counts:
            counts[status] += 1
        elif status == "done" and isinstance(completed, (int, float)) and now - completed <= DAY_S:
            done += 1
    return {"slug": board.slug, **counts, "done24h": done}


# ---------------------------------------------------------------- bots and blockers
def _tool_text(tool: dict | None, include_args: bool) -> str:
    if not tool:
        return ""
    name = clean_text(tool.get("name"), 160)
    arg = clean_text(tool.get("arg"), 160) if include_args else ""
    return clean_text(f"{name}: {arg}" if arg else name, 160)


def _activity(sessions: dict, include_args: bool) -> dict:
    """currentStep, quest and lastTool of the newest active session (main sessions first)."""
    active = sorted(sessions["active"], key=lambda item: bool(item.get("isSub")))
    main = active[0] if active else None
    out = {}
    if main:
        out["currentStep"] = clean_text(main.get("step"), 160)
        out["quest"] = clean_text(main.get("title"), 80)
    tool = next((item["tool"] for item in active if item.get("tool")), None)
    out["lastTool"] = _tool_text(tool, include_args)
    return {key: value for key, value in out.items() if value}


def _status(sessions: dict, quests: list[dict], readable: bool) -> str:
    """running > blocked > unknown (activity could not be read at all) > idle."""
    kinds = {quest["status"] for quest in quests}
    if sessions["active"] or "running" in kinds:
        return "running"
    if "blocked" in kinds:
        return "blocked"
    return "idle" if readable else "unknown"


def read_bot(name: str, home: Home, quests: list[dict], score: dict, now: float, include_args: bool,
             warnings: list[str]) -> dict:
    sessions = live.read_sessions(name, now, home.cfg)
    warnings.extend(sessions.get("warnings", []))
    if sessions["error"]:
        dbutil.warning(warnings, name, sessions["error"])
    readable = state_db(name, home.cfg).exists() and not sessions["error"] and not sessions["warnings"]
    profile = home.profiles[name]
    last = (sessions["last"] or {}).get("at")
    bot = {"id": name, "model": clean_text(profile["model"], 80) or "?", "status": _status(sessions, quests, readable),
           "lastActive": int(last) if isinstance(last, (int, float)) else None,
           **_activity(sessions, include_args), "xp": score["xp"], "level": score["lvl"], "hp": score["hp"]}
    role = clean_text(profile.get("description"), 40)
    if role:
        bot["cls"] = role
    return bot


def read_bots(homes: list[Home], kanban: scoring.KanbanIndex, now: float, include_args: bool,
              warnings: list[str]) -> list[dict]:
    bots = []
    for home in homes:
        reviews, review_warnings = scoring.parse_reviews([home.cfg["reviews_path"], home.cfg["legacy_ledger_path"]])
        warnings.extend(review_warnings)
        scores = scoring.compute(list(home.profiles), kanban, reviews, home.cfg)
        for name in home.profiles:
            bots.append(read_bot(name, home, kanban.quests.get(name, []), scores[name], now, include_args, warnings))
    return bots


def read_cards(homes: list[Home], found: list[Board], warnings: list[str]) -> list[dict]:
    """Blocked cards, each group of boards read with the settings of the home it belongs to."""
    cards: list[dict] = []
    for home in homes:
        sources = [(board.slug, board.path) for board in found if board.home == home.index]
        rows, errors = read_blockers(home.cfg, NO_ROSTER, sources)
        warnings.extend(errors)
        cards.extend(rows)
    cards.sort(key=lambda card: (CAT_ORDER[card["cat"]], -card["ageDays"]))
    out = []
    for card in cards:
        if remote_schema.CARD_RE.fullmatch(str(card["id"])) is None or remote_schema.BOARD_RE.fullmatch(card["board"]) is None:
            warnings.append("a blocked card with a non-standard id was skipped")
            continue
        assignee = card["assignee"] if remote_schema.BOT_ID_RE.fullmatch(card["assignee"]) else "?"
        out.append({"board": card["board"], "id": card["id"], "title": clean_text(card["title"], 120),
                    "category": card["cat"], "assignee": assignee, "ageDays": card["ageDays"],
                    "reason": clean_text(card["reason"], 160)})
    return out


# ---------------------------------------------------------------- document
def _warning(text) -> str:
    """One warning: no absolute paths (the reader must not learn this host's layout), clean, at most 160 characters."""
    return clean_text(PATH_RE.sub("<path>", str(text)), remote_schema.MAX_WARNING)


def _warning_list(notes: list[str], warnings: list[str]) -> list[str]:
    """Notes first (they explain truncation), then the warnings without duplicates; at most 20 entries."""
    merged = list(dict.fromkeys(_warning(item) for item in notes + warnings if item))
    limit = remote_schema.MAX_WARNINGS
    if len(merged) > limit:
        merged = merged[:limit - 1] + [f"{len(merged) - limit + 1} more warnings omitted"]
    return merged


def _dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=True, separators=(",", ":"))


def fit_limits(doc: dict, warnings: list[str]) -> str:
    """Cap the lists and the document size by truncating lists; every cut is reported in ``warnings``."""
    notes = []
    for key in LIST_ORDER:
        cap = remote_schema.MAX_LIST[key]
        if len(doc[key]) > cap:
            notes.append(f"{key}: truncated to {cap} of {len(doc[key])}")
            doc[key] = doc[key][:cap]
    doc["warnings"] = _warning_list(notes, warnings)
    for key in LIST_ORDER:
        before = len(doc[key])
        while doc[key] and len(_dump(doc)) + 1 > remote_schema.MAX_BYTES:
            doc[key] = doc[key][:len(doc[key]) // 2]
        if len(doc[key]) < before:
            notes.append(f"{key}: truncated to {len(doc[key])} of {before} (document size)")
            doc["warnings"] = _warning_list(notes, warnings)
    return _dump(doc)


def open_notes(findings: dict[Path, str], homes: list[Home], found: list[Board]) -> list[str]:
    """R5-D10: one warning per profile database or board that was read with less than all its data, or not at all."""
    names = {state_db(name, home.cfg).resolve(): f"profile {name}" for home in homes for name in home.profiles}
    names.update({board.path.resolve(): f"board {board.slug}" for board in found})
    return [f"{names[path]}: {reason}" for path, reason in findings.items() if path in names]


def build(homes: list[Home], extra: list[Path], label: str, include_args: bool, warnings: list[str],
          now: float, findings: dict[Path, str] | None = None) -> dict:
    found = gather_boards(homes, extra, warnings)
    kanban = scoring.KanbanIndex()
    for board in found:
        kanban.add_board(board.slug, board.path)
    warnings.extend(kanban.warnings)
    counts = [board_counts(board, now, warnings) for board in found]
    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bots, blockers = read_bots(homes, kanban, now, include_args, warnings), read_cards(homes, found, warnings)
    warnings.extend(open_notes(findings or {}, homes, found))
    return {"schema": remote_schema.SCHEMA, "source": label, "generated": stamp,
            "pixelhq": cfgmod.disk_version() or "unknown", "bots": bots, "blockers": blockers,
            "boards": [row for row in counts if row], "warnings": []}


def export(homes: list[Path | HomeArg], kanban_dbs: list[Path], label: str, include_tool_args: bool = False,
           now: float | None = None) -> str:
    """The document as printed text (one line of JSON), already checked against the shared schema."""
    specs = [item if isinstance(item, HomeArg) else HomeArg(item) for item in homes]
    for spec in specs:
        if not spec.path.is_dir():
            raise ExportError("--home is not a directory")
    for path in kanban_dbs:
        if not path.is_file():
            raise ExportError("--kanban-db is not a file")
    warnings: list[str] = []
    found = read_homes(specs or [HomeArg(profilemod.root_home())], warnings)
    if not found[0].path.is_dir():
        raise ExportError("the default Hermes home is not a directory")
    with dbutil.create_nothing() as findings:  # R5-D10: no database read may create a file next to a database
        doc = build(found, kanban_dbs, label, include_tool_args, warnings, time.time() if now is None else now, findings)
    text = fit_limits(doc, warnings)
    try:
        return _dump(remote_schema.validate(json.loads(text)))
    except remote_schema.SchemaError as exc:  # a bug here must never reach the reader as a broken document
        raise ExportError(f"internal: invalid document ({exc})") from exc


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        text = export(args.home,
                      [Path(item).expanduser() for item in args.kanban_db], args.label, args.include_tool_args)
    except ExportError as exc:
        print(f"pixelhq-export: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # exception texts can quote paths or file contents: name the type only
        print(f"pixelhq-export: failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
