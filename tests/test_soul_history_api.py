"""The SOUL history routes: same refusal style as /roster, never a 500 for bad input, never a path in a message."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from dashboard import plugin_api as api
from tests.test_review_api import app  # noqa: F401

ITEM_ID = "20261112T100000Z-00000001000000000000000000000000.md"


def rid(n: int = 1) -> str:
    return f"{n:08x}" + "0" * 24


def save_body(text="You are a careful reviewer.", n=1, bot="ops-bot", source="local"):
    return {"bot": bot, "sourceKey": source, "text": text, "rid": rid(n)}


def history_dir(fleet, source="local", bot="ops-bot") -> Path:
    return fleet.root / "plugin-data" / "pixel-hq" / "soul-history" / source / bot


@asynccontextmanager
async def client_for(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def run(app, scenario):
    async def main():
        async with client_for(app) as client:
            await scenario(client)
    asyncio.run(main())


def test_the_three_routes_are_mounted_with_their_methods(app):
    seen = {(route.path, method) for route in api.router.routes for method in route.methods}
    assert {("/soul-history", "POST"), ("/soul-history", "GET"), ("/soul-history/item", "GET")} <= seen


def test_save_list_item_round_trip_through_the_routes(app, fleet):
    async def scenario(client):
        first = await client.post("/soul-history", json=save_body("# First\nline", 1))
        assert first.status_code == 200 and first.json() == {"ok": True, "message": "SOUL version saved."}
        second = await client.post("/soul-history", json=save_body("Second \u00e9\r\nline", 2))
        assert second.json()["ok"] is True
        listed = await client.get("/soul-history", params={"bot": "ops-bot", "sourceKey": "local"})
        rows = listed.json()
        assert listed.status_code == 200 and isinstance(rows, list) and len(rows) == 2
        assert set(rows[0]) == {"id", "savedAt", "bytes", "firstLine"}
        assert {row["firstLine"] for row in rows} == {"# First", "Second \u00e9"}
        texts = {}
        for row in rows:
            got = await client.get("/soul-history/item", params={"bot": "ops-bot", "sourceKey": "local", "id": row["id"]})
            assert got.status_code == 200 and set(got.json()) == {"text"}
            texts[row["firstLine"]] = got.json()["text"]
        assert texts == {"# First": "# First\nline", "Second \u00e9": "Second \u00e9\nline"}
        assert len(list(history_dir(fleet).iterdir())) == 2
    run(app, scenario)


def test_an_empty_history_lists_as_an_empty_array(app):
    async def scenario(client):
        got = await client.get("/soul-history", params={"bot": "ops-bot", "sourceKey": "local"})
        assert got.status_code == 200 and got.json() == []
    run(app, scenario)


def test_a_retried_request_id_is_idempotent_over_http(app, fleet):
    async def scenario(client):
        assert (await client.post("/soul-history", json=save_body(n=3))).json()["message"] == "SOUL version saved."
        again = await client.post("/soul-history", json=save_body("other text", n=3))
        assert again.status_code == 200 and again.json() == {"ok": True, "message": "SOUL version already saved."}
        assert len(list(history_dir(fleet).iterdir())) == 1
    run(app, scenario)


def test_twelve_saves_keep_ten_through_the_route(app, fleet):
    async def scenario(client):
        for n in range(12):
            assert (await client.post("/soul-history", json=save_body(f"v{n}", n + 1))).json()["ok"]
        assert len(list(history_dir(fleet).iterdir())) == 10
    run(app, scenario)


@pytest.mark.parametrize("change", [
    {"bot": "../escape"}, {"bot": ""}, {"bot": None}, {"bot": 5}, {"sourceKey": "../escape"}, {"sourceKey": "a/b"},
    {"sourceKey": "x" * 65}, {"sourceKey": "\u212a"}, {"rid": "short"}, {"rid": None}, {"rid": "Z" * 16},
    {"text": None}, {"text": 7}, {"text": "bad\x00nul"}, {"text": "bad\x1bescape"}, {"text": "a" * 65537}])
def test_invalid_save_input_is_400_with_a_short_message_and_writes_nothing(app, fleet, change):
    async def scenario(client):
        before = api._cache["data"]
        result = await client.post("/soul-history", json={**save_body(), **change})
        payload = result.json()
        assert result.status_code == 400 and payload["ok"] is False and set(payload) == {"ok", "message"}
        assert 0 < len(payload["message"]) < 120
        assert str(fleet.root) not in payload["message"] and "escape" not in payload["message"]
        assert not (fleet.root / "plugin-data" / "pixel-hq" / "soul-history").exists()
        assert api._cache["data"] is before
    run(app, scenario)


@pytest.mark.parametrize("missing", ["bot", "sourceKey", "text", "rid"])
def test_a_missing_save_field_is_400(app, missing):
    async def scenario(client):
        data = {k: v for k, v in save_body().items() if k != missing}
        result = await client.post("/soul-history", json=data)
        assert result.status_code == 400 and result.json()["ok"] is False
    run(app, scenario)


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", b"null", b'"text"', b"42", b"\xff\xfe", b"[" * 100000,
                                 b'{"text": "' + b"x" * (600 * 1024) + b'"}'])
def test_malformed_or_oversized_bodies_are_400_never_500(app, raw):
    async def scenario(client):
        result = await client.post("/soul-history", content=raw, headers={"content-type": "application/json"})
        assert result.status_code == 400 and result.json()["ok"] is False
    run(app, scenario)


def test_a_body_cannot_choose_the_location(app, fleet, tmp_path):
    async def scenario(client):
        data = {**save_body(), "path": str(tmp_path / "chosen"), "hermes_home": str(tmp_path / "other"), "dir": "../x"}
        assert (await client.post("/soul-history", json=data)).status_code == 200
        assert not (tmp_path / "chosen").exists() and not (tmp_path / "other").exists()
        assert len(list(history_dir(fleet).iterdir())) == 1
    run(app, scenario)


@pytest.mark.parametrize("params", [
    {}, {"bot": "ops-bot"}, {"sourceKey": "local"}, {"bot": "../x", "sourceKey": "local"},
    {"bot": "ops-bot", "sourceKey": "..%2f"}, {"bot": "ops bot", "sourceKey": "local"}, {"bot": "a" * 65, "sourceKey": "local"}])
def test_invalid_list_query_is_400(app, params):
    async def scenario(client):
        result = await client.get("/soul-history", params=params)
        assert result.status_code == 400 and result.json()["ok"] is False
    run(app, scenario)


def test_item_unlisted_is_404_and_crafted_ids_are_400(app, fleet):
    async def scenario(client):
        await client.post("/soul-history", json=save_body("x", 1))
        base = {"bot": "ops-bot", "sourceKey": "local"}
        missing = await client.get("/soul-history/item", params={**base, "id": "20261112T100000Z-0000ffff000000000000000000000000.md"})
        assert missing.status_code == 404 and missing.json() == {"ok": False, "message": "No such version."}
        other = await client.get("/soul-history/item", params={"bot": "other-bot", "sourceKey": "local", "id": ITEM_ID})
        assert other.status_code == 404
        for crafted in ["", "..", "../" + ITEM_ID, ITEM_ID + "/", "/" + ITEM_ID, "local/ops-bot/" + ITEM_ID,
                        ITEM_ID[:-3], ITEM_ID.upper(), ITEM_ID + "%00", "*.md", ITEM_ID + "/../../x"]:
            result = await client.get("/soul-history/item", params={**base, "id": crafted})
            assert result.status_code == 400, crafted
            assert result.json()["ok"] is False and str(fleet.root) not in result.json()["message"]
        no_id = await client.get("/soul-history/item", params=base)
        assert no_id.status_code == 400
        bad_bot = await client.get("/soul-history/item", params={"bot": "../x", "sourceKey": "local", "id": ITEM_ID})
        assert bad_bot.status_code == 400
    run(app, scenario)


def test_symlinked_store_is_refused_without_a_path_and_without_writing_through_it(app, fleet, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    root = fleet.root / "plugin-data" / "pixel-hq" / "soul-history"
    root.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, root)

    async def scenario(client):
        result = await client.post("/soul-history", json=save_body())
        assert result.status_code == 409 and result.json()["ok"] is False
        assert str(tmp_path) not in result.json()["message"] and str(fleet.root) not in result.json()["message"]
        listed = await client.get("/soul-history", params={"bot": "ops-bot", "sourceKey": "local"})
        assert listed.status_code == 409
        assert not list(target.rglob("*"))
    run(app, scenario)


def test_unwritable_store_is_a_handled_500_without_diagnostics(app, fleet, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("read-only file system at /private/place")
    monkeypatch.setattr(os, "replace", broken)

    async def scenario(client):
        result = await client.post("/soul-history", json=save_body())
        assert result.status_code == 500 and result.json()["ok"] is False
        assert "/private" not in result.json()["message"] and "read-only" not in result.json()["message"]
    run(app, scenario)


def test_soul_history_does_not_touch_the_snapshot_cache(app, fleet):
    async def scenario(client):
        await client.get("/snapshot")
        cached = api._cache["data"]
        assert cached is not None
        await client.post("/soul-history", json=save_body())
        await client.get("/soul-history", params={"bot": "ops-bot", "sourceKey": "local"})
        assert api._cache["data"] is cached
    run(app, scenario)


def test_soul_history_does_not_wait_for_a_running_snapshot(app):
    async def scenario(client):
        await api._lock.acquire()
        try:
            result = await asyncio.wait_for(client.post("/soul-history", json=save_body()), timeout=5)
            assert result.status_code == 200
        finally:
            api._lock.release()
    run(app, scenario)


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_a_save_without_a_json_content_type_is_415_and_writes_nothing(app, fleet, content_type):
    """A simple cross-origin request (no CORS preflight) cannot reach the SOUL history store."""
    import json

    async def scenario(client):
        headers = {"content-type": content_type} if content_type else {}
        result = await client.post("/soul-history", content=json.dumps(save_body()).encode(), headers=headers)
        assert result.status_code == 415 and result.json() == {"ok": False, "message": "body: expected application/json."}
        assert not history_dir(fleet).exists()
    run(app, scenario)


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "Application/JSON", "application/merge+json"])
def test_json_media_types_with_parameters_are_accepted(app, fleet, content_type):
    import json

    async def scenario(client):
        result = await client.post("/soul-history", content=json.dumps(save_body()).encode(),
                                   headers={"content-type": content_type})
        assert result.status_code == 200 and result.json()["ok"] is True
    run(app, scenario)
