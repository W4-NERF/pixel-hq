"""Scoring settings and compatibility with the existing nested configuration."""
import json

from pixelhq import config


def configured(fleet, monkeypatch, settings):
    data = fleet.root / "plugin-data" / "pixel-hq"
    path = data / "config.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(config, "site_file", lambda name: data / name if (data / name).exists() else None)
    return config.load()


def test_scoring_defaults_use_root_home_review_path(fleet, monkeypatch):
    cfg = configured(fleet, monkeypatch, {})
    assert config.DEFAULTS["reviews_path"] == ""
    assert config.DEFAULTS["legacy_ledger_path"] == ""
    assert cfg["kanban_xp"] is True
    assert cfg["reviews_path"] == str(fleet.reviews_path)
    assert cfg["legacy_ledger_path"] == ""
    assert [cfg["xp_" + v] for v in ("pass", "revise", "fail")] == [10, 3, -5]


def test_nested_xp_and_gpu_keep_working(fleet, monkeypatch):
    cfg = configured(fleet, monkeypatch, {
        "xp": {"pass": 17, "fail": -2},
        "gpu": {"metrics_prefix": "sample", "node_aliases": {"node-1": "GPU1"}},
        "ledger_path": str(fleet.legacy_path),
    })
    assert [cfg["xp_" + v] for v in ("pass", "revise", "fail")] == [17, 3, -2]
    assert cfg["xp_pass"] == 17
    assert cfg["xp_fail"] == -2
    assert cfg["metrics_prefix"] == "sample"
    assert cfg["node_aliases"] == {"node-1": "GPU1"}
    assert cfg["legacy_ledger_path"] == str(fleet.legacy_path)


def test_flat_settings_override_nested_aliases(fleet, monkeypatch):
    cfg = configured(fleet, monkeypatch, {
        "reviews_path": str(fleet.root / "custom.jsonl"),
        "legacy_ledger_path": "", "ledger_path": str(fleet.legacy_path),
        "xp": {"pass": 99}, "xp_pass": 23, "xp_revise": 4, "kanban_xp": False,
        "gpu": {"metrics_prefix": "old"}, "metrics_prefix": "sample",
    })
    assert cfg["reviews_path"] == str(fleet.root / "custom.jsonl")
    assert cfg["legacy_ledger_path"] == ""
    assert [cfg["xp_" + v] for v in ("pass", "revise", "fail")] == [23, 4, -5]
    assert cfg["metrics_prefix"] == "sample"
    assert cfg["kanban_xp"] is False


def test_active_profile_home_resolves_reviews_at_root(fleet, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(fleet.root / "profiles" / "ops-bot"))
    cfg = configured(fleet, monkeypatch, {})
    assert cfg["hermes_home"] == str(fleet.root)
    assert cfg["reviews_path"] == str(fleet.reviews_path)
