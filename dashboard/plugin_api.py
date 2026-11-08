"""Pixel HQ backend: /api/plugins/pixel-hq/{snapshot,live,page,blocker/action}.

Collector and UI live in ``<repo>/pixelhq``; the plugin folder is usually a symlink into the repo, hence
``resolve()``. Modules are re-imported per request so config/roster/rule changes apply without a restart
(only this file needs a desktop-app restart). The snapshot is cached (default 30 s) so several windows
or refreshes do not run the ~3 s collector in parallel.
"""
from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path

from fastapi import APIRouter

_PIXELHQ = Path(__file__).resolve().parents[1] / "pixelhq"


def _load(name: str, fn: str):
    spec = importlib.util.spec_from_file_location(name, _PIXELHQ / fn)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


router = APIRouter()
_cache: dict = {"t": 0.0, "data": None}
_lock = asyncio.Lock()


@router.get("/snapshot")
async def snapshot(max_age: int = 30):
    async with _lock:
        if _cache["data"] is None or time.time() - _cache["t"] > max(5, max_age):
            collect = _load("pixelhq_collect", "collect.py")
            _cache["data"] = await asyncio.to_thread(collect.collect)
            _cache["t"] = time.time()
    return _cache["data"]


@router.get("/live")
async def live():
    """What is every bot doing right now (10-s polling, ~30 ms, uncached)."""
    return await asyncio.to_thread(_load("pixelhq_live", "live.py").query, {})


@router.get("/page")
async def page():
    return {"html": _load("pixelhq_page", "page.py").page_html(None)}


@router.post("/blocker/action")
async def blocker_action(body: dict):
    """Action on a blocked card (logic in pixelhq/actions.py; writes only through the kanban CLI)."""
    result = await asyncio.to_thread(_load("pixelhq_actions", "actions.py").run, body or {})
    if result.get("ok"):
        _cache["data"] = None  # next snapshot is fresh
    return result
