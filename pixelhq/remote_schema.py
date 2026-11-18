"""The ``pixelhq-remote/1`` document: limits, field rules and one validator shared by both ends.

The exporter (``export.py``, runs on the remote host) checks the document it is about to print with
:func:`validate`; the collector of the reading Pixel HQ uses the same function on whatever a source returns,
which is untrusted input. :func:`validate` never trusts the shape: it type-checks every field, enforces the
enums and id patterns, clips and cleans text, drops unknown fields and refuses lists above their limits.
A refusal raises :class:`SchemaError` whose message is short enough to show in a footer.
"""
from __future__ import annotations

import datetime as dt
import math
import re

from .common import clip
from .config import SOURCE_RE, text_rejected

SCHEMA = "pixelhq-remote/1"
MAX_BYTES = 1 << 20  # the whole document, as printed
MAX_LIST = {"bots": 200, "blockers": 500, "boards": 64}
MAX_WARNINGS, MAX_WARNING = 20, 160
MAX_REASON = 80  # longest SchemaError message

BOT_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")      # same rule as roster ids (roster.ID_RE)
BOARD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")   # same rule as Kanban board slugs (actions.BOARD_RE)
CARD_RE = re.compile(r"t_[0-9a-f]{6,16}")            # same rule as card ids (actions.ID_RE)
STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
STATUSES = ("running", "idle", "blocked", "unknown")
CATEGORIES = ("you", "technical", "stale", "unknown", "upstream")
BIG = 10 ** 12

# field -> (kind, argument, required). Kinds: text (limit), re (pattern), enum (values), int ((lo, hi)),
# int? (nullable int), ts? (nullable unix seconds).
BOT_FIELDS = {
    "id": ("re", BOT_ID_RE, True), "model": ("text", 80, True), "status": ("enum", STATUSES, True),
    "lastActive": ("ts?", None, True), "currentStep": ("text", 160, False), "quest": ("text", 80, False),
    "lastTool": ("text", 160, False), "xp": ("int", (0, BIG), True), "level": ("int", (1, BIG), True),
    "hp": ("int?", (0, 100), True), "cls": ("text", 40, False),
}
BLOCKER_FIELDS = {
    "board": ("re", BOARD_RE, True), "id": ("re", CARD_RE, True), "title": ("text", 120, True),
    "category": ("enum", CATEGORIES, True), "assignee": ("text", 64, True), "ageDays": ("int", (0, BIG), True),
    "reason": ("text", 160, True),
}
BOARD_FIELDS = {
    "slug": ("re", BOARD_RE, True),
    **{key: ("int", (0, BIG), True) for key in ("ready", "running", "blocked", "todo", "done24h")},
}
SECTIONS = {"bots": BOT_FIELDS, "blockers": BLOCKER_FIELDS, "boards": BOARD_FIELDS}
UNIQUE = {"bots": "id", "boards": "slug"}


class SchemaError(ValueError):
    """The document is not a valid ``pixelhq-remote/1`` document; the message is at most 80 characters."""

    def __init__(self, reason: str):
        super().__init__(clip(reason, MAX_REASON, collapse_whitespace=True))


def clean_text(value, limit: int) -> str:
    """Single-line text without characters the shared text rule refuses, clipped to ``limit``.

    Line breaks and tabs become one space first; the other control characters are removed.
    """
    text = "".join(ch for ch in " ".join(str(value or "").split()) if not text_rejected(ch))
    return clip(text, limit, collapse_whitespace=True)


def _number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{where}: expected a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise SchemaError(f"{where}: expected a finite number")
    return value


def _int(value, bounds: tuple[int, int], where: str) -> int:
    number = _number(value, where)
    if int(number) != number or not bounds[0] <= number <= bounds[1]:
        raise SchemaError(f"{where}: expected an integer {bounds[0]}..{bounds[1]}")
    return int(number)


def _field(value, kind: str, arg, where: str):
    """One value of a known field, cleaned; ``None`` only for the nullable kinds."""
    if kind.endswith("?") and value is None:
        return None
    if kind == "ts?":
        return int(_int(value, (0, BIG), where))
    if kind in ("int", "int?"):
        return _int(value, arg, where)
    if not isinstance(value, str):
        raise SchemaError(f"{where}: expected text")
    if kind == "text":
        return clean_text(value, arg)
    if kind == "re" and arg.fullmatch(value) is None:
        raise SchemaError(f"{where}: invalid format")
    if kind == "enum" and value not in arg:
        raise SchemaError(f"{where}: unknown value")
    return value


def _entry(raw, fields: dict, where: str) -> dict:
    if not isinstance(raw, dict):
        raise SchemaError(f"{where}: expected an object")
    out = {}
    for name, (kind, arg, required) in fields.items():
        if name not in raw or (raw[name] is None and not kind.endswith("?")):
            if required:
                raise SchemaError(f"{where}.{name}: missing")
            continue
        out[name] = _field(raw[name], kind, arg, f"{where}.{name}")
    return out


def _section(doc: dict, name: str) -> list[dict]:
    raw = doc.get(name)
    if not isinstance(raw, list):
        raise SchemaError(f"{name}: expected a list")
    if len(raw) > MAX_LIST[name]:
        raise SchemaError(f"{name}: more than {MAX_LIST[name]} entries")
    out = [_entry(item, SECTIONS[name], f"{name}[{index}]") for index, item in enumerate(raw)]
    key = UNIQUE.get(name)
    if key and len({item[key] for item in out}) != len(out):
        raise SchemaError(f"{name}: duplicate {key}")
    return out


def _generated_seconds(stamp: str) -> int | None:
    """Unix seconds of a ``generated`` stamp, ``None`` when it is no calendar time (the collector refuses those itself)."""
    try:
        moment = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None  # not a calendar time: the collector refuses the document on its own (`remote._epoch`)
    return int(moment.replace(tzinfo=dt.timezone.utc).timestamp())


def _clamp_last_active(doc: dict) -> None:
    """A real exporter never reports activity after it generated the document: a later ``lastActive`` becomes ``generated``."""
    generated = _generated_seconds(doc["generated"])
    if generated is None:
        return
    for entry in doc["bots"]:
        if entry.get("lastActive") is not None and entry["lastActive"] > generated:
            entry["lastActive"] = generated


def validate(doc) -> dict:
    """Return the cleaned copy of a document, or raise :class:`SchemaError`. Unknown fields are dropped."""
    if not isinstance(doc, dict):
        raise SchemaError("document: expected an object")
    if doc.get("schema") != SCHEMA:
        raise SchemaError("schema: unsupported")
    source, generated, version = doc.get("source"), doc.get("generated"), doc.get("pixelhq")
    if not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise SchemaError("source: invalid label")
    if not isinstance(generated, str) or STAMP_RE.fullmatch(generated) is None:
        raise SchemaError("generated: expected an ISO-8601 UTC time")
    seconds = _generated_seconds(generated)
    if seconds is not None and seconds < 0:  # R5-D11: keeps the lastActive clamp inside the schema range
        raise SchemaError("generated: before 1970-01-01T00:00:00Z")
    if not isinstance(version, str):
        raise SchemaError("pixelhq: expected text")
    warnings = doc.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise SchemaError("warnings: expected a list of text")
    if len(warnings) > MAX_WARNINGS:
        raise SchemaError(f"warnings: more than {MAX_WARNINGS} entries")
    out = {"schema": SCHEMA, "source": source, "generated": generated, "pixelhq": clean_text(version, 32)}
    for name in SECTIONS:
        out[name] = _section(doc, name)
    out["warnings"] = [clean_text(item, MAX_WARNING) for item in warnings]
    _clamp_last_active(out)
    return out
