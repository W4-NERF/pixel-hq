"""Pixel HQ actions on blocked Kanban cards.

Writes ONLY through the official CLI (`hermes kanban --board … comment|unblock|archive`), never into the
database. Which actions a card allows depends on its category (enforced here, not just in the UI).
`archive --rm` (permanent delete) is deliberately not available. Every action is appended to
var/actions.jsonl (audit log, git-ignored).
"""
from __future__ import annotations

import datetime as dt
import contextlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from . import config as cfgmod, dbutil

HERE = Path(__file__).resolve().parent

# No HERMES_HOME override here: the hermes launcher pins the root home, so the CLI always writes to the
# REAL boards. Test only on a dedicated sandbox board whose cards have no assignee.
WS_BACKUP = HERE.parent / "var" / "archived-workspaces"
LOG = HERE.parent / "var" / "actions.jsonl"
BOARD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ID_RE = re.compile(r"^t_[0-9a-f]{6,16}$")


LABEL = {"answer": "Answer & unblock", "retry": "Retry", "comment": "Comment", "archive": "Archive"}


def _collect():
    from . import collect
    return collect


def _hermes() -> list[str]:
    exe = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")
    return [exe]


def _status(board: str, tid: str, warnings: list[str] | None = None, cfg: dict | None = None) -> str | None:
    cfg = cfgmod.load() if cfg is None else cfg
    warnings = warnings if warnings is not None else []
    db = Path(cfg["hermes_home"]) / "kanban" / "boards" / board / "kanban.db"
    try:
        with contextlib.closing(dbutil.ro(db)) as con:
            rows = dbutil.rows(con, "tasks", ["status", "id"], "id=? LIMIT 1", (tid,),
                               warnings=warnings, source=board)
        return rows[0][0] if rows else None
    except (OSError, sqlite3.Error) as exc:
        dbutil.warning(warnings, board, exc)
        return None


def _backup_workspace(board: str, tid: str, cfg: dict | None = None) -> str | None:
    cfg = cfgmod.load() if cfg is None else cfg
    ws = Path(cfg["hermes_home"]) / "kanban" / "boards" / board / "workspaces" / tid
    if ws.is_dir() and any(ws.iterdir()):
        dst = WS_BACKUP / board / f"{tid}-{dt.datetime.now():%Y%m%d-%H%M%S}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ws, dst, symlinks=True)
        return str(dst)
    return None


def _log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run(body: dict) -> dict:
    cfg = cfgmod.load()
    boards = Path(cfg["hermes_home"]) / "kanban" / "boards"
    operator = re.sub(r"[^\w .-]", "", cfg["operator_name"])[:40] or "operator"
    tag = f"[Pixel HQ · {operator}]"
    board = str(body.get("board") or "")
    tid = str(body.get("id") or "")
    action = str(body.get("action") or "")
    text = str(body.get("text") or "").strip()
    if not BOARD_RE.match(board) or not (boards / board / "kanban.db").exists():
        return {"ok": False, "error": "unknown board"}
    if not ID_RE.match(tid):
        return {"ok": False, "error": "invalid card id"}
    if action not in LABEL:
        return {"ok": False, "error": "unknown action"}
    if action in ("answer", "comment") and not (3 <= len(text) <= 4000):
        return {"ok": False, "error": "text missing or too long (3–4000 characters)"}

    warnings = []
    before = _status(board, tid, warnings, cfg)
    if warnings:
        return {"ok": False, "error": "card status unavailable", "warnings": warnings}
    if before is None:
        return {"ok": False, "error": "card not found"}
    if action != "comment" and before != "blocked":
        return {"ok": False, "error": f"card is no longer blocked (status: {before}) – reload"}

    col = _collect()
    blockers, _ = col.read_blockers()
    card = next((b for b in blockers if b["board"] == board and b["id"] == tid), None)
    cat = card["cat"] if card else None
    if action != "comment" and (cat is None or action not in col.ALLOWED.get(cat, [])):
        return {"ok": False, "error": f"action '{LABEL[action]}' is not allowed for category {cat or '?'}"}

    base = _hermes() + ["kanban", "--board", board]
    if action == "answer":
        cmd = base + ["unblock", "--reason", f"{tag} {text}", tid]
    elif action == "retry":
        cmd = base + ["unblock", "--reason", f"{tag} retry (from Pixel HQ)", tid]
    elif action == "comment":
        cmd = base + ["comment", "--author", f"{operator} (Pixel HQ)", tid, text]
    else:  # archive — never --rm
        cmd = base + ["archive", tid]

    try:
        if action == "archive":
            _backup_workspace(board, tid, cfg)  # archive reaps the workspace dir — back it up first
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        out = (proc.stdout + proc.stderr).strip()
        rc = proc.returncode
    except Exception as exc:  # timeout etc.
        out, rc = f"{type(exc).__name__}: {exc}", -1
    after = _status(board, tid, warnings, cfg)
    ok = rc == 0 and not warnings and (action == "comment" or after != "blocked")
    entry = {"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "board": board, "id": tid,
             "action": action, "cat": cat, "before": before, "after": after, "rc": rc, "ok": ok,
             "text": text[:500] if text else None}
    _log(entry)
    hint = ""
    if ok and action in ("answer", "retry") and card and card.get("remote"):
        hint = " Note: this bot runs on a remote host – the local dispatcher will not start it."
    return {"ok": ok, "action": action, "label": LABEL[action], "board": board, "id": tid,
            "before": before, "after": after, "output": out[-600:], "warnings": warnings,
            "message": (f"{LABEL[action]}: {tid} {before} → {after}." + hint) if ok
            else f"{LABEL[action]} failed (rc={rc}): {out[-300:]}"}
