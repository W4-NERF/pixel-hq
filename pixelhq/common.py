"""Shared text bounds and read-source paths; configuration is supplied per request."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path


def clip(value, limit: int, *, collapse_whitespace: bool = False) -> str:
    """Bound text, optionally keeping the live view's single-line presentation."""
    text = str(value or "")
    if collapse_whitespace:
        text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def state_db(profile: str, cfg: dict) -> Path:
    home = Path(cfg["hermes_home"])
    return home / "state.db" if profile == "default" else home / "profiles" / profile / "state.db"


def boards(cfg: dict, candidates: Iterable[tuple[str, Path]] | None = None) -> Iterator[tuple[str, Path]]:
    """Yield sorted local databases, or supplied sources, applying the same exclusions.

    Explicit candidates retain their order and missing paths so scoring can report
    source failures instead of silently losing them.
    """
    if candidates is None:
        root = Path(cfg["hermes_home"]) / "kanban" / "boards"
        candidates = ((directory.name, directory / "kanban.db") for directory in sorted(root.glob("*/"))
                      if (directory / "kanban.db").exists())
    excluded = set(cfg.get("exclude_boards", []))
    for name, path in candidates:
        if name not in excluded:
            yield name, path
