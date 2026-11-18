"""Remote sources of the collector (round 5 §2): other hosts' ``pixelhq-remote/1`` documents.

Everything a source returns is untrusted. It is fetched only while a snapshot is collected (the route's TTL cache
decides how often; there is no loop or timer here), parsed, and checked by :func:`remote_schema.validate`.

Two kinds of source:

* ``ssh:<destination>``: one fixed command, never a shell. The remote key's forced command decides what runs.
* ``file:<name>``: ``<root>/plugin-data/pixel-hq/remote/<name>.json``, a regular file (no symlink) of at most 1 MiB.

The last good document of every source stays in this process's memory (never on disk) so that a failing source is
shown with its age instead of vanishing.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import remote_schema
from .config import SOURCE_RE

GRACE_S = 1  # all sources together never keep a snapshot waiting longer than the timeout plus this
FUTURE_S = 120  # a document generated further ahead of this host's clock is invalid (R5-D3)
SSH_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SSH_AUTH_SOCK")  # R5-D8: nothing else
STAMP = "%Y-%m-%dT%H:%M:%SZ"
_LOCK = threading.Lock()
_GOOD: dict[str, tuple[dict, float]] = {}  # entry -> (last good cleaned document, unix time it describes)


class FetchError(Exception):
    """A source did not deliver a usable document; ``state`` is ``unreachable`` or ``invalid``, ``detail`` is short."""

    def __init__(self, state: str, detail: str):
        super().__init__(f"{state} ({detail})")
        self.state, self.detail = state, detail


@dataclass
class Source:
    entry: str                    # as configured: ssh:<dest> or file:<name>
    name: str                     # configured label, unique among the sources
    kind: str                     # "ssh" or "file"
    label: str = ""               # shown label: the document's ``source`` when usable, else ``name``
    doc: dict | None = None       # cleaned document of this round, else the last good one
    observed: float | None = None  # unix time the document describes (age base)
    state: str = ""               # outcome of this round's fetch: ok | unreachable | invalid
    error: str = ""               # why this round's fetch failed (also while the last good document is shown)


def reset() -> None:
    """Forget every last good document (tests; a restart of the backend does the same)."""
    with _LOCK:
        _GOOD.clear()


def _unique(candidate: str, used: set[str]) -> str:
    name, number = candidate, 1
    while name in used:
        number += 1
        name = f"{candidate[:28]}-{number}"
    used.add(name)
    return name


def source_names(entries: list[str]) -> list[str]:
    """One configured label per entry: the ``file:`` name or the host part of the destination, made unique."""
    used: set[str] = set()
    names = []
    for index, entry in enumerate(entries):
        kind, _, target = entry.partition(":")
        base = target if kind == "file" else target.rpartition("@")[2].lower()[:32]
        names.append(_unique(base if SOURCE_RE.fullmatch(base) else f"source-{index + 1}", used))
    return names


# ---------------------------------------------------------------- transports
def ssh_env() -> dict[str, str]:
    """The SSH child's whole environment: the allowlisted variables that are set here, nothing else (R5-D8)."""
    return {name: os.environ[name] for name in SSH_ENV if name in os.environ}


def _ssh(dest: str, timeout: float) -> bytes:
    """The only command this module ever runs; the destination was validated by ``config.valid_remote_entry``."""
    try:
        done = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-T", dest, "pixelhq-export"],
                              shell=False, timeout=timeout, capture_output=True, env=ssh_env())
    except subprocess.TimeoutExpired:
        raise FetchError("unreachable", "timeout") from None
    except OSError:
        raise FetchError("unreachable", "ssh unavailable") from None
    if done.returncode != 0:
        raise FetchError("unreachable", f"exit {done.returncode}")  # stderr may name hosts or paths: never shown
    if not isinstance(done.stdout, bytes):
        raise FetchError("invalid", "no output")
    if len(done.stdout) > remote_schema.MAX_BYTES:
        raise FetchError("invalid", "output over 1 MiB")
    return done.stdout


def _regular(mode: int) -> None:
    if stat.S_ISLNK(mode):
        raise FetchError("invalid", "symlink refused")
    if not stat.S_ISREG(mode):
        raise FetchError("invalid", "not a regular file")


def _file(root: str | Path, name: str) -> bytes:
    path = Path(root) / "plugin-data" / "pixel-hq" / "remote" / f"{name}.json"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise FetchError("unreachable", "file missing") from None
    except OSError:
        raise FetchError("unreachable", "file unreadable") from None
    _regular(info.st_mode)
    if info.st_size > remote_schema.MAX_BYTES:
        raise FetchError("invalid", "file over 1 MiB")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        stream = os.fdopen(os.open(path, flags), "rb")  # a swap for a symlink after the check fails here (O_NOFOLLOW)
    except OSError:
        raise FetchError("unreachable", "file unreadable") from None
    with stream:
        try:
            _regular(os.fstat(stream.fileno()).st_mode)
            data = stream.read(remote_schema.MAX_BYTES + 1)
        except OSError:
            raise FetchError("unreachable", "file unreadable") from None
    if len(data) > remote_schema.MAX_BYTES:
        raise FetchError("invalid", "file over 1 MiB")
    return data


# ---------------------------------------------------------------- one document
def _epoch(stamp: str) -> float:
    try:
        return dt.datetime.strptime(stamp, STAMP).replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        raise FetchError("invalid", "generated: not a valid time") from None


def parse(raw: bytes, name: str) -> tuple[dict, float]:
    """Validated document and its ``generated`` time. A ``source`` that is no usable label becomes ``name``."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise FetchError("invalid", "not UTF-8") from None
    except (ValueError, RecursionError):
        raise FetchError("invalid", "not JSON") from None
    if isinstance(doc, dict) and not (isinstance(doc.get("source"), str) and SOURCE_RE.fullmatch(doc["source"])):
        doc = {**doc, "source": name}
    try:
        clean = remote_schema.validate(doc)
    except remote_schema.SchemaError as exc:
        raise FetchError("invalid", str(exc)) from None
    return clean, _epoch(clean["generated"])


def _fetch(entry: str, name: str, timeout: float, root: str | Path):
    """``(document, generated)`` or the :class:`FetchError`; a thread of the pool never raises."""
    kind, _, target = entry.partition(":")
    try:
        return parse(_ssh(target, timeout) if kind == "ssh" else _file(root, target), name)
    except FetchError as exc:
        return exc
    except Exception:  # whatever a source does, the snapshot goes on
        return FetchError("unreachable", "error")


def _gather(sources: list[Source], timeout: float, root: str | Path) -> list:
    """Fetch every source in parallel; a source still running after ``timeout + GRACE_S`` counts as a timeout."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="pixelhq-remote")
    futures = [pool.submit(_fetch, src.entry, src.name, timeout, root) for src in sources]
    concurrent.futures.wait(futures, timeout=timeout + GRACE_S)
    pool.shutdown(wait=False, cancel_futures=True)  # never wait for a straggler: its own timeout ends the process
    return [future.result() if future.done() else FetchError("unreachable", "timeout") for future in futures]


def _settle(src: Source, outcome, stamp: float) -> None:
    """A document is as old as its ``generated`` time says, for SSH and files alike (R5-D3), never newer than now."""
    if not isinstance(outcome, FetchError) and outcome[1] > stamp + FUTURE_S:
        outcome = FetchError("invalid", "generated: in the future")
    if isinstance(outcome, FetchError):
        src.state, src.error = outcome.state, outcome.detail
        src.doc, src.observed = _GOOD.get(src.entry, (None, None))
        return
    doc, generated = outcome
    src.state, src.doc, src.observed = "ok", doc, min(stamp, generated)
    _GOOD[src.entry] = (doc, src.observed)


def _labels(sources: list[Source]) -> None:
    """The document's own ``source`` when no other source shows it already, else the configured name (numbered if needed)."""
    used: set[str] = set()
    for src in sources:
        wanted = [src.doc["source"], src.name] if src.doc else [src.name]
        src.label = next((label for label in wanted if label not in used), None) or _unique(src.name, used)
        used.add(src.label)


def fetch_all(entries: list[str], *, timeout: float, root: str | Path, now: float | None = None) -> list[Source]:
    """Fetch every configured source (already validated) in parallel and settle it against its last good document."""
    names = source_names(entries)
    sources = [Source(entry, name, entry.partition(":")[0]) for entry, name in zip(entries, names, strict=True)]
    outcomes = _gather(sources, timeout, root) if sources else []
    stamp = time.time() if now is None else now
    with _LOCK:
        for entry in [entry for entry in _GOOD if entry not in entries]:
            del _GOOD[entry]
        for src, outcome in zip(sources, outcomes, strict=True):
            _settle(src, outcome, stamp)
    _labels(sources)
    return sources


# ---------------------------------------------------------------- footer status
def age_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h" if seconds < 86400 else f"{seconds // 86400} d"


def status(src: Source, now: float, stale_after: int) -> dict:
    """The footer line of one source: ``ok · 35 s``, ``stale · 12 min``, ``unreachable (timeout)``, ``invalid (reason)``.

    ``ok``/``stale`` describe the document in use (older than ``stale_after`` seconds is stale), even when this
    round's fetch failed; ``error`` then names the failure.
    """
    age = None if src.observed is None else max(0, int(now - src.observed))
    if src.doc is None:
        state, detail = src.state, src.error
        text = f"{state} ({detail})"
    else:
        state, detail = ("stale" if age > stale_after else "ok"), ""
        text = f"{state} · {age_text(age)}"
    return {"name": src.name, "source": src.label, "kind": src.kind, "state": state, "detail": detail, "age": age,
            "text": text, "error": src.error}
