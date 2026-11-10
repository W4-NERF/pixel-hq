"""Regression coverage for schema coercion and request-time configuration."""
import json

import pytest

from pixelhq import config, scoring


@pytest.mark.parametrize("settings, expected", [
    ({"xp_pass": "10", "xp_revise": "-2", "stale_days": "3"},
     {"xp_pass": 10, "xp_revise": -2, "stale_days": 3}),
    ({"kanban_xp": "false"}, {"kanban_xp": False}),
    ({"kanban_xp": "yes"}, {"kanban_xp": True}),
    ({"kanban_xp": 0}, {"kanban_xp": False}),
    ({"exclude_boards": "platform"}, {"exclude_boards": ["platform"]}),
    ({"needs_input_keywords": "approval"}, {"needs_input_keywords": ["approval"]}),
    ({"node_aliases": '{"node-1":"GPU1"}'}, {"node_aliases": {"node-1": "GPU1"}}),
    ({"theme_label": 123}, {"theme_label": "123"}),
])
def test_schema_values_are_coerced_without_warnings(tmp_path, monkeypatch, settings, expected):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    monkeypatch.setattr(config, "load_config_readonly", lambda: {
        "plugins": {"entries": {"pixel-hq": {"settings": settings}}}})
    cfg = config.load()
    for key, value in expected.items():
        assert type(cfg[key]) is type(value)
        assert cfg[key] == value
    assert cfg.get("warnings", []) == []
    assert cfg.get("config_error") is None
    scoring.compute(["ops-bot"], scoring.KanbanIndex(), [{"agent": "ops-bot", "verdict": "pass"}], cfg)


@pytest.mark.parametrize("key, value", [
    ("xp_pass", "invalid"), ("xp_revise", []), ("xp_fail", None),
    ("stale_days", 1.5), ("kanban_xp", "perhaps"), ("kanban_xp", {}),
    ("exclude_boards", {}), ("exclude_boards", [["platform"]]),
    ("needs_input_keywords", [42]), ("node_aliases", []),
    ("node_aliases", "not json"), ("operator_name", None),
    ("reviews_path", []), ("legacy_ledger_path", {}),
])
@pytest.mark.parametrize("source", ["file", "hermes"])
def test_invalid_setting_falls_back_per_key_with_bounded_warning(
        tmp_path, monkeypatch, key, value, source):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    settings = {"xp_pass": 27, "theme_label": "SAMPLE HQ", key: value}
    if source == "file":
        (tmp_path / "config.json").write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(config, "load_config_readonly", lambda: {
        "plugins": {"entries": {"pixel-hq": {"settings": settings if source == "hermes" else {}}}}})
    cfg = config.load()
    expected = config.DEFAULTS[key]
    if key == "reviews_path":
        expected = str(config.root_home() / "plugin-data" / "pixel-hq" / "reviews.jsonl")
    assert cfg[key] == expected
    assert cfg["theme_label"] == "SAMPLE HQ"
    if key != "xp_pass":
        assert cfg["xp_pass"] == 27
    message = f"{key}: expected {type(config.DEFAULTS[key]).__name__}"
    assert cfg["warnings"] == [message]
    assert cfg["config_error"] == message
    assert cfg["settings_source"] == source


@pytest.mark.parametrize("key", ["reviews_path", "legacy_ledger_path"])
@pytest.mark.parametrize("value", ["ratings.jsonl", "archive/ratings.jsonl", "../ratings.jsonl", 123])
def test_relative_ledger_paths_use_root_plugin_data(fleet, monkeypatch, key, value):
    data = fleet.root / "plugin-data" / "pixel-hq"
    monkeypatch.setenv("HERMES_HOME", str(fleet.root / "profiles" / "ops-bot"))
    monkeypatch.setattr(config, "_DIRS", [data])
    (data / "config.json").write_text(json.dumps({key: value}), encoding="utf-8")
    cfg = config.load()
    assert cfg[key] == str((data / str(value)).resolve())
    assert cfg.get("warnings", []) == []


def test_ui_writer_resolves_relative_path_without_changing_cwd(fleet, monkeypatch):
    from pixelhq import reviews

    monkeypatch.chdir(fleet.root)
    cfg = {"hermes_home": str(fleet.root), "reviews_path": "archive/ratings.jsonl"}
    assert reviews.append({"agent": "ops-bot", "verdict": "pass"}, cfg, {"ops-bot"})["ok"]
    path = fleet.root / "plugin-data" / "pixel-hq" / "archive" / "ratings.jsonl"
    assert json.loads(path.read_text(encoding="utf-8"))["agent"] == "ops-bot"
    assert not (fleet.root / "archive").exists()


def test_first_invalid_setting_is_the_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    (tmp_path / "config.json").write_text(
        '{"xp_pass": "invalid", "stale_days": "invalid"}', encoding="utf-8")
    cfg = config.load()
    assert set(cfg["warnings"]) == {"xp_pass: expected int", "stale_days: expected int"}
    assert cfg["config_error"] == cfg["warnings"][0]


def test_invalid_higher_priority_key_uses_default_not_file_value(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    (tmp_path / "config.json").write_text('{"xp_pass": 27}', encoding="utf-8")
    monkeypatch.setattr(config, "load_config_readonly", lambda: {
        "plugins": {"entries": {"pixel-hq": {"settings": {"xp_pass": "invalid"}}}}})
    cfg = config.load()
    assert cfg["xp_pass"] == config.DEFAULTS["xp_pass"]
    assert cfg["warnings"] == ["xp_pass: expected int"]
