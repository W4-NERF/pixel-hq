"""Pixel HQ settings: defaults < optional ``config.json`` < Hermes plugin settings.

Site-specific files (``config.json``, ``roster.json``) are read from
``$HERMES_HOME/plugin-data/pixel-hq/`` only (default ``~/.hermes/plugin-data/pixel-hq/`` — survives plugin updates).
``config.example.json`` and ``roster.example.json`` document every key. Nothing in this package
hard-codes hosts, IPs or people.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import unicodedata

try:
    from hermes_cli.config import load_config_readonly
except ImportError:
    def load_config_readonly() -> dict:
        return {}

HERE = Path(__file__).resolve().parent
SPRITE_VARIANTS = ("default", "wizard", "knight", "engineer", "scout", "medic", "scribe", "rogue")
_VERSION_LINE = re.compile(r"^version:[ \t]*[\"']?([^\"'#\s]+)", re.MULTILINE)


def disk_version() -> str:
    """Version in ``plugin.yaml`` as it is on disk right now; empty when unreadable."""
    try:
        found = _VERSION_LINE.search((HERE.parent / "plugin.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return ""
    return found.group(1) if found else ""


# Fixed when this module is executed, i.e. when the backend process loaded the plugin files.
LOADED_VERSION = disk_version()


def root_home() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    return home.parent.parent if home.parent.name == "profiles" else home


_DIRS: list[Path] | None = None  # optional explicit lookup override for standalone callers


def site_file(name: str) -> Path | None:
    for d in (_DIRS if _DIRS is not None else [root_home() / "plugin-data" / "pixel-hq"]):
        if (d / name).exists():
            return d / name
    return None


# One text rule for labels: the server check (roster.py) and the editor's pre-check (app.js, built from
# ``public()["textRule"]``) both derive from this definition. Rejected: Unicode categories Cc, Cs, Cn, Co and the
# bidi overrides U+202A–U+202E / U+2066–U+2069. Other format characters (ZWJ, ZWNJ, emoji sequences) are allowed.
TEXT_RULE = {"categories": ["Cc", "Cs", "Cn", "Co"], "ranges": [[0x202A, 0x202E], [0x2066, 0x2069]],
             "message": "control or bidi-override characters"}


def text_rejected(text: str) -> bool:
    """True when ``text`` holds a character the shared text rule refuses."""
    return any(unicodedata.category(ch) in TEXT_RULE["categories"]
               or any(lo <= ord(ch) <= hi for lo, hi in TEXT_RULE["ranges"]) for ch in text)


DEFAULTS: dict = {
    # Display
    "locale": "en-GB",                  # number/date formatting in the UI (BCP 47)
    "timezone": "UTC",                  # IANA zone for clocks in the UI
    "theme_label": "PIXEL HQ",
    "appearance": "auto",              # auto follows the host; dark/light override it
    # People / roles
    "operator_name": "operator",        # shown as author of comments written from the UI
    "orchestrator_profile": "default",  # owns unattributed helper XP and receives triage runs
    # Paths (``~`` allowed)
    "reviews_path": "",                 # empty resolves to <root>/plugin-data/pixel-hq/reviews.jsonl
    "legacy_ledger_path": "",           # optional, read-only older ledger
    # Kanban
    "kanban_xp": True,
    "exclude_boards": [],               # board slugs hidden from every view (e.g. a sandbox board)
    "stale_days": 14,
    # Blocked cards whose title/reason contains one of these words are filed under "waiting for you"
    "needs_input_keywords": ["approval", "approve", "decision", "sign-off", "gate", "waiting for", "go"],
    # Gamification
    "xp_pass": 10, "xp_revise": 3, "xp_fail": -5,
    # GPU / LLM serving ("reactor"). Leave prometheus_url empty to hide the reactor.
    "prometheus_url": "", "metrics_prefix": "vllm", "node_aliases": {}, "model_endpoint": "",
}


def _flat_settings(settings: dict) -> dict:
    """Map legacy nested settings; an explicit flat key wins within the same file."""
    if not isinstance(settings, dict):
        raise ValueError("expected a settings object")
    out = copy.deepcopy(settings)
    for group, mapping in (
        ("xp", {key: "xp_" + key for key in ("pass", "revise", "fail")}),
        ("gpu", {key: key for key in ("prometheus_url", "metrics_prefix", "node_aliases", "model_endpoint")}),
    ):
        nested = out.pop(group, None)
        if isinstance(nested, dict):
            for key, flat in mapping.items():
                if key in nested:
                    out.setdefault(flat, nested[key])
    if "ledger_path" in out:
        out.setdefault("legacy_ledger_path", out.pop("ledger_path"))
    return out


def _coerce(value, expected: type):
    """Coerce scalar settings without truthiness traps or unsafe list members."""
    if expected is bool:
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ("true", "yes", "on", "1"):
                return True
            if value in ("false", "no", "off", "0"):
                return False
        elif type(value) in (bool, int) and value in (0, 1):
            return bool(value)
    elif expected is int:
        if type(value) in (str, int, float) and not isinstance(value, bool):
            number = int(value)
            if not isinstance(value, float) or number == value:
                return number
    elif expected is list:
        value = [value] if isinstance(value, str) else value
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
    elif expected is dict:
        value = json.loads(value) if isinstance(value, str) else value
        if isinstance(value, dict):
            return copy.deepcopy(value)
    elif expected is str and type(value) in (str, int, float, bool):
        return str(value)
    raise ValueError("invalid setting type")


def _normalise(cfg: dict) -> None:
    """A malformed key cannot invalidate its readable siblings or the whole page."""
    cfg["warnings"] = []
    for key, default in DEFAULTS.items():
        try:
            cfg[key] = _coerce(cfg[key], type(default))
        except (TypeError, ValueError, OverflowError, RecursionError):
            cfg[key] = copy.deepcopy(default)
            message = f"{key}: expected {type(default).__name__}"
            cfg["warnings"].append(message)
            cfg.setdefault("config_error", message)
    if cfg["appearance"] not in ("auto", "dark", "light"):
        cfg["appearance"] = "auto"
        message = "appearance: expected auto, dark or light"
        cfg["warnings"].append(message)
        cfg.setdefault("config_error", message)


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    cfg["hermes_home"] = str(root_home())
    cfg["settings_source"] = "defaults"
    p = site_file("config.json")
    if p:
        try:
            cfg.update(_flat_settings(json.loads(p.read_text(encoding="utf-8"))))
            cfg["settings_source"] = "file"
        except Exception as exc:  # a broken config must not take the whole page down
            cfg["config_error"] = f"config.json: {str(exc)[:120]}"
    try:
        settings = load_config_readonly()
        for key in ("plugins", "entries", "pixel-hq", "settings"):
            settings = settings.get(key, {}) if isinstance(settings, dict) else {}
        if isinstance(settings, dict) and settings:
            cfg.update(_flat_settings(settings))
            cfg["settings_source"] = "hermes"
    except Exception as exc:
        # Loader errors may include private YAML contents; expose only the exception type.
        cfg.setdefault("config_error", f"Hermes settings: {type(exc).__name__}")
    _normalise(cfg)
    cfg["hermes_home"] = os.path.expanduser(cfg["hermes_home"])
    for key in ("reviews_path", "legacy_ledger_path"):
        cfg[key] = ledger_path(cfg, key)
    return cfg


def ledger_path(cfg: dict, key: str = "reviews_path") -> str:
    """Relative ledgers belong to plugin-data, not the server's working directory."""
    value = cfg.get(key) or ("reviews.jsonl" if key == "reviews_path" else "")
    if not value:
        return ""
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = Path(cfg["hermes_home"]) / "plugin-data" / "pixel-hq" / path
        # A symlinked ledger stays visible as a symlink: the writer refuses it (D19) instead of following it.
        path = path.parent.resolve() / path.name if path.is_symlink() else path.resolve()
    return str(path)


def roster_path() -> Path | None:
    return site_file("roster.json")


def _generated_roster(warnings: list[str]) -> dict:
    return {"rooms": [{"id": "hq", "label": "HEADQUARTERS", "main": True,
                       "zones": [{"id": "command", "label": "COMMAND"},
                                 {"id": "crew", "label": "CREW"}]}],
            "bots": [], "rosterSource": "generated", "warnings": warnings}


def departments(rooms: list) -> list:
    """The departments of a rooms list in file order as (room, zone) pairs; malformed entries are skipped."""
    found = []
    for room in rooms if isinstance(rooms, list) else []:
        zones = room.get("zones") if isinstance(room, dict) else None
        for zone in zones if isinstance(zones, list) else []:
            if isinstance(zone, dict) and isinstance(zone.get("id"), str) and zone["id"]:
                found.append((room, zone))
    return found


def has_department(rooms: list) -> bool:
    return bool(departments(rooms))


def load_roster() -> dict:
    warnings = []
    try:
        path = roster_path()
        if path is None:
            return _generated_roster(warnings)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a roster object")
        for key in ("rooms", "bots"):
            if not isinstance(data.setdefault(key, []), list):
                raise ValueError(f"expected a {key} list")
        bots = []
        for index, bot in enumerate(data["bots"]):
            if not isinstance(bot, dict) or not isinstance(bot.get("id"), str) or not bot["id"]:
                warnings.append(f"roster.json: bots[{index}]: expected a string id")
                continue
            if "sprite" in bot and bot["sprite"] not in SPRITE_VARIANTS:
                bot.pop("sprite")
                warnings.append(f"roster.json: bots[{index}].sprite: expected a sprite variant")
            bots.append(bot)
        data.update(bots=bots, rosterSource="file", warnings=warnings)
        if not has_department(data["rooms"]):
            raise ValueError("roster without a department")
        return data
    except (OSError, ValueError, RecursionError) as exc:
        # JSON/OS diagnostics can quote arbitrary private content or paths.
        warnings.append(f"roster.json: invalid or unreadable roster ({type(exc).__name__})")
        return _generated_roster(warnings)


def public(cfg: dict, roster: dict) -> dict:
    """Subset handed to the UI / desktop plugin (no paths except the tools dir the plugin itself needs)."""
    return {
        "locale": cfg["locale"], "timezone": cfg["timezone"], "label": cfg["theme_label"], "appearance": cfg["appearance"],
        "operator": cfg["operator_name"], "orchestrator": cfg["orchestrator_profile"],
        "xp": {verdict: cfg["xp_" + verdict] for verdict in ("pass", "revise", "fail")},
        "staleDays": cfg["stale_days"], "toolsDir": str(HERE),
        "remoteBots": [b["id"] for b in roster["bots"] if b.get("remote")],
        "rooms": roster["rooms"], "configError": cfg.get("config_error"),
        "configDir": str(Path(cfg.get("hermes_home") or root_home()) / "plugin-data" / "pixel-hq"), "usingExampleRoster": False,
        "rosterSource": roster.get("rosterSource", "file"),
        "settingsSource": cfg.get("settings_source", "defaults"), "textRule": TEXT_RULE,
        "version": LOADED_VERSION, "diskVersion": disk_version(),
    }
