"""Broken roster files and settings are isolated at request boundaries, not imports."""
import asyncio
import importlib
import json

import httpx
import pytest
from fastapi import FastAPI

from pixelhq import config


@pytest.mark.parametrize("payload", ["{not json", "[]", "null", "42", '{"bots": {}}', '{"rooms": null}'])
def test_import_then_collect_with_broken_roster_warns_and_generates(fleet, monkeypatch, payload):
    path = fleet.root / "plugin-data" / "pixel-hq" / "roster.json"
    path.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(config, "_DIRS", [path.parent])
    collect = importlib.reload(importlib.import_module("pixelhq.collect"))
    data = collect.collect()
    assert {bot["id"] for bot in data["bots"]} == {"default", "ops-bot"}
    assert data["cfg"]["rosterSource"] == "generated"
    assert any("roster.json" in warning for warning in data["warnings"])
    assert all(len(warning) <= 120 for warning in data["warnings"])


@pytest.mark.parametrize("bad_bot", [{}, {"id": None}, {"id": 42}, {"id": []}, "sample", None])
def test_bad_roster_entry_is_skipped_without_losing_valid_remote(fleet, monkeypatch, bad_bot):
    from pixelhq import collect, live

    data = fleet.root / "plugin-data" / "pixel-hq"
    monkeypatch.setattr(config, "_DIRS", [data])
    path = data / "roster.json"
    roster = json.loads(path.read_text(encoding="utf-8"))
    roster["bots"].append(bad_bot)
    path.write_text(json.dumps(roster), encoding="utf-8")
    for snapshot in (collect.collect(), live.query()):
        bots = snapshot["bots"]
        assert (set(bots) if isinstance(bots, dict) else {bot["id"] for bot in bots}) == {
            "default", "ops-bot", "remote-bot"}
        assert any("roster.json" in warning and "id" in warning for warning in snapshot["warnings"])


@pytest.mark.parametrize("module_name", ["collect", "live", "actions"])
def test_imports_do_not_load_settings_or_roster(monkeypatch, module_name):
    def not_during_import():
        pytest.fail("Configuration and roster must only be read inside a request")
    monkeypatch.setattr(config, "load", not_during_import)
    monkeypatch.setattr(config, "load_roster", not_during_import)
    importlib.reload(importlib.import_module("pixelhq." + module_name))


def test_imported_modules_reload_config_and_roster_on_each_request(fleet, monkeypatch):
    from pixelhq import collect, live

    data = fleet.root / "plugin-data" / "pixel-hq"
    monkeypatch.setattr(config, "_DIRS", [data])
    assert len(collect.collect()["bots"]) == 3
    assert len(live.query()["bots"]) == 3
    (data / "roster.json").write_text("{invalid", encoding="utf-8")
    (data / "config.json").write_text('{"xp_pass":"invalid","stale_days":"invalid"}', encoding="utf-8")
    for snapshot in (collect.collect(), live.query()):
        assert len(snapshot["bots"]) == 2
        assert "xp_pass: expected int" in snapshot["warnings"]
        assert "stale_days: expected int" in snapshot["warnings"]
        assert any("roster.json" in warning for warning in snapshot["warnings"])
    (data / "roster.json").unlink()
    (data / "config.json").write_text('{"orchestrator_profile":"ops-bot"}', encoding="utf-8")
    current = collect.collect()
    assert current["warnings"] == []
    assert next(bot for bot in current["bots"] if bot["id"] == "ops-bot")["zone"] == "command"


def test_site_lookup_tracks_root_home_after_module_import(fleet, monkeypatch):
    from pixelhq import collect

    monkeypatch.setattr(config, "_DIRS", None)
    result = collect.collect()
    assert result["cfg"]["rosterSource"] == "file"
    assert len(result["bots"]) == 3
    assert result["cfg"]["configDir"] == str(fleet.root / "plugin-data" / "pixel-hq")


@pytest.mark.parametrize("payload", ["{not json", "[]", '{"bots": [{}, {"id":42}]}'])
def test_snapshot_live_and_review_routes_survive_broken_roster(fleet, monkeypatch, payload):
    from dashboard import plugin_api as api

    data = fleet.root / "plugin-data" / "pixel-hq"
    (data / "roster.json").write_text(payload, encoding="utf-8")
    monkeypatch.setattr(config, "_DIRS", None)
    monkeypatch.setattr(api, "_cache", {"t": 0.0, "data": None})
    monkeypatch.setattr(api, "_lock", asyncio.Lock())
    app = FastAPI()
    app.include_router(api.router)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for route in ("/snapshot", "/live"):
                response = await client.get(route)
                assert response.status_code == 200
                assert any("roster.json" in warning for warning in response.json()["warnings"])
            response = await client.post("/review", json={"agent": "ops-bot", "verdict": "pass"})
            assert response.status_code == 200 and response.json()["ok"]
            fresh = (await client.get("/snapshot")).json()
            assert next(bot for bot in fresh["bots"] if bot["id"] == "ops-bot")["xp"] == 10
    asyncio.run(scenario())
