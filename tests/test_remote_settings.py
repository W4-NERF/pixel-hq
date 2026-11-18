"""R5-02: the three remote settings (round 5 §2) and the roster ``source`` field: validation never raises, never echoes."""
import json

import pytest

from pixelhq import config, roster

VALID = [
    "ssh:atlas", "ssh:ops@atlas.example", "ssh:user.name@host-1", "ssh:a@b@c", "ssh:A", "ssh:" + "a" * 128, "ssh:9lives",
    "file:atlas", "file:a.b-c_d", "file:0", "file:" + "a" * 32,
]
HOSTILE = [
    "ssh:-oProxyCommand=sample", "ssh:--help", "ssh:a b", "ssh: atlas", "ssh:atlas ", "ssh:a;b", "ssh:a|b", "ssh:a&b",
    "ssh:a$(sample)", "ssh:a`sample`", "ssh:a\nb", "ssh:atlas\n", "ssh:\natlas", "ssh:a\rb", "ssh:a\tb", "ssh:a\x00b",
    "ssh:a:b", "ssh:atlas:22", "ssh://atlas", "ssh:", "ssh:@atlas", "ssh:user@", "ssh:user@-host", "ssh:user@.host",
    "ssh:" + "a" * 129, "ssh:a'b", 'ssh:a"b', "ssh:a\\b", "ssh:a>b", "ssh:a<b", "ssh:a/b", "ssh:a*b", "ssh:a\u202eb", "ssh:ä",
    "ssh:.atlas", "ssh:_atlas", "SSH:atlas", "sshx:atlas", "http://atlas", "atlas", "", "ssh", ":atlas",
    "file:", "file:A", "file:../x", "file:a/b", "file:.hidden", "file:-x", "file:a b", "file:a\n", "file:" + "a" * 33,
    "file:a.json\n", "file:ä", "file:atlas.json/", "FILE:atlas",
]


@pytest.fixture
def load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    monkeypatch.setattr(config, "load_config_readonly", lambda: {})

    def run(**settings):
        (tmp_path / "config.json").write_text(json.dumps(settings), encoding="utf-8")
        return config.load()

    return run


def test_defaults_are_empty_8_and_300(load):
    cfg = load()
    assert (cfg["remote_sources"], cfg["remote_timeout_s"], cfg["remote_stale_after_s"]) == ([], 8, 300)
    assert cfg["warnings"] == [] and "config_error" not in cfg


@pytest.mark.parametrize("entry", VALID)
def test_valid_entries_are_kept(load, entry):
    cfg = load(remote_sources=[entry])
    assert cfg["remote_sources"] == [entry] and cfg["warnings"] == []
    assert config.valid_remote_entry(entry)


@pytest.mark.parametrize("entry", HOSTILE)
def test_hostile_entries_are_dropped_with_a_warning_that_does_not_echo_them(load, entry):
    cfg = load(remote_sources=["ssh:atlas", entry, "file:harbor"])
    assert cfg["remote_sources"] == ["ssh:atlas", "file:harbor"]
    assert cfg["warnings"] == ["remote_sources[1]: expected ssh:<destination> or file:<name>"]
    assert cfg["config_error"] == cfg["warnings"][0]
    assert not config.valid_remote_entry(entry)


def test_the_destination_pattern_is_the_spec_pattern_plus_a_clean_host_part():
    assert config.SSH_DEST_RE.pattern == "[A-Za-z0-9][A-Za-z0-9._@-]{0,127}"
    assert config.SOURCE_RE.pattern == "[a-z0-9][a-z0-9._-]{0,31}"
    # Not an option for ssh even though the whole destination starts with a letter.
    assert config.SSH_DEST_RE.fullmatch("user@-oProxyCommand") and not config.valid_remote_entry("ssh:user@-oProxyCommand")


def test_duplicates_collapse_and_the_list_is_capped(load):
    assert load(remote_sources=["ssh:a", "ssh:a", "file:b", "ssh:a"])["remote_sources"] == ["ssh:a", "file:b"]
    many = [f"ssh:host{index}" for index in range(40)]
    cfg = load(remote_sources=many)
    assert cfg["remote_sources"] == many[:config.MAX_REMOTE_SOURCES]
    assert cfg["warnings"] == [f"remote_sources: at most {config.MAX_REMOTE_SOURCES} sources"]


@pytest.mark.parametrize("value", [{}, 5, [1], [["ssh:a"]], None, True, [None]])
def test_wrong_types_fall_back_to_the_default_with_the_usual_warning(load, value):
    cfg = load(remote_sources=value)
    assert cfg["remote_sources"] == []
    assert cfg["warnings"] == ["remote_sources: expected list"]


def test_a_single_string_is_one_entry(load):
    assert load(remote_sources="ssh:atlas")["remote_sources"] == ["ssh:atlas"]


@pytest.mark.parametrize("raw, expected", [(1, 2), (2, 2), (8, 8), (30, 30), (31, 30), (-5, 2), (0, 2), (10 ** 9, 30), ("12", 12)])
def test_timeout_is_clamped_to_2_30(load, raw, expected):
    cfg = load(remote_timeout_s=raw)
    assert cfg["remote_timeout_s"] == expected
    assert (cfg["warnings"] == []) == (raw in (2, 8, 30, "12"))
    assert "config_error" not in cfg  # clamping is not an error


@pytest.mark.parametrize("value", ["soon", 2.5, [], {}, True, None])
def test_timeout_and_stale_after_with_a_wrong_type_use_the_default(load, value):
    cfg = load(remote_timeout_s=value, remote_stale_after_s=value)
    assert (cfg["remote_timeout_s"], cfg["remote_stale_after_s"]) == (8, 300)
    assert cfg["warnings"] == ["remote_timeout_s: expected int", "remote_stale_after_s: expected int"]


@pytest.mark.parametrize("raw, expected", [(300, 300), (1, 1), (0, 1), (-1, 1), (10 ** 12, 7 * 86400), (60, 60)])
def test_stale_after_is_kept_positive_and_bounded(load, raw, expected):
    assert load(remote_stale_after_s=raw)["remote_stale_after_s"] == expected


def test_settings_from_hermes_are_validated_the_same_way(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_DIRS", [tmp_path])
    monkeypatch.setattr(config, "load_config_readonly", lambda: {"plugins": {"entries": {"pixel-hq": {"settings": {
        "remote_sources": ["ssh:atlas", "ssh:a b"], "remote_timeout_s": 99}}}}})
    cfg = config.load()
    assert cfg["remote_sources"] == ["ssh:atlas"] and cfg["remote_timeout_s"] == 30 and cfg["settings_source"] == "hermes"


# ---------------------------------------------------------------- roster ``source``
def roster_body(*bots):
    base = {"title": "Recruit", "cls": "Role", "zone": "crew", "color": "#93A1AF"}
    return {"roster": {"rooms": [{"id": "hq", "label": "HQ", "main": True, "zones": [{"id": "crew", "label": "CREW"}]}],
                       "bots": [{**base, **bot} for bot in bots]}}


def save(tmp_path, *bots, profiles=("default",)):
    return roster.save(roster_body(*bots), {"hermes_home": str(tmp_path)}, {name: {} for name in profiles})


def test_a_remote_entry_may_carry_a_source_and_it_survives_save_and_load(tmp_path, monkeypatch):
    assert save(tmp_path, {"id": "default"}, {"id": "ops", "remote": True, "source": "atlas"})["ok"]
    monkeypatch.setattr(config, "_DIRS", [tmp_path / "plugin-data" / "pixel-hq"])
    loaded = config.load_roster()
    assert loaded["warnings"] == []
    assert [(b["id"], b.get("source")) for b in loaded["bots"]] == [("default", None), ("ops", "atlas")]


@pytest.mark.parametrize("extra", [{}, {"remote": False}, {"remote": 1}])
def test_a_source_needs_remote_true(tmp_path, extra):
    result = save(tmp_path, {"id": "default"}, {"id": "ops", "source": "atlas", **extra})
    assert result["ok"] is False and "only a remote bot can name a source" in result["message"]


@pytest.mark.parametrize("source", ["", "Atlas", "a/b", "a b", "x" * 33, 5, None, [], "a\n"])
def test_a_source_must_match_the_name_rule(tmp_path, source):
    result = save(tmp_path, {"id": "ops", "remote": True, "source": source})
    assert result["ok"] is False and ".source" in result["message"]


def test_ids_are_unique_per_source_not_globally(tmp_path):
    assert save(tmp_path, {"id": "default"}, {"id": "default", "remote": True, "source": "atlas"},
                {"id": "default", "remote": True, "source": "harbor"})["ok"]
    twice = save(tmp_path, {"id": "default", "remote": True, "source": "atlas"},
                 {"id": "default", "remote": True, "source": "atlas"})
    assert twice["ok"] is False and "duplicate id" in twice["message"]
    local_twice = save(tmp_path, {"id": "default"}, {"id": "default", "remote": True})
    assert local_twice["ok"] is False and "duplicate id" in local_twice["message"]


def test_a_roster_file_with_a_bad_source_loses_only_that_field(tmp_path, monkeypatch):
    data = tmp_path / "pixel-hq"
    data.mkdir()
    (data / "roster.json").write_text(json.dumps({
        "rooms": [{"id": "hq", "label": "HQ", "main": True, "zones": [{"id": "crew", "label": "CREW"}]}],
        "bots": [{"id": "a", "zone": "crew", "remote": True, "source": "Bad Name"},
                 {"id": "b", "zone": "crew", "source": "atlas"},
                 {"id": "c", "zone": "crew", "remote": True, "source": "atlas"}]}), encoding="utf-8")
    monkeypatch.setattr(config, "_DIRS", [data])
    loaded = config.load_roster()
    assert [b.get("source") for b in loaded["bots"]] == [None, None, "atlas"]
    assert len(loaded["warnings"]) == 2 and all(".source: expected a source name on a remote bot" in w for w in loaded["warnings"])
