"""Bot-HQ actions on blocked Kanban cards.

Writes ONLY through the official CLI (`hermes kanban --board … comment|unblock|archive`), never into the
database. Which actions a card allows depends on its category (enforced here, not just in the UI).
`archive --rm` (permanent delete) is deliberately not available. Every action is appended to
var/actions.jsonl (audit log, git-ignored).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as cfgmod  # noqa: E402

CFG = cfgmod.load()
# No HERMES_HOME override here: the hermes launcher pins the root home, so the CLI always writes to the
# REAL boards. Test only on a dedicated sandbox board whose cards have no assignee.
BOARDS = Path(CFG["hermes_home"]) / "kanban" / "boards"
WS_BACKUP = HERE.parent / "var" / "archived-workspaces"
LOG = HERE.parent / "var" / "actions.jsonl"
BOARD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ID_RE = re.compile(r"^t_[0-9a-f]{6,16}$")
OPERATOR = re.sub(r"[^\w .-]", "", str(CFG["operator_name"]))[:40] or "operator"
TAG = f"[Bot-HQ · {OPERATOR}]"

LABEL = {"answer": "Answer & unblock", "retry": "Retry", "comment": "Comment", "archive": "Archive"}


def _collect():
    spec = importlib.util.spec_from_file_location("bothq_collect_actions", HERE / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hermes() -> list[str]:
    exe = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")
    return [exe]


def _status(board: str, tid: str) -> str | None:
    db = BOARDS / board / "kanban.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    try:
        row = con.execute("select status from tasks where id=?", (tid,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _backup_workspace(board: str, tid: str) -> str | None:
    ws = BOARDS / board / "workspaces" / tid
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
    board = str(body.get("board") or "")
    tid = str(body.get("id") or "")
    action = str(body.get("action") or "")
    text = str(body.get("text") or "").strip()
    if not BOARD_RE.match(board) or not (BOARDS / board / "kanban.db").exists():
        return {"ok": False, "error": "unknown board"}
    if not ID_RE.match(tid):
        return {"ok": False, "error": "invalid card id"}
    if action not in LABEL:
        return {"ok": False, "error": "unknown action"}
    if action in ("answer", "comment") and not (3 <= len(text) <= 4000):
        return {"ok": False, "error": "text missing or too long (3–4000 characters)"}

    before = _status(board, tid)
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
        cmd = base + ["unblock", "--reason", f"{TAG} {text}", tid]
    elif action == "retry":
        cmd = base + ["unblock", "--reason", f"{TAG} retry (from Bot-HQ)", tid]
    elif action == "comment":
        cmd = base + ["comment", "--author", f"{OPERATOR} (Bot-HQ)", tid, text]
    else:  # archive — never --rm
        cmd = base + ["archive", tid]

    try:
        if action == "archive":
            _backup_workspace(board, tid)  # archive reaps the workspace dir — back it up first
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        out = (proc.stdout + proc.stderr).strip()
        rc = proc.returncode
    except Exception as exc:  # timeout etc.
        out, rc = f"{type(exc).__name__}: {exc}", -1
    after = _status(board, tid)
    ok = rc == 0 and (action == "comment" or after != "blocked")
    entry = {"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "board": board, "id": tid,
             "action": action, "cat": cat, "before": before, "after": after, "rc": rc, "ok": ok,
             "text": text[:500] if text else None}
    _log(entry)
    hint = ""
    if ok and action in ("answer", "retry") and card and card.get("remote"):
        hint = " Note: this bot runs on a remote host – the local dispatcher will not start it."
    return {"ok": ok, "action": action, "label": LABEL[action], "board": board, "id": tid,
            "before": before, "after": after, "output": out[-600:],
            "message": (f"{LABEL[action]}: {tid} {before} → {after}." + hint) if ok
            else f"{LABEL[action]} failed (rc={rc}): {out[-300:]}"}
