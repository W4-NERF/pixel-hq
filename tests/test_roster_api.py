"""The roster route validates real profiles and invalidates even in-flight snapshots."""
import asyncio

import httpx

from dashboard import plugin_api as api
from tests.test_review_api import app  # noqa: F401
from tests.test_roster_save import body, target  # noqa: F401


def test_roster_route_save_backup_reset_and_fresh_snapshot(app, fleet, body):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = (await client.get("/snapshot")).json()
            assert first["cfg"]["rosterSource"] == "file"
            cached, original = api._cache["data"], target(fleet.root).read_bytes()
            bad = await client.post("/roster", json={"roster": {}})
            assert bad.status_code == 200 and bad.json()["ok"] is False
            assert api._cache["data"] is cached
            body["roster"]["bots"][0]["title"] = "Senior engineer"
            result = await client.post("/roster", json=body)
            assert result.status_code == 200 and result.json() == {"ok": True, "message": "Roster saved."}
            assert api._cache["data"] is None
            assert target(fleet.root).with_suffix(".json.bak").read_bytes() == original
            fresh = (await client.get("/snapshot")).json()
            bot = next(b for b in fresh["bots"] if b["id"] == "ops-bot")
            assert bot["title"] == "Senior engineer" and bot["leader"] is True
            # A stale non-remote profile cannot be saved; a remote bot does not need a local profile.
            body["roster"]["bots"][0]["id"] = "unknown"
            assert not (await client.post("/roster", json=body)).json()["ok"]
            body["roster"]["bots"][0]["remote"] = True
            assert (await client.post("/roster", json=body)).json()["ok"]
            assert (await client.post("/roster", json={"reset": True})).json()["ok"]
            assert api._cache["data"] is None
            reset = (await client.get("/snapshot")).json()
            assert reset["cfg"]["rosterSource"] == "generated"
            assert {b["id"] for b in reset["bots"]} == {"default", "ops-bot"}
    asyncio.run(scenario())


def test_roster_waits_for_inflight_snapshot(app, body):
    async def scenario():
        api._cache["data"] = {"old": True}
        await api._lock.acquire()
        pending = asyncio.create_task(api.roster(body))
        await asyncio.sleep(0)
        assert not pending.done()
        api._lock.release()
        result = await pending
        assert result["ok"] and api._cache["data"] is None
    assert hasattr(api, "roster"), "POST /roster handler is missing"
    asyncio.run(scenario())


def test_roster_io_failure_preserves_snapshot(app, fleet, body):
    target(fleet.root).unlink()
    target(fleet.root).mkdir()
    cached = {"old": True}
    api._cache["data"] = cached
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.post("/roster", json=body)
            assert result.status_code == 200 and result.json()["ok"] is False
            assert api._cache["data"] is cached
    asyncio.run(scenario())
