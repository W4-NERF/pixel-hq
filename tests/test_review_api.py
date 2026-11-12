"""Exercise the real REST router against an invented on-disk installation."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from dashboard import plugin_api as api


@pytest.fixture
def app(fleet, monkeypatch):
    # Redirect only the fixture's config lookup; keep collection, roster and I/O real.
    monkeypatch.setattr(api._module("config"), "_DIRS", [fleet.root / "plugin-data" / "pixel-hq"])
    monkeypatch.setattr(api, "_cache", {"t": 0.0, "data": None})
    monkeypatch.setattr(api, "_lock", asyncio.Lock())
    app = FastAPI()
    app.include_router(api.router)
    return app


def test_review_route_appends_and_refreshes_cached_score(app, fleet):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = (await client.get("/snapshot")).json()
            original = api._cache["data"]
            assert next(b for b in first["bots"] if b["id"] == "ops-bot")["xp"] == 0
            bad = await client.post("/review", json={"agent": "unknown-bot", "verdict": "pass"})
            assert bad.status_code == 200 and bad.json()["ok"] is False
            assert api._cache["data"] is original
            assert not fleet.reviews_path.exists()
            result = await client.post("/review", json={"agent": "ops-bot", "verdict": "pass",
                                                       "dims": {"safety": 5}, "ref": "Sample verification"})
            assert result.status_code == 200 and result.json()["ok"] is True
            assert api._cache["data"] is None
            record = json.loads(fleet.reviews_path.read_text(encoding="utf-8"))
            assert record["source"] == "ui" and record["reviewer"] == "operator"
            fresh = (await client.get("/snapshot")).json()
            bot = next(b for b in fresh["bots"] if b["id"] == "ops-bot")
            assert bot["xp"] == 10 and bot["xpBySource"]["reviews"] == 10
            assert bot["attrsSource"] == "reviews"
            # Remote roster entries and generated recruits are known, nonexistent profiles are not.
            assert (await client.post("/review", json={"agent": "remote-bot", "verdict": "revise"})).json()["ok"]
            recruit = fleet.root / "profiles" / "new-bot"
            recruit.mkdir()
            (recruit / "config.yaml").write_text("model:\n  default: sample/model\n", encoding="utf-8")
            assert (await client.post("/review", json={"agent": "new-bot", "verdict": "fail"})).json()["ok"]
    asyncio.run(scenario())


def test_review_serializes_with_an_inflight_snapshot(app):
    async def scenario():
        original = {"old": True}
        api._cache["data"] = original
        await api._lock.acquire()
        pending = asyncio.create_task(api.review({"agent": "ops-bot", "verdict": "pass"}))
        await asyncio.sleep(0)
        assert not pending.done()
        api._lock.release()
        result = await pending
        assert result["ok"] and api._cache["data"] is None
    assert hasattr(api, "review"), "POST /review handler is missing"
    asyncio.run(scenario())


def test_review_io_failure_keeps_the_cache(app, fleet):
    fleet.reviews_path.mkdir()
    original = {"old": True}
    api._cache["data"] = original
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/review", json={"agent": "ops-bot", "verdict": "pass"})
            assert response.status_code == 200 and response.json()["ok"] is False
            assert api._cache["data"] is original
    asyncio.run(scenario())


def test_a_blocker_action_during_a_snapshot_leaves_no_stale_cache(app, monkeypatch):
    """The snapshot that was collecting while the CLI ran must not be served afterwards as fresh data."""
    import threading

    started, release = threading.Event(), threading.Event()

    def slow_collect():
        started.set()
        release.wait(5)
        return {"collected": "before the action"}

    monkeypatch.setattr(api._module("collect"), "collect", slow_collect)
    monkeypatch.setattr(api._module("actions"), "run", lambda body: {"ok": True})

    async def scenario():
        snapshot = asyncio.create_task(api.snapshot(max_age=30))
        while not started.is_set():
            await asyncio.sleep(0.01)
        action = asyncio.create_task(api.blocker_action({"board": "platform"}))
        for _ in range(20):  # let the action's worker thread finish while the snapshot still collects
            await asyncio.sleep(0.01)
        release.set()
        assert (await snapshot) == {"collected": "before the action"}
        assert (await action)["ok"] is True
        assert api._cache["data"] is None

    asyncio.run(scenario())
