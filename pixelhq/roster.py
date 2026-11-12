"""Validate and atomically save the operator's roster under plugin-data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .config import SPRITE_VARIANTS, TEXT_RULE, text_rejected
from .profiles import root_home


ROOM_KEYS = ("id", "label", "main", "zones", "note")
ZONE_KEYS = ("id", "label", "quarantine")
BOT_KEYS = ("id", "cls", "title", "zone", "loc", "color", "leader", "remote", "sprite")
MAX_ROOMS, MAX_ZONES, MAX_BOTS = 8, 24, 200


ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")        # bot ids (profile names) keep the dot
GROUP_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")   # room and zone ids: no dot
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _require(condition: bool, field: str, rule: str) -> None:
    if not condition:
        raise ValueError(f"{field}: {rule}.")


def _id(value, field: str, pattern=ID_RE) -> None:
    dot = "._-" if pattern is ID_RE else "_-"
    _require(isinstance(value, str) and pattern.fullmatch(value) is not None,
             field, f"use 1–64 ASCII letters, digits or {dot} only")


def _text(value, field: str, limit: int = 40) -> None:
    _require(isinstance(value, str) and len(value) <= limit and not text_rejected(value),
             field, f"use at most {limit} characters without {TEXT_RULE['message']}")


def _flags(value: dict, fields, prefix: str) -> None:
    for field in fields:
        if field in value:
            _require(type(value[field]) is bool, prefix + "." + field, "expected a boolean")


def _unique_id(value: dict, field: str, seen: set, pattern=ID_RE) -> None:
    _id(value.get("id"), field, pattern)
    _require(value["id"] not in seen, field, "duplicate id")
    seen.add(value["id"])


def _entry(value, prefix: str) -> str:
    _require(isinstance(value, dict), prefix, "expected an object")
    if isinstance(value.get("id"), str):
        prefix += f' (id {json.dumps(value["id"], ensure_ascii=True)})'
    return prefix


def _rooms(rooms) -> set:
    _require(isinstance(rooms, list), "rooms", "expected a list")
    _require(len(rooms) <= MAX_ROOMS, "rooms", f"at most {MAX_ROOMS} rooms")
    room_ids, zone_ids, mains = set(), set(), 0
    for index, room in enumerate(rooms):
        prefix = _entry(room, f"rooms[{index}]")
        _unique_id(room, prefix + ".id", room_ids, GROUP_ID_RE)
        _text(room.get("label"), prefix + ".label")
        if "note" in room:
            _text(room["note"], prefix + ".note", 80)
        _flags(room, ("main",), prefix)
        mains += room.get("main", False)
        zones = room.get("zones")
        _require(isinstance(zones, list), prefix + ".zones", "expected a list")
        _require(len(zone_ids) + len(zones) <= MAX_ZONES, prefix + ".zones",
                 f"at most {MAX_ZONES} departments in total")
        for zi, zone in enumerate(zones):
            zp = _entry(zone, f"{prefix}.zones[{zi}]")
            _unique_id(zone, zp + ".id", zone_ids, GROUP_ID_RE)
            _text(zone.get("label"), zp + ".label")
            _flags(zone, ("quarantine",), zp)
    _require(mains == 1, "rooms.main", "exactly one main room is required")
    return zone_ids


def _bots(bots, zones: set, profiles) -> None:
    _require(isinstance(bots, list), "bots", "expected a list")
    _require(len(bots) <= MAX_BOTS, "bots", f"at most {MAX_BOTS} bots")
    ids, leaders = set(), 0
    for index, bot in enumerate(bots):
        prefix = _entry(bot, f"bots[{index}]")
        _unique_id(bot, prefix + ".id", ids)
        for field in ("cls", "title"):
            _text(bot.get(field), prefix + "." + field)
        if "loc" in bot:
            _text(bot["loc"], prefix + ".loc")
        _id(bot.get("zone"), prefix + ".zone", GROUP_ID_RE)
        _require(bot["zone"] in zones, prefix + ".zone", "department does not exist")
        color = bot.get("color")
        _require(isinstance(color, str) and COLOR_RE.fullmatch(color) is not None,
                 prefix + ".color", "expected #rrggbb")
        if "sprite" in bot:
            _require(bot["sprite"] in SPRITE_VARIANTS, prefix + ".sprite", "expected a sprite variant")
        _flags(bot, ("leader", "remote"), prefix)
        leaders += bot.get("leader", False)
        _require(leaders <= 1, prefix + ".leader", "at most one leader")
        _require(bot.get("remote", False) or bot["id"] in profiles,
                 prefix + ".id", "non-remote bot must be an existing profile")


def _validated(body: dict, profiles) -> dict | None:
    _require(isinstance(body, dict), "body", "expected an object")
    _flags(body, ("reset",), "body")
    _require(not (body.get("reset") and "roster" in body), "reset", "cannot be combined with roster")
    if body.get("reset") is True:
        return None
    roster = body.get("roster")
    _require(isinstance(roster, dict), "roster", "expected an object")
    zones = _rooms(roster.get("rooms"))
    _bots(roster.get("bots"), zones, profiles)
    return _clean(roster)


def _fields(value: dict, keys) -> dict:
    return {key: value[key] for key in keys if key in value}


def _clean(roster: dict) -> dict:
    rooms = []
    for room in roster["rooms"]:
        clean = _fields(room, ROOM_KEYS)
        clean["zones"] = [_fields(zone, ZONE_KEYS) for zone in room["zones"]]
        rooms.append(clean)
    return {"rooms": rooms, "bots": [_fields(bot, BOT_KEYS) for bot in roster["bots"]]}


def _replace(path: Path, payload: bytes, prefix: str = ".roster-") -> None:
    """Keep temporary bytes in the target directory and remove them on any failure."""
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _irregular(*paths: Path) -> bool:
    """True when one of the paths exists (a dangling symlink counts) but is not a regular file."""
    for path in paths:
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            return True
    return False


def save(body: dict, cfg: dict, profiles) -> dict:
    """Validate every field before disk I/O; the body never selects a write path."""
    try:
        roster = _validated(body, profiles)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    path = Path(cfg.get("hermes_home") or root_home()) / "plugin-data" / "pixel-hq" / "roster.json"
    backup = path.with_suffix(".json.bak")
    try:
        if _irregular(path, backup):  # symlinks and special files are neither read nor replaced
            return {"ok": False, "message": "roster.json is not a regular file"}
        if roster is None:
            if path.exists():
                os.replace(path, backup)
            return {"ok": True, "message": "Roster reset to generated."}
        payload = (json.dumps(roster, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Copy the old bytes atomically; readers must never see a missing roster during Save.
            _replace(backup, path.read_bytes())
        _replace(path, payload)
    except (OSError, ValueError):
        return {"ok": False, "message": "Could not save the roster; check plugin-data permissions."}
    return {"ok": True, "message": "Roster saved."}
