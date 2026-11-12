"""Pixel HQ backend: /api/plugins/pixel-hq/{snapshot,live,page,blocker/action,review,roster}.

Collector and UI live in ``<repo>/pixelhq``; the plugin folder is usually a symlink into the repo, hence
``resolve()``. The whole ``pixelhq`` directory is loaded exactly once, when this file is imported, as the
package ``pixelhq_plugin`` (see ``pixelhq_loader.py``); requests never re-execute modules, so one backend
process always runs one consistent version of the code. The routes mount when the Hermes gateway starts:
after updating Pixel HQ, restart the gateway (``hermes gateway restart``); until then the old code keeps
serving and the footer reports the stale backend. Config and roster data are read inside each
collector/live/review/action invocation, not at import time. Snapshots are cached (default 30 s), so data
edits appear on the next cache miss or invalidation; the live endpoint is uncached.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
import time
from pathlib import Path

from fastapi import APIRouter


def _loader():
    """The shared loader module: built completely first, then published with ``setdefault`` (one instance)."""
    mod = sys.modules.get("pixelhq_plugin_loader")
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            "pixelhq_plugin_loader", Path(__file__).resolve().parents[1] / "pixelhq_loader.py")
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
        mod = sys.modules.setdefault(spec.name, candidate)
    return mod


_PACKAGE = _loader().load()


def _module(name: str):
    """One module of the package loaded at start-up, e.g. ``_module("collect")``."""
    return importlib.import_module(f"{_PACKAGE.__name__}.{name}")


router = APIRouter()
_cache: dict = {"t": 0.0, "data": None}
_lock = asyncio.Lock()


@router.get("/snapshot")
async def snapshot(max_age: int = 30):
    async with _lock:
        if _cache["data"] is None or time.time() - _cache["t"] > max(5, max_age):
            _cache["data"] = await asyncio.to_thread(_module("collect").collect)
            _cache["t"] = time.time()
    return _cache["data"]


@router.get("/live")
async def live():
    """What is every bot doing right now (10-s polling, ~30 ms, uncached)."""
    return await asyncio.to_thread(_module("live").query, {})


@router.get("/page")
async def page():
    return {"html": _module("page").page_html(None)}


@router.post("/blocker/action")
async def blocker_action(body: dict):
    """Action on a blocked card (logic in pixelhq/actions.py; writes only through the kanban CLI)."""
    result = await asyncio.to_thread(_module("actions").run, body or {})
    if result.get("ok"):
        _cache["data"] = None  # next snapshot is fresh
    return result


def _append_review(body: dict) -> dict:
    collect = _module("collect")
    cfg, roster = collect.context()
    known = {bot["id"] for bot in collect.roster_bots(collect.read_profiles(cfg=cfg), roster=roster, cfg=cfg)}
    return _module("reviews").append(body, cfg, known)


@router.post("/review")
async def review(body: dict):
    """Write only to the review JSONL, then invalidate even an in-flight snapshot."""
    async with _lock:
        result = await asyncio.to_thread(_append_review, body)
        if result.get("ok"):
            _cache["data"] = None
    return result


def _save_roster(body: dict) -> dict:
    collect = _module("collect")
    cfg = collect.cfgmod.load()
    profiles = collect.read_profiles(cfg=cfg)
    return _module("roster").save(body, cfg, profiles)


@router.post("/roster")
async def roster(body: dict):
    """Save only the fixed plugin-data roster; serialize writes with snapshot collection."""
    async with _lock:
        result = await asyncio.to_thread(_save_roster, body)
        if result.get("ok"):
            _cache["data"] = None
    return result
