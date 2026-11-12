"""Append UI and tool reviews to the JSONL ledger; never write to Hermes databases."""
from __future__ import annotations

import errno
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX advisory lock
except ImportError:  # Windows has no fcntl: appends still use one O_APPEND write, just without the lock
    fcntl = None

from .config import ledger_path


DIMS = {"correctness", "completeness", "format", "safety"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
RID_RE = re.compile(r"^[0-9a-f]{16,32}$")  # request id of one UI review draft (retries reuse it)
RID_WINDOW = 64 * 1024  # a retry is looked up in this much of the ledger's tail
SYMLINK_MESSAGE = "The review ledger is a symlink; set reviews_path to the real file."


def _identifier(value) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 64 and IDENTIFIER_RE.fullmatch(value) is not None


def append(body: dict, cfg: dict, known_bots) -> dict:
    """Validate before touching disk; only server-owned UI metadata is persisted."""
    return _append(body, cfg, known_bots,
                   reviewer=str(cfg.get("operator_name", "operator"))[:120], source="ui")


def append_tool(args: dict, cfg: dict, reviewer: str) -> dict:
    """Use the same validator/writer, allowing helper ids that are not local profiles."""
    if not isinstance(args, dict):
        return {"ok": False, "message": "Expected a review object."}
    body = {key: args[key] for key in ("agent", "parent", "verdict", "ref") if key in args}
    dims = {key: args[key] for key in sorted(DIMS) if key in args}
    if dims:
        body["dims"] = dims
    return _append(body, cfg, None, reviewer=reviewer, source="tool")


def _append(body: dict, cfg: dict, known_bots, *, reviewer: str, source: str) -> dict:
    """Validate a review before the shared append; metadata comes only from trusted callers."""
    if not isinstance(body, dict):
        return {"ok": False, "message": "Expected a review object."}
    agent, verdict = body.get("agent"), body.get("verdict")
    for key in ("agent", "parent"):
        if (key == "agent" or key in body) and not _identifier(body.get(key)):
            return {"ok": False, "message": f"Invalid {key}: use 1–64 ASCII letters, digits or ._+- only."}
    if known_bots is not None and agent not in known_bots:
        return {"ok": False, "message": "Unknown agent."}
    if verdict not in ("pass", "revise", "fail"):
        return {"ok": False, "message": "Invalid verdict: use pass, revise or fail."}
    if "dims" in body:
        dims = body["dims"]
        if (not isinstance(dims, dict) or any(key not in DIMS or type(value) is not int
                                              or not 1 <= value <= 5 for key, value in dims.items())):
            return {"ok": False, "message": "Invalid dims: use integer scores 1–5 for the four dimensions."}
    ref = body.get("ref", "")
    if not isinstance(ref, str) or len(ref) > 200:
        return {"ok": False, "message": "Invalid ref: use a string of at most 200 characters."}
    rid = body.get("rid") if source == "ui" else None  # the agent tool sends no rid
    if source == "ui" and "rid" in body and (not isinstance(rid, str) or RID_RE.fullmatch(rid) is None):
        return {"ok": False, "message": "Invalid rid: use 16–32 lowercase hex characters."}
    record = {"ts": datetime.now(timezone.utc).isoformat(), "agent": agent,
              "verdict": verdict, "ref": ref,
              "reviewer": reviewer, "source": source}
    if "dims" in body:
        record["dims"] = dict(body["dims"])
    if source == "tool" and "parent" in body:
        record["parent"] = body["parent"]
    if rid is not None:
        record["rid"] = rid
    payload = (json.dumps(record, ensure_ascii=True) + "\n").encode("utf-8")
    try:
        path = Path(ledger_path(cfg))
        path.parent.mkdir(parents=True, exist_ok=True)
        written = _append_line(path, payload, rid)
    except LedgerSymlink:
        return {"ok": False, "message": SYMLINK_MESSAGE}
    except (OSError, ValueError, KeyError):
        # Paths and OS diagnostics may contain private installation details.
        return {"ok": False, "message": "Could not append the review; check the review path and permissions."}
    return {"ok": True, "message": "Review saved." if written else "Review already recorded."}


class LedgerSymlink(OSError):
    """The ledger path is a symbolic link; it is never followed."""


def _refuse_symlink(path: Path) -> None:
    """Portable check for platforms (or filesystems) where O_NOFOLLOW does not exist or is not enough."""
    try:
        linked = stat.S_ISLNK(os.lstat(path).st_mode)
    except FileNotFoundError:
        return
    if linked:
        raise LedgerSymlink(SYMLINK_MESSAGE)


def _recorded(fd: int, size: int, rid: str) -> bool:
    """Is ``rid`` in one of the complete records within the last ``RID_WINDOW`` bytes of the ledger?"""
    start = max(0, size - RID_WINDOW - 1)  # one byte more: a newline there means the window starts on a record
    os.lseek(fd, start, os.SEEK_SET)
    tail = b""
    while len(tail) < size - start:
        chunk = os.read(fd, size - start - len(tail))
        if not chunk:
            break
        tail += chunk
    lines = tail.split(b"\n")
    if start:
        lines = lines[1:]  # the window may begin in the middle of a record
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("rid") == rid:
            return True
    return False


def _append_line(path: Path, payload: bytes, rid: str | None = None) -> bool:
    """One O_APPEND write with rollback on a short write; serialized across writers where flock exists.

    Returns False without writing when ``rid`` is already in the tail of the ledger (a retried request).
    """
    _refuse_symlink(path)
    # O_BINARY (Windows only): no newline translation, so the ledger stays byte-identical across platforms.
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", errno.ELOOP)):  # O_NOFOLLOW hit a symlink
            raise LedgerSymlink(SYMLINK_MESSAGE) from exc
        raise
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        if rid is not None and size and _recorded(fd, size, rid):
            return False
        if size:
            os.lseek(fd, -1, os.SEEK_END)
            if os.read(fd, 1) != b"\n":
                payload = b"\n" + payload
        try:
            if os.write(fd, payload) != len(payload):
                raise OSError("Incomplete review append")
            os.fsync(fd)
        except OSError:
            os.ftruncate(fd, size)
            raise
        return True
    finally:
        os.close(fd)  # also releases the advisory lock
