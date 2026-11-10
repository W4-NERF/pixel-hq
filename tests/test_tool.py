"""Agent tool registration and JSONL writes without a Hermes runtime."""
import importlib
import json
from pathlib import Path
from datetime import datetime, timezone
import os
import subprocess
import sys

import pytest


@pytest.fixture
def tool_config(fleet, monkeypatch):
    from pixelhq import config

    data = fleet.root / "plugin-data" / "pixel-hq"
    monkeypatch.setattr(config, "_DIRS", [data])
    monkeypatch.setattr(config, "load_config_readonly", lambda: {})
    return fleet


class FakeContext:
    def __init__(self):
        self.calls = []

    def register_tool(self, name, toolset, schema, handler, description=""):
        self.calls.append({"name": name, "toolset": toolset, "schema": schema,
                           "handler": handler, "description": description})


def registration():
    ctx = FakeContext()
    importlib.import_module("__init__").register(ctx)
    assert len(ctx.calls) == 1
    return ctx.calls[0]


def test_register_declares_the_round_one_tool_schema():
    tool = registration()
    assert tool["name"] == "pixelhq_review"
    assert tool["toolset"] == "pixelhq"
    assert callable(tool["handler"])
    assert tool["description"]
    schema = tool["schema"]
    assert schema["name"] == tool["name"]
    assert schema["description"]
    params = schema["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["agent", "verdict"]
    props = params["properties"]
    assert set(props) == {"agent", "verdict", "correctness", "completeness",
                          "format", "safety", "ref", "parent"}
    assert props["agent"]["type"] == props["parent"]["type"] == "string"
    assert props["verdict"]["type"] == "string"
    assert props["verdict"]["enum"] == ["pass", "revise", "fail"]
    assert props["ref"]["type"] == "string" and props["ref"]["maxLength"] == 200
    for key in ("correctness", "completeness", "format", "safety"):
        assert props[key]["type"] == "integer"
        assert props[key]["minimum"] == 1 and props[key]["maximum"] == 5


def test_handler_writes_flat_scores_and_trusted_profile_metadata(tool_config, monkeypatch):
    monkeypatch.setenv("HERMES_PROFILE", "review-bot")
    args = {"agent": "ops-bot", "verdict": "pass", "correctness": 5, "completeness": 4,
            "format": 3, "safety": 2, "ref": "Sample service verification",
            "reviewer": "untrusted", "source": "ui", "ts": "untrusted"}
    before = datetime.now(timezone.utc)
    result = json.loads(registration()["handler"](args, task_id="t_abcdef"))
    assert result == {"ok": True, "message": "Review saved."}
    path = tool_config.reviews_path
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {"ts": record["ts"], "agent": "ops-bot", "verdict": "pass",
                      "dims": {"correctness": 5, "completeness": 4, "format": 3, "safety": 2},
                      "ref": args["ref"], "reviewer": "review-bot", "source": "tool"}
    timestamp = datetime.fromisoformat(record["ts"])
    assert before <= timestamp <= datetime.now(timezone.utc)
    assert timestamp.utcoffset().total_seconds() == 0
    assert path.read_bytes().endswith(b"\n")
    assert args["reviewer"] == "untrusted" and "dims" not in args


@pytest.mark.parametrize("profile, home, expected", [
    ("review-bot", "profiles/ops-bot", "review-bot"),
    (None, "profiles/ops-bot", "ops-bot"),
    ("", "profiles/ops-bot", "ops-bot"),
    (None, ".", "default"),
    (None, None, "default"),
])
def test_calling_profile_uses_environment_then_profile_home_then_default(
        tool_config, monkeypatch, profile, home, expected):
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if profile is not None:
        monkeypatch.setenv("HERMES_PROFILE", profile)
    if home is not None:
        monkeypatch.setenv("HERMES_HOME", str(tool_config.root / home))
    result = json.loads(registration()["handler"]({"agent": "ops-bot", "verdict": "revise"}))
    assert result["ok"] is True
    record = json.loads(tool_config.reviews_path.read_text(encoding="utf-8"))
    assert record["reviewer"] == expected
    assert record["source"] == "tool"
    assert "dims" not in record and "parent" not in record and record["ref"] == ""


def test_tool_can_rate_a_helper_and_credit_its_parent(tool_config, monkeypatch):
    from pixelhq import config, scoring

    monkeypatch.setenv("HERMES_PROFILE", "review-bot")
    args = {"agent": "sample-helper", "parent": "ops-bot", "verdict": "pass",
            "safety": 5, "ref": "é" * 200}
    assert json.loads(registration()["handler"](args))["ok"] is True
    record = json.loads(tool_config.reviews_path.read_text(encoding="utf-8"))
    assert record["agent"] == "sample-helper"
    assert record["parent"] == "ops-bot"
    assert record["dims"] == {"safety": 5} and record["ref"] == "é" * 200
    records, warnings = scoring.parse_reviews([tool_config.reviews_path])
    score = scoring.compute(["ops-bot"], scoring.KanbanIndex(), records, config.load())["ops-bot"]
    assert warnings == []
    assert score["xpOwn"] == 0 and score["xpSummon"] == 10
    assert score["summ"] == [1, 0, 0] and score["selfReviews"] == 0


@pytest.mark.parametrize("helper, parent", [("sample-helper", "ops-bot"), ("subagent-1", None)])
def test_orchestrator_rating_its_helper_earns_summon_xp(tool_config, monkeypatch, helper, parent):
    from pixelhq import collect

    data = tool_config.root / "plugin-data" / "pixel-hq"
    (data / "config.json").write_text('{"orchestrator_profile":"ops-bot"}', encoding="utf-8")
    monkeypatch.setenv("HERMES_PROFILE", "ops-bot")
    args = {"agent": helper, "verdict": "pass", "correctness": 5}
    if parent is not None:
        args["parent"] = parent
    assert json.loads(registration()["handler"](args))["ok"] is True
    snapshot = collect.collect()
    bot = next(bot for bot in snapshot["bots"] if bot["id"] == "ops-bot")
    assert bot["xpSummon"] == 10 and bot["selfReviews"] == 0
    assert bot["summ"] == [1, 0, 0] and bot["hp"] == 100
    assert bot["attrs"][0] == 5 and bot["lastQc"] is not None
    event, = [event for event in snapshot["events"] if event["kind"] == "qc-pass"]
    assert event["summon"] is True and event["selfReview"] is False


@pytest.mark.parametrize("change, message", [
    ({"verdict": "approve"}, "verdict"), ({"verdict": []}, "verdict"),
    ({"agent": ""}, "agent"), ({"agent": "  "}, "agent"), ({"agent": []}, "agent"),
    ({"correctness": 0}, "dims"), ({"completeness": 6}, "dims"),
    ({"format": True}, "dims"), ({"safety": 4.0}, "dims"), ({"safety": "4"}, "dims"),
    ({"ref": "x" * 201}, "ref"), ({"ref": None}, "ref"),
    ({"parent": None}, "parent"), ({"parent": []}, "parent"),
    ({"parent": 42}, "parent"), ({"parent": True}, "parent"),
])
def test_invalid_tool_args_return_error_without_creating_or_changing_ledger(
        tool_config, monkeypatch, change, message):
    from pixelhq import config

    path = tool_config.root / "new" / "reviews.jsonl"
    cfg = config.load() | {"reviews_path": str(path)}
    monkeypatch.setattr(config, "load", lambda: cfg)
    args = {"agent": "ops-bot", "verdict": "pass", **change}
    handler = registration()["handler"]
    result = json.loads(handler(args))
    assert set(result) == {"error"} and message in result["error"]
    assert not path.parent.exists()
    path.parent.mkdir()
    original = b'{"sample": true}\n'
    path.write_bytes(original)
    assert set(json.loads(handler(args))) == {"error"}
    assert path.read_bytes() == original


@pytest.mark.parametrize("args", [None, [], "sample", {}, {"agent": "ops-bot"}])
def test_handler_rejects_nonobjects_and_missing_fields(tool_config, args):
    result = json.loads(registration()["handler"](args))
    assert set(result) == {"error"} and result["error"]
    assert not tool_config.reviews_path.exists()


def test_manifest_tool_capabilities_match_the_registration():
    import yaml

    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "plugin.yaml").read_text(encoding="utf-8"))
    # Hermes reads these as top-level manifest keys (hermes plugins validate checks provides_tools).
    assert manifest["provides_tools"] == [registration()["name"]]
    assert manifest["provides_hooks"] == [] and manifest["provides_middleware"] == []
    assert "capabilities" not in manifest
    assert "pixelhq_review" in manifest["description"]


@pytest.mark.parametrize("stage", ["config", "writer", "io"])
def test_handler_returns_safe_json_for_setup_and_write_failures(tool_config, monkeypatch, stage):
    from pixelhq import config, reviews

    marker = "SAMPLE_PRIVATE_SETTING"
    def fail(*args, **kwargs):
        raise RuntimeError(marker)
    if stage == "config":
        monkeypatch.setattr(config, "load", fail)
    elif stage == "writer":
        monkeypatch.setattr(reviews, "append_tool", fail)
    else:
        tool_config.reviews_path.mkdir()
    result = json.loads(registration()["handler"]({"agent": "ops-bot", "verdict": "fail"}))
    assert set(result) == {"error"} and result["error"]
    assert marker not in result["error"] and str(tool_config.root) not in result["error"]
    assert not tool_config.reviews_path.is_file()


def test_configured_review_path_is_reloaded_for_each_call(tool_config, monkeypatch):
    from pixelhq import config

    target = tool_config.root / "custom" / "ratings.jsonl"
    settings = {"plugins": {"entries": {"pixel-hq": {"settings": {"reviews_path": str(target)}}}}}
    monkeypatch.setattr(config, "load_config_readonly", lambda: settings)
    monkeypatch.setenv("HERMES_PROFILE", "first-review-bot")
    handler = registration()["handler"]
    assert json.loads(handler({"agent": "ops-bot", "verdict": "pass"}))["ok"]
    settings["plugins"]["entries"]["pixel-hq"]["settings"]["reviews_path"] = str(tool_config.reviews_path)
    monkeypatch.setenv("HERMES_PROFILE", "second-review-bot")
    assert json.loads(handler({"agent": "ops-bot", "verdict": "fail"}))["ok"]
    assert json.loads(target.read_text(encoding="utf-8"))["reviewer"] == "first-review-bot"
    assert json.loads(tool_config.reviews_path.read_text(encoding="utf-8"))["reviewer"] == "second-review-bot"


@pytest.mark.parametrize("mode", ["module", "file"])
def test_entrypoint_import_and_handler_work_without_hermes(tool_config, tmp_path, mode):
    root = Path(__file__).resolve().parents[1]
    probe = tmp_path / "probe" / "import_probe.py"
    probe.parent.mkdir()
    probe.write_text('''import importlib, importlib.util, json, sys
from pathlib import Path
root, mode = Path(sys.argv[1]), sys.argv[2]
assert importlib.util.find_spec("hermes") is None
assert importlib.util.find_spec("hermes_cli") is None
if mode == "module":
    sys.path.insert(0, str(root))
    module = importlib.import_module("__init__")
else:
    spec = importlib.util.spec_from_file_location("pixel_hq_probe", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
class Context:
    def register_tool(self, **kwargs):
        self.tool = kwargs
ctx = Context()
module.register(ctx)
print(callable(module.register))
print(ctx.tool["handler"]({"agent": "ops-bot", "verdict": "pass"}))
''', encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1",
           "HERMES_HOME": str(tool_config.root), "HERMES_PROFILE": "review-bot"}
    result = subprocess.run([sys.executable, str(probe), str(root), mode], cwd=probe.parent,
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "True" and json.loads(lines[1])["ok"] is True
    record = json.loads(tool_config.reviews_path.read_text(encoding="utf-8"))
    assert record["reviewer"] == "review-bot" and record["source"] == "tool"
