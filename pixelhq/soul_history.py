"""Keep the previous SOUL of a bot under plugin-data so the operator can restore it (round-4 §4).

This is the plugin's only new write path. A request names a bot and a source (``local`` or a connection id),
never a path: both are validated against a fixed pattern and mapped to
``<root>/plugin-data/pixel-hq/soul-history/<source>/<bot>/<UTC yyyymmddThhmmssZ>-<rid>.md`` (full request id, R4-D1).
"""
from __future__ import annotations

import os
import re
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path

from .common import clip
from .profiles import root_home
from .reviews import RID_RE
from .roster import _irregular, _replace


KEY_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")      # applied to bot and source after lower-casing
# Version id rule, one copy per language: this one, VERSION_ID_RE in desktop/plugin.js and CONF_VERSION_ID in
# pixelhq/ui/js/39-soul-history.js (tests/test_soul_history_contract.py keeps them equal).
FILE_RE = re.compile(r"(\d{8}T\d{6}Z)-([a-z0-9]{8,32})\.md")
UNSAFE_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")        # NUL and the other C0 controls except \t and \n
MAX_BYTES = 64 * 1024
KEEP = 10
FIRST_LINE = 80
_LOCK = threading.Lock()                                  # one writer per process; retries and races stay ordered


class HistoryError(Exception):
    """A refusal with an HTTP status and a short message that never contains a path."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def key_part(value, field: str) -> str:
    """Lower-case a bot id or source key; anything outside the fixed pattern is refused (no path syntax survives)."""
    if not isinstance(value, str) or not value.isascii() or KEY_RE.fullmatch(value.lower()) is None:
        raise HistoryError(f"{field}: use 1–64 ASCII letters, digits or ._- only, starting with a letter or digit.")
    return value.lower()


def clean_text(value) -> bytes:
    """Normalise line endings to ``\\n`` and enforce the SOUL limits; returns the UTF-8 bytes to store."""
    if not isinstance(value, str):
        raise HistoryError("text: expected a string.")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if UNSAFE_RE.search(text):
        raise HistoryError("text: control characters other than tab and newline are not allowed.")
    try:
        payload = text.encode("utf-8")
    except UnicodeEncodeError:
        raise HistoryError("text: not valid Unicode text.") from None
    if len(payload) > MAX_BYTES:
        raise HistoryError(f"text: at most {MAX_BYTES // 1024} KiB.")
    return payload


def _timestamp(name: str):
    """The save time encoded in a file name, or None when it is not a real date."""
    try:
        return datetime.strptime(FILE_RE.fullmatch(name).group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        return None


def _history_root(cfg: dict) -> Path:
    home = Path(cfg.get("hermes_home") or root_home())
    return home / "plugin-data" / "pixel-hq" / "soul-history"


def _directory(path: Path, create: bool) -> bool:
    """True when ``path`` is a real directory (created 0700 on demand); a symlink or file is refused, never followed."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        if not create:
            return False
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
        return True
    if not stat.S_ISDIR(mode):
        raise HistoryError("The SOUL history store is not a regular directory.", 409)
    return True


def _store(cfg: dict, source: str, bot: str, create: bool):
    """``soul-history/<source>/<bot>`` with every level checked; None when it does not exist (read paths)."""
    root = _history_root(cfg)
    if create:
        root.parent.mkdir(parents=True, exist_ok=True)
    path = root
    for part in (None, source, bot):
        path = path if part is None else path / part
        if not _directory(path, create):
            return None
        if create:
            os.chmod(path, 0o700)
    return path


def _versions(directory: Path) -> list:
    """Regular, in-bounds history files as ``(name, stat)``, newest first; everything else is ignored."""
    found = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if FILE_RE.fullmatch(entry.name) is None or _timestamp(entry.name) is None:
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES:
                found.append((entry.name, info))
    found.sort(key=lambda item: (item[0][:16], item[1].st_mtime_ns, item[0]), reverse=True)
    return found


def _read(directory: Path, name: str) -> str:
    """Read one listed file without following a link that replaced it in the meantime."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / name, flags)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise HistoryError("No such version.", 404)
        return stream.read(MAX_BYTES + 1).decode("utf-8", errors="replace")


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return clip(line.strip(), FIRST_LINE)
    return ""


def _rid_of(name: str):
    """The request id encoded in a history file name, or None when it is not one."""
    match = FILE_RE.fullmatch(name)
    return match.group(2) if match else None


def _recorded(directory: Path, rid: str) -> bool:
    """Was this request id saved already? A non-regular entry under that id is refused, not skipped."""
    with os.scandir(directory) as entries:
        names = [entry.name for entry in entries if _rid_of(entry.name) == rid]
    if _irregular(*(directory / name for name in names)):
        raise HistoryError("The SOUL history store contains an entry that is not a regular file.", 409)
    return bool(names)


def _prune(directory: Path, keep_name: str) -> None:
    """Keep the newest ``KEEP`` files; the file just written always survives, even if the clock went backwards."""
    names = [name for name, _info in _versions(directory)]
    survivors = set(names[:KEEP])
    if keep_name not in survivors:
        survivors = set(names[:KEEP - 1]) | {keep_name}
    for name in names:
        if name not in survivors:
            try:
                os.unlink(directory / name)
            except OSError:
                pass  # a failed cleanup never undoes a successful backup


def _guarded(call):
    try:
        return call()
    except HistoryError:
        raise
    except (OSError, ValueError):
        # Paths and OS diagnostics may contain private installation details.
        raise HistoryError("The SOUL history store is not available; check plugin-data permissions.", 500) from None


def _request(body) -> tuple:
    if not isinstance(body, dict):
        raise HistoryError("body: expected an object.")
    source, bot = key_part(body.get("sourceKey"), "sourceKey"), key_part(body.get("bot"), "bot")
    rid = body.get("rid")
    if not isinstance(rid, str) or RID_RE.fullmatch(rid) is None:
        raise HistoryError("rid: use 16–32 lowercase hex characters.")
    return source, bot, clean_text(body.get("text")), rid


def save(body, cfg: dict, now: datetime | None = None) -> dict:
    """Store the previous SOUL once per ``rid``; validation happens before any disk access."""
    source, bot, payload, rid = _request(body)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")

    def write() -> dict:
        with _LOCK:
            directory = _store(cfg, source, bot, create=True)
            if _recorded(directory, rid):
                return {"ok": True, "message": "SOUL version already saved."}
            name = f"{stamp}-{rid}.md"
            if _irregular(directory / name):
                raise HistoryError("The SOUL history store contains an entry that is not a regular file.", 409)
            _replace(directory / name, payload, prefix=".soul-")
            _prune(directory, name)
            return {"ok": True, "message": "SOUL version saved."}
    return _guarded(write)


def list_versions(bot, source, cfg: dict) -> list:
    """Newest first: ``[{id, savedAt, bytes, firstLine}]``; an unknown bot or source has an empty history."""
    key = (key_part(source, "sourceKey"), key_part(bot, "bot"))

    def read() -> list:
        directory = _store(cfg, *key, create=False)
        rows = []
        for name, info in (_versions(directory) if directory else []):
            try:
                text = _read(directory, name)
            except (OSError, HistoryError):
                continue
            rows.append({"id": name, "savedAt": _timestamp(name).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "bytes": info.st_size, "firstLine": _first_line(text)})
        return rows
    return _guarded(read)


def item(bot, source, version_id, cfg: dict) -> dict:
    """The text of one version; ``version_id`` must equal a currently listed file name."""
    key = (key_part(source, "sourceKey"), key_part(bot, "bot"))
    if not isinstance(version_id, str) or FILE_RE.fullmatch(version_id) is None:
        raise HistoryError("id: not a history version id.")

    def read() -> dict:
        directory = _store(cfg, *key, create=False)
        if directory is None or version_id not in {name for name, _info in _versions(directory)}:
            raise HistoryError("No such version.", 404)
        return {"text": _read(directory, version_id)}
    return _guarded(read)
