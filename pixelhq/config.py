"""Pixel HQ configuration: generic defaults, overridden by an optional ``config.json``.

Site-specific files (``config.json``, ``roster.json``) are looked up in this order:
  1. ``$HERMES_HOME/plugin-data/pixel-hq/``  (default ``~/.hermes/plugin-data/pixel-hq/`` — survives plugin updates)
  2. next to this file (git-ignored; handy for a linked development checkout)
``config.example.json`` and ``roster.example.json`` document every key. Nothing in this package
hard-codes hosts, IPs or people.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
_ROOT = Path(os.path.expanduser("~/.hermes"))
_ENV_HOME = Path(os.environ["HERMES_HOME"]) if os.environ.get("HERMES_HOME") else None
# candidate data dirs: the active HERMES_HOME (profile or root), then the default root, then this folder
_DIRS = [d / "plugin-data" / "pixel-hq" for d in ([_ENV_HOME] if _ENV_HOME else []) + [_ROOT]] + [HERE]
DATA_DIR = _DIRS[0] if _ENV_HOME is None else _ROOT / "plugin-data" / "pixel-hq"


def site_file(name: str) -> Path | None:
    for d in _DIRS:
        if (d / name).exists():
            return d / name
    return None

DEFAULTS: dict = {
    # Display
    "locale": "en-GB",                  # number/date formatting in the UI (BCP 47)
    "timezone": "UTC",                  # IANA zone for clocks in the UI
    "theme_label": "PIXEL HQ",
    # People / roles
    "operator_name": "operator",        # shown as author of comments written from the UI
    "orchestrator_profile": "default",  # profile that writes the quality ledger, owns unattributed helper XP
                                        # and receives triage runs
    # Paths (``~`` allowed)
    "hermes_home": "~/.hermes",
    "ledger_path": "~/.hermes/quality/ledger.jsonl",
    # Kanban
    "exclude_boards": [],               # board slugs hidden from every view (e.g. a sandbox board)
    "stale_days": 14,
    # Blocked cards whose title/reason contains one of these words are filed under "waiting for you"
    "needs_input_keywords": ["approval", "approve", "decision", "sign-off", "gate", "waiting for", "go"],
    # Gamification
    "xp": {"pass": 10, "revise": 3, "fail": -5},
    # GPU / LLM serving ("reactor"). Leave prometheus_url empty to hide the reactor.
    "gpu": {
        "prometheus_url": "",           # e.g. http://prometheus.example:9090
        "metrics_prefix": "vllm",       # metric family prefix: vllm | tensorfold | sglang
        "node_aliases": {},             # {"prometheus instance label": "display name"}
        "model_endpoint": "",           # OpenAI-compatible base, e.g. http://llm.example:8000 → /v1/models
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = site_file("config.json")
    if p:
        try:
            cfg = _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:  # a broken config must not take the whole page down
            cfg["config_error"] = f"config.json: {str(exc)[:120]}"
    cfg["hermes_home"] = os.path.expanduser(cfg["hermes_home"])
    cfg["ledger_path"] = os.path.expanduser(cfg["ledger_path"])
    return cfg


def roster_path() -> Path:
    return site_file("roster.json") or HERE / "roster.example.json"


def load_roster() -> dict:
    data = json.loads(roster_path().read_text(encoding="utf-8"))
    data.setdefault("rooms", [])
    data.setdefault("bots", [])
    return data


def public(cfg: dict, roster: dict) -> dict:
    """Subset handed to the UI / desktop plugin (no paths except the tools dir the plugin itself needs)."""
    return {
        "locale": cfg["locale"], "timezone": cfg["timezone"], "label": cfg["theme_label"],
        "operator": cfg["operator_name"], "orchestrator": cfg["orchestrator_profile"],
        "xp": cfg["xp"], "staleDays": cfg["stale_days"], "toolsDir": str(HERE),
        "remoteBots": [b["id"] for b in roster["bots"] if b.get("remote")],
        "rooms": roster["rooms"], "configError": cfg.get("config_error"),
        "configDir": str(DATA_DIR), "usingExampleRoster": roster_path().name == "roster.example.json",
    }
