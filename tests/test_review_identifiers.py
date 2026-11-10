"""The UI writer, tool writer and registered handler share identifier boundaries."""
import importlib
import json

import pytest

from pixelhq import config, reviews


BAD_IDS = [
    pytest.param("", id="empty"), pytest.param("sample bot", id="space"),
    pytest.param(" bot", id="leading-space"), pytest.param("bot ", id="trailing-space"),
    pytest.param("bot\n", id="trailing-newline"), pytest.param("bot\tname", id="tab"),
    pytest.param("cron:sample", id="colon"), pytest.param("helper/name", id="slash"),
    pytest.param("böt", id="unicode"), pytest.param("<sample>", id="markup"),
    pytest.param("x" * 65, id="65-chars"), pytest.param("x" * 5_000_000, id="5mb"),
    pytest.param(None, id="null"), pytest.param(42, id="integer"),
    pytest.param([], id="list"), pytest.param({}, id="object"),
]


def write_review(writer, body, cfg):
    if writer == "ui":
        # Even a malicious string present in the roster must fail format validation.
        known = {body["agent"]} if isinstance(body.get("agent"), str) else set()
        return reviews.append(body, cfg, known)
    if writer == "tool":
        return reviews.append_tool(body, cfg, "review-bot")
    return json.loads(importlib.import_module("__init__")._handle_review(body))


@pytest.mark.parametrize("writer", ["ui", "tool", "handler"])
@pytest.mark.parametrize("key", ["agent", "parent"])
@pytest.mark.parametrize("bad", BAD_IDS)
def test_invalid_identifiers_reject_without_any_ledger_write(fleet, monkeypatch, writer, key, bad):
    path = fleet.root / "new-ledger" / "reviews.jsonl"
    cfg = config.load() | {"reviews_path": str(path)}
    monkeypatch.setattr(config, "load", lambda: cfg)
    body = {"agent": "ops-bot", "verdict": "pass", key: bad}
    result = write_review(writer, body, cfg)
    assert not result.get("ok")
    message = result.get("error") or result.get("message", "")
    assert key in message.lower() and len(message) < 160
    assert not path.parent.exists()
    path.parent.mkdir()
    original = b'{"sample":true}\n'
    path.write_bytes(original)
    assert not write_review(writer, body, cfg).get("ok")
    assert path.read_bytes() == original


@pytest.mark.parametrize("writer", ["ui", "tool", "handler"])
@pytest.mark.parametrize("identifier", ["a", "A._+-09", "x" * 64])
def test_identifier_boundaries_preserve_exact_values(fleet, monkeypatch, writer, identifier):
    cfg = config.load()
    monkeypatch.setattr(config, "load", lambda: cfg)
    result = write_review(writer, {"agent": identifier, "parent": identifier, "verdict": "pass"}, cfg)
    assert result["ok"] is True
    record = json.loads(fleet.reviews_path.read_text(encoding="utf-8"))
    assert record["agent"] == identifier
    if writer == "ui":
        assert "parent" not in record  # Caller-supplied UI metadata is never trusted.
    else:
        assert record["parent"] == identifier


def test_tool_schema_documents_both_identifier_bounds():
    properties = importlib.import_module("__init__").REVIEW_SCHEMA["parameters"]["properties"]
    for key in ("agent", "parent"):
        assert properties[key]["minLength"] == 1
        assert properties[key]["maxLength"] == 64
        assert properties[key]["pattern"] == r"^[A-Za-z0-9._+-]{1,64}$"
