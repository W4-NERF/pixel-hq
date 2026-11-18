"""Invented ``pixelhq-remote/1`` documents and a stand-in for ``subprocess.run`` (no SSH ever runs in a test)."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import time

STAMP = "%Y-%m-%dT%H:%M:%SZ"


def stamp(seconds_ago: float = 0, base: float | None = None) -> str:
    moment = (time.time() if base is None else base) - seconds_ago
    return dt.datetime.fromtimestamp(moment, dt.timezone.utc).strftime(STAMP)


def bot(**over) -> dict:
    return {"id": "ops-bot", "model": "sample/model", "status": "idle", "lastActive": 1700000000, "xp": 120, "level": 3,
            "hp": 80, **over}


def card(**over) -> dict:
    return {"board": "platform", "id": "t_00aa11bb", "title": "Sample card", "category": "you", "assignee": "ops-bot",
            "ageDays": 2, "reason": "waiting for a decision", **over}


def board(**over) -> dict:
    return {"slug": "platform", "ready": 1, "running": 2, "blocked": 3, "todo": 4, "done24h": 5, **over}


def document(source: str = "atlas", *, base: float | None = None, age: float = 0, **over) -> dict:
    return {"schema": "pixelhq-remote/1", "source": source, "generated": stamp(age, base), "pixelhq": "1.4.0",
            "bots": [bot()], "blockers": [card()], "boards": [board()], "warnings": [], **over}


def raw(doc) -> bytes:
    return json.dumps(doc).encode("utf-8")


def done(stdout: bytes = b"", returncode: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ssh"], returncode, stdout=stdout, stderr=stderr)


class FakeSsh:
    """Replaces ``subprocess.run``: records every call and answers per destination.

    An outcome is bytes (stdout of a successful run), a ``CompletedProcess``, an exception (raised) or a callable
    (called, its result is used again as an outcome). Calls for a destination without an outcome fail the test.
    """

    def __init__(self, outcomes: dict | None = None):
        self.outcomes = outcomes or {}
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        outcome = self.outcomes[argv[-2]]
        while callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome if isinstance(outcome, subprocess.CompletedProcess) else done(outcome)

    @property
    def destinations(self) -> list[str]:
        return [argv[-2] for argv, _ in self.calls]
