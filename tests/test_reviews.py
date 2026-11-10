"""UI review records: validation and append-only persistence."""
import importlib
import json
from datetime import datetime, timezone

import pytest


def append(body, cfg, known_bots=("ops-bot",)):
    return importlib.import_module("pixelhq.reviews").append(body, cfg, known_bots)


def test_valid_append_creates_file_and_sets_server_metadata(tmp_path):
    path = tmp_path / "plugin-data" / "pixel-hq" / "reviews.jsonl"
    cfg = {"reviews_path": str(path), "operator_name": "sample-operator"}
    body = {"agent": "ops-bot", "verdict": "pass", "dims": {
        "correctness": 5, "completeness": 4, "format": 3, "safety": 2},
        "ref": "Sample verification", "sessionId": "sample-session",
        "ts": "untrusted", "reviewer": "untrusted", "source": "tool", "parent": "untrusted"}
    before = datetime.now(timezone.utc)
    result = append(body, cfg)
    assert result["ok"] is True and result["message"]
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {"ts": record["ts"], "agent": "ops-bot", "verdict": "pass",
                      "dims": body["dims"], "ref": body["ref"],
                      "reviewer": "sample-operator", "source": "ui"}
    ts = datetime.fromisoformat(record["ts"])
    assert ts.utcoffset().total_seconds() == 0
    assert before <= ts <= datetime.now(timezone.utc)
    assert path.read_bytes().endswith(b"\n")
    assert body["reviewer"] == "untrusted"


@pytest.mark.parametrize("change, message", [
    ({"agent": "unknown-bot"}, "agent"), ({"agent": ["ops-bot"]}, "agent"),
    ({"agent": ""}, "agent"), ({"verdict": "approve"}, "verdict"),
    ({"verdict": None}, "verdict"), ({"verdict": []}, "verdict"),
    ({"dims": {"correctness": 0}}, "dims"), ({"dims": {"safety": 6}}, "dims"),
    ({"dims": {"format": 4.0}}, "dims"), ({"dims": {"format": True}}, "dims"),
    ({"dims": {"completeness": "4"}}, "dims"), ({"dims": {"unknown": 4}}, "dims"),
    ({"dims": []}, "dims"), ({"dims": None}, "dims"),
    ({"ref": "x" * 201}, "ref"), ({"ref": None}, "ref"), ({"ref": 42}, "ref"),
])
def test_invalid_reviews_do_not_create_or_change_ledger(tmp_path, change, message):
    path = tmp_path / "missing" / "reviews.jsonl"
    body = {"agent": "ops-bot", "verdict": "pass", **change}
    result = append(body, {"reviews_path": str(path)})
    assert result["ok"] is False and message in result["message"]
    assert not path.parent.exists()
    path.parent.mkdir()
    path.write_text('{"sample": true}\n', encoding="utf-8")
    result = append(body, {"reviews_path": str(path)})
    assert result["ok"] is False
    assert path.read_text(encoding="utf-8") == '{"sample": true}\n'


@pytest.mark.parametrize("body", [None, [], "sample", {}, {"agent": "ops-bot"}])
def test_missing_fields_and_nonobjects_return_an_error(tmp_path, body):
    result = append(body, {"reviews_path": str(tmp_path / "reviews.jsonl")})
    assert result["ok"] is False and result["message"]


@pytest.mark.parametrize("verdict", ["pass", "revise", "fail"])
def test_optional_dimensions_and_reference_boundary(tmp_path, verdict):
    path = tmp_path / "reviews.jsonl"
    cfg = {"reviews_path": str(path)}
    for dims in (None, {}, {"safety": 1, "correctness": 5}):
        body = {"agent": "ops-bot", "verdict": verdict, "ref": "é" * 200}
        if dims is not None:
            body["dims"] = dims
        assert append(body, cfg)["ok"] is True
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 3
    assert "dims" not in records[0]
    assert records[1]["dims"] == {}
    assert records[2]["dims"] == {"safety": 1, "correctness": 5}
    assert all(r["ref"] == "é" * 200 and r["reviewer"] == "operator" for r in records)


def test_io_failure_returns_a_safe_message(tmp_path):
    path = tmp_path / "directory"
    path.mkdir()
    result = append({"agent": "ops-bot", "verdict": "pass"}, {"reviews_path": str(path)})
    assert result["ok"] is False
    assert str(tmp_path) not in result["message"]


def test_short_write_rolls_back_without_damaging_existing_records(tmp_path, monkeypatch):
    reviews = importlib.import_module("pixelhq.reviews")
    path = tmp_path / "reviews.jsonl"
    original = b'{"sample": true}\n'
    path.write_bytes(original)
    real_write = reviews.os.write
    def short_write(fd, payload):
        return real_write(fd, payload[:7])
    monkeypatch.setattr(reviews.os, "write", short_write)
    result = append({"agent": "ops-bot", "verdict": "fail"}, {"reviews_path": str(path)})
    assert result["ok"] is False
    assert path.read_bytes() == original


def test_append_separates_a_complete_last_record_without_newline(tmp_path):
    path = tmp_path / "reviews.jsonl"
    path.write_text('{"sample": true}', encoding="utf-8")
    assert append({"agent": "ops-bot", "verdict": "revise"}, {"reviews_path": str(path)})["ok"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2 and records[0] == {"sample": True}


def test_default_path_and_concurrent_writers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    cfg = {"hermes_home": str(tmp_path), "reviews_path": ""}
    def write(index):
        return append({"agent": "ops-bot", "verdict": "pass", "ref": f"Sample {index}"}, cfg)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(r["ok"] for r in pool.map(write, range(80)))
    records = [json.loads(line) for line in (tmp_path / "plugin-data" / "pixel-hq" / "reviews.jsonl").read_text().splitlines()]
    assert {r["ref"] for r in records} == {f"Sample {i}" for i in range(80)}
    assert len(records) == 80
