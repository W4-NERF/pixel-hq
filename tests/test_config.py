"""Settings precedence, manifest defaults and backwards-compatible file loading."""
import json
from pathlib import Path

import pytest

from pixelhq import config

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DEFAULTS = {
    "locale": "en-GB", "timezone": "UTC", "theme_label": "PIXEL HQ", "appearance": "auto", "operator_name": "operator",
    "orchestrator_profile": "default", "reviews_path": "", "legacy_ledger_path": "", "kanban_xp": True,
    "xp_pass": 10, "xp_revise": 3, "xp_fail": -5, "stale_days": 14, "exclude_boards": [],
    "needs_input_keywords": ["approval", "approve", "decision", "sign-off", "gate", "waiting for", "go"],
    "prometheus_url": "", "metrics_prefix": "vllm", "model_endpoint": "", "node_aliases": {},
}


def test_manifest_has_all_19_settings_with_typed_defaults_and_descriptions():
    import yaml

    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    schema = manifest["config_schema"]
    assert len(schema) == 19
    assert schema.keys() == EXPECTED_DEFAULTS.keys()
    assert config.DEFAULTS == EXPECTED_DEFAULTS
    types = {str: "str", int: "int", bool: "bool", list: "list", dict: "dict"}
    for key, default in EXPECTED_DEFAULTS.items():
        entry = schema[key]
        assert entry["type"] == types[type(default)]
        assert type(entry["default"]) is type(default)
        assert entry["default"] == default
        assert entry["description"].strip().endswith(".")
        assert "\n" not in entry["description"]


def test_example_uses_the_canonical_flat_keys():
    example = json.loads((ROOT / "pixelhq" / "config.example.json").read_text(encoding="utf-8"))
    assert example == EXPECTED_DEFAULTS


@pytest.mark.parametrize("value", ["auto", "dark", "light", "invalid", "", "LIGHT", 1, True, None, [], {}])
@pytest.mark.parametrize("source", ["file", "hermes"])
def test_appearance_is_validated_coerced_and_exposed(config_files, monkeypatch, value, source):
    settings = {"appearance": value}
    if source == "file":
        (config_files / "config.json").write_text(json.dumps(settings), encoding="utf-8")
    else:
        monkeypatch.setattr(config, "load_config_readonly", lambda: {
            "plugins": {"entries": {"pixel-hq": {"settings": settings}}}})
    cfg = config.load()
    valid = value in ("auto", "dark", "light")
    expected = value if valid else "auto"
    assert cfg["appearance"] == expected
    assert config.public(cfg, {"rooms": [], "bots": []})["appearance"] == expected
    assert bool(cfg["warnings"]) is not valid
    if not valid:
        assert cfg["warnings"][0].startswith("appearance: expected ")
        assert cfg["config_error"] == cfg["warnings"][0]


def test_appearance_settings_precedence_and_invalid_override(config_files, monkeypatch):
    assert config.load()["appearance"] == "auto"
    (config_files / "config.json").write_text('{"appearance":"dark"}', encoding="utf-8")
    assert config.load()["appearance"] == "dark"
    settings = {"appearance": "light"}
    monkeypatch.setattr(config, "load_config_readonly", lambda: {
        "plugins": {"entries": {"pixel-hq": {"settings": settings}}}})
    assert config.load()["appearance"] == "light"
    settings["appearance"] = "unknown"
    assert config.load()["appearance"] == "auto"


@pytest.fixture
def config_files(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    data = root / "plugin-data" / "pixel-hq"
    data.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(config, "_DIRS", [data])
    return data


def test_load_maps_legacy_blocks_to_flat_keys_only(config_files):
    settings = {
        "xp": {"pass": 17, "revise": 4, "fail": -2},
        "gpu": {
            "prometheus_url": "https://metrics.example",
            "metrics_prefix": "sample",
            "model_endpoint": "https://models.example",
            "node_aliases": {"node-1": "GPU1"},
        },
    }
    (config_files / "config.json").write_text(json.dumps(settings), encoding="utf-8")
    cfg = config.load()
    assert "xp" not in cfg
    assert "gpu" not in cfg
    assert [cfg["xp_" + verdict] for verdict in ("pass", "revise", "fail")] == [17, 4, -2]
    assert {key: cfg[key] for key in settings["gpu"]} == settings["gpu"]
    assert config.public(cfg, {"rooms": [], "bots": []})["xp"] == settings["xp"]
    assert "xp" not in config.DEFAULTS
    assert "gpu" not in config.DEFAULTS


def test_load_precedence_defaults_file_then_hermes(config_files, monkeypatch):
    hermes = {}
    calls = []

    def loader():
        calls.append(True)
        return hermes

    monkeypatch.setattr(config, "load_config_readonly", loader, raising=False)
    roster = {"rooms": [], "bots": []}
    defaults = config.load()
    assert defaults["timezone"] == "UTC"
    assert config.public(defaults, roster)["settingsSource"] == "defaults"

    (config_files / "config.json").write_text(json.dumps({
        "theme_label": "FILE HQ", "locale": "fr-FR", "kanban_xp": True,
        "xp": {"pass": 17, "revise": 4}, "xp_pass": 23,
        "exclude_boards": ["sandbox"], "needs_input_keywords": ["review"],
        "gpu": {"prometheus_url": "https://metrics.example", "metrics_prefix": "old"},
    }), encoding="utf-8")
    file_cfg = config.load()
    assert file_cfg["xp_pass"] == 23
    assert file_cfg["theme_label"] == "FILE HQ"
    assert config.public(file_cfg, roster)["settingsSource"] == "file"

    settings = {"theme_label": "HERMES HQ", "xp_pass": 0, "kanban_xp": False,
                "exclude_boards": [], "needs_input_keywords": [], "prometheus_url": "",
                "reviews_path": "~/sample-reviews.jsonl", "metrics_prefix": "sample"}
    hermes.update({"plugins": {"entries": {"pixel-hq": {"settings": settings},
                                          "another-plugin": {"settings": {"locale": "de-DE"}}}}})
    cfg = config.load()
    assert cfg["theme_label"] == "HERMES HQ"
    assert cfg["xp_pass"] == 0
    assert cfg["xp_revise"] == 4
    assert cfg["locale"] == "fr-FR"
    assert cfg["stale_days"] == 14
    assert cfg["kanban_xp"] is False
    assert cfg["exclude_boards"] == []
    assert cfg["needs_input_keywords"] == []
    assert cfg["prometheus_url"] == ""
    assert cfg["metrics_prefix"] == "sample"
    assert cfg["reviews_path"] == str(config.Path.home() / "sample-reviews.jsonl")
    assert config.public(cfg, roster)["settingsSource"] == "hermes"
    assert len(calls) == 3
    assert settings["reviews_path"] == "~/sample-reviews.jsonl"
    cfg["exclude_boards"].append("other-sandbox")
    assert settings["exclude_boards"] == []


@pytest.mark.parametrize("aliases", [{}, {"node-2": "GPU2"}])
def test_hermes_dict_setting_replaces_file_mapping(config_files, monkeypatch, aliases):
    (config_files / "config.json").write_text(
        '{"gpu":{"node_aliases":{"node-1":"GPU1"}}}', encoding="utf-8")
    settings = {"node_aliases": aliases}
    monkeypatch.setattr(config, "load_config_readonly", lambda: {
        "plugins": {"entries": {"pixel-hq": {"settings": settings}}}})
    cfg = config.load()
    assert cfg["node_aliases"] == aliases
    cfg["node_aliases"]["node-3"] = "GPU3"
    assert settings == {"node_aliases": aliases}
    assert "node-3" not in aliases


@pytest.mark.parametrize("payload", ["{invalid", "[]", "null", '"settings"', "true", "42"])
def test_invalid_file_uses_defaults_and_reports_config_error(config_files, payload):
    (config_files / "config.json").write_text(payload, encoding="utf-8")
    cfg = config.load()
    assert cfg["config_error"].startswith("config.json:")
    for key, value in config.DEFAULTS.items():
        if key != "reviews_path":
            assert cfg[key] == value
    assert cfg["reviews_path"] == str(config_files / "reviews.jsonl")
    public = config.public(cfg, {"rooms": [], "bots": []})
    assert public["settingsSource"] == "defaults"
    assert public["configError"] == cfg["config_error"]


@pytest.mark.parametrize("has_file", [False, True])
def test_hermes_loader_failure_preserves_lower_layers(config_files, monkeypatch, has_file):
    if has_file:
        (config_files / "config.json").write_text('{"theme_label":"FILE HQ"}', encoding="utf-8")

    def loader():
        raise RuntimeError("private settings contents must not be exposed")

    monkeypatch.setattr(config, "load_config_readonly", loader)
    cfg = config.load()
    assert cfg["theme_label"] == ("FILE HQ" if has_file else "PIXEL HQ")
    assert cfg["xp_pass"] == 10
    assert "RuntimeError" in cfg["config_error"]
    assert "private settings" not in cfg["config_error"]
    assert config.public(cfg, {"rooms": [], "bots": []})["settingsSource"] == (
        "file" if has_file else "defaults")


def test_reactor_reads_flat_endpoints_prefix_and_aliases(config_files, monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from pixelhq import collect

    (config_files / "config.json").write_text(json.dumps({
        "prometheus_url": "https://metrics.example/", "metrics_prefix": "sample",
        "model_endpoint": "https://models.example/", "node_aliases": {"node-1": "GPU1"},
    }), encoding="utf-8")
    cfg = config.load()
    requests = []

    def http_json(url):
        requests.append(url)
        if url == "https://models.example/v1/models":
            return {"data": [{"id": "sample/model"}]}
        assert url.startswith("https://metrics.example/api/v1/query?")
        query = parse_qs(urlsplit(url).query)["query"][0]
        if "DCGM_FI_DEV_GPU_UTIL" in query:
            result = [{"metric": {"instance": "node-1"}, "value": [0, "75"]}]
        elif "DCGM_FI_DEV_POWER_USAGE" in query:
            result = [{"metric": {"instance": "node-1"}, "value": [0, "123"]}]
        else:
            assert "sample:" in query
            result = [{"value": [0, "12.5"]}] if "generation_tokens_total" in query else []
        return {"data": {"result": result}}

    monkeypatch.setattr(collect, "http_json", http_json)
    reactor = collect.read_reactor(cfg)
    assert reactor["nodes"] == [{"id": "GPU1", "util": 75, "power": 123}]
    assert reactor["model"] == "sample/model"
    assert reactor["engine"] == "sample"
    assert reactor["srv"]["decodeTps"] == 12.5
    assert "https://models.example/v1/models" in requests


def test_demo_uses_flat_weights_for_buckets_and_sources(monkeypatch):
    from pixelhq import demo

    weights = {"xp_pass": 17, "xp_revise": 4, "xp_fail": -8}
    monkeypatch.setattr(demo.cfgmod, "DEFAULTS", demo.cfgmod.DEFAULTS | weights)
    snapshot = demo.snapshot(seed=6)
    assert snapshot["cfg"]["xp"] == {"pass": 17, "revise": 4, "fail": -8}
    for bot in snapshot["bots"]:
        def raw(counts):
            return sum(count * weights["xp_" + verdict]
                       for verdict, count in zip(("pass", "revise", "fail"), counts, strict=True))
        assert bot["xpOwn"] == max(0, raw(bot["own"]))
        assert bot["xpSummon"] == max(0, raw(bot["summ"]))
        assert bot["xp"] == bot["xpOwn"] + bot["xpSummon"]
        assert bot["xpBySource"] == {
            source: raw([counts[v] for v in ("pass", "revise", "fail")])
            for source, counts in bot["bySource"].items()
        }
