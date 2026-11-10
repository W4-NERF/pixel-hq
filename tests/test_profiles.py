"""Profile discovery uses local files, including long model and profile names."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("parser", ["yaml", "fallback"])
def test_model_block_and_quoted_description_are_parsed(fleet, monkeypatch, parser):
    from pixelhq import profiles

    if parser == "fallback":
        monkeypatch.setattr(profiles, "yaml", None)
    (fleet.root / "config.yaml").write_text(
        'unrelated:\n  default: wrong\nmodel:\n  # Keep model names intact.\n'
        '  default: "vendor/model#revision" # trailing comment\n'
        "  provider: 'sample'\ngateway:\n  default: wrong-again\n", encoding="utf-8")
    (fleet.root / "profile.yaml").write_text('description: "Research: #1" # note\n', encoding="utf-8")

    found = profiles.list_profiles()["default"]
    assert found["model"] == "vendor/model#revision"
    assert found["provider"] == "sample"
    assert found["description"] == "Research: #1"


@pytest.mark.parametrize("alive", [True, False])
def test_gateway_pid_reports_actual_liveness(fleet, monkeypatch, alive):
    from pixelhq import profiles

    pid = os.getpid()
    (fleet.root / "gateway.pid").write_text(str(pid), encoding="utf-8")
    if not alive:
        def dead_pid(candidate, signal):
            assert (candidate, signal) == (pid, 0)
            raise ProcessLookupError("Process is gone")
        monkeypatch.setattr(profiles.os, "kill", dead_pid)
    assert profiles.list_profiles()["default"]["gateway"] == ("running" if alive else "stopped")


@pytest.mark.parametrize("alive", [True, False])
def test_gateway_json_pid_reports_actual_liveness(fleet, monkeypatch, alive):
    from pixelhq import profiles

    pid = os.getpid()
    record = {"pid": pid, "kind": "hermes-gateway", "argv": ["hermes", "gateway", "run"]}
    (fleet.root / "gateway.pid").write_text(json.dumps(record), encoding="utf-8")
    if not alive:
        def dead_pid(candidate, signal):
            assert (candidate, signal) == (pid, 0)
            raise ProcessLookupError("Process is gone")
        monkeypatch.setattr(profiles.os, "kill", dead_pid)
    warnings = []
    found = profiles.list_profiles(warnings=warnings)
    assert found["default"]["gateway"] == ("running" if alive else "stopped")
    assert warnings == []


@pytest.mark.parametrize("payload", [
    "", "0", "-1", "SAMPLE_PRIVATE_VALUE", "[]", '"123"', "true",
    '{"pid":', "{}", '{"pid": null}', '{"pid": true}', '{"pid": "123"}',
    '{"pid": 1.5}', '{"pid": -1}', '{"pid": 0}',
    '{"pid": "bad", "argv": ["SAMPLE_PRIVATE_VALUE"]}',
    '{"pid":' + '[' * 1200 + '1' + ']' * 1200 + '}',
])
def test_invalid_gateway_pid_is_unknown_and_warns_without_probing_or_echoing_data(
        fleet, monkeypatch, payload):
    from pixelhq import profiles

    (fleet.root / "gateway.pid").write_text(payload, encoding="utf-8")
    def no_probe(*args):
        pytest.fail("An invalid PID must not probe a process")
    monkeypatch.setattr(profiles.os, "kill", no_probe)
    warnings = []
    assert profiles.list_profiles(warnings=warnings)["default"]["gateway"] is None
    assert len(warnings) == 1 and "gateway.pid" in warnings[0]
    assert len(warnings[0]) <= 120 and "SAMPLE_PRIVATE_VALUE" not in warnings[0]


@pytest.mark.parametrize("parser", ["yaml", "fallback"])
@pytest.mark.parametrize("scalar", ["sample/model", '"vendor/model#revision" # note', "'model: sample'"])
def test_scalar_model_is_accepted_with_unknown_provider(fleet, monkeypatch, parser, scalar):
    from pixelhq import profiles

    if parser == "fallback":
        monkeypatch.setattr(profiles, "yaml", None)
    (fleet.root / "config.yaml").write_text("model: " + scalar + "\n", encoding="utf-8")
    warnings = []
    found = profiles.list_profiles(warnings=warnings)["default"]
    expected = {"sample/model": "sample/model", '"vendor/model#revision" # note': "vendor/model#revision",
                "'model: sample'": "model: sample"}[scalar]
    assert found["model"] == expected
    assert found["provider"] == "?"
    assert warnings == []


@pytest.mark.parametrize("bad_config", ["model: [", "- unexpected", "model: [unexpected]"])
def test_invalid_profile_data_keeps_profile_and_warns(fleet, bad_config):
    from pixelhq import profiles

    (fleet.root / "profiles" / "ops-bot" / "config.yaml").write_text(bad_config, encoding="utf-8")
    warnings = []
    found = profiles.list_profiles(warnings=warnings)
    assert set(found) == {"default", "ops-bot"}
    assert found["ops-bot"]["model"] == "?"
    assert found["ops-bot"]["description"] == "Sample operator"
    assert any("ops-bot" in warning and "config.yaml" in warning for warning in warnings)
    assert all(len(warning) <= 120 for warning in warnings)


def test_collector_discovers_profiles_without_cli(fleet, monkeypatch):
    from pixelhq import collect

    found = collect.read_profiles()
    assert set(found) == {"default", "ops-bot"}
    assert found["ops-bot"]["description"] == "Sample operator"


@pytest.mark.parametrize("module_name", ["collect", "live"])
def test_dashboard_file_import_works_without_previous_module_imports(fleet, tmp_path, module_name):
    root = Path(__file__).resolve().parents[1]
    source = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('pixelhq_probe', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.collect() if hasattr(module, 'collect') else module.query()
print(json.dumps(result))
"""
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONNOUSERSITE": "1", "HERMES_HOME": str(fleet.root)}
    result = subprocess.run([sys.executable, "-c", source, str(root / "pixelhq" / (module_name + ".py"))],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    bots = data["bots"]
    assert (set(bots) if isinstance(bots, dict) else {bot["id"] for bot in bots}) == {
        "default", "ops-bot", "remote-bot"}


def test_unreadable_profile_does_not_hide_readable_neighbours(fleet, monkeypatch):
    from pixelhq import profiles

    for name in ("alpha", "zulu"):
        directory = fleet.root / "profiles" / name
        directory.mkdir()
        (directory / "config.yaml").write_text("model:\n  default: sample/model\n", encoding="utf-8")
    is_file = Path.is_file

    def inaccessible(path):
        if path.parent.name == "zulu":
            raise PermissionError("Sample profile is not readable")
        return is_file(path)

    monkeypatch.setattr(Path, "is_file", inaccessible)
    warnings = []
    found = profiles.list_profiles(warnings=warnings)
    assert {"default", "ops-bot", "alpha"} <= found.keys()
    assert any("zulu" in warning for warning in warnings)


@pytest.mark.parametrize("stage", ["read", "probe"])
def test_gateway_permission_errors_distinguish_reading_from_liveness(fleet, monkeypatch, stage):
    from pixelhq import profiles

    (fleet.root / "gateway.pid").write_text(str(os.getpid()), encoding="utf-8")
    if stage == "read":
        read_text = Path.read_text

        def denied(path, *args, **kwargs):
            if path.name == "gateway.pid":
                raise PermissionError("Sample PID file is not readable")
            return read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", denied)
    else:
        def denied(pid, signal):
            raise PermissionError("Sample process belongs to another user")
        monkeypatch.setattr(profiles.os, "kill", denied)
    warnings = []
    found = profiles.list_profiles(warnings=warnings)
    assert found["default"]["gateway"] == (None if stage == "read" else "running")
    assert bool(warnings) == (stage == "read")


def test_fallback_uses_only_direct_model_keys_and_preserves_plain_hash(fleet, monkeypatch):
    from pixelhq import profiles

    monkeypatch.setattr(profiles, "yaml", None)
    (fleet.root / "config.yaml").write_text(
        "model:\n  default: vendor/model#revision\n  routing:\n    default: wrong\n  provider: sample # note\n",
        encoding="utf-8")
    found = profiles.list_profiles()["default"]
    assert found["model"] == "vendor/model#revision"
    assert found["provider"] == "sample"


def test_yaml_parse_warnings_do_not_echo_private_config_values(fleet):
    from pixelhq import profiles

    marker = "SAMPLE_PRIVATE_VALUE"
    (fleet.root / "config.yaml").write_text(marker + ": [\n", encoding="utf-8")
    warnings = []
    profiles.list_profiles(warnings=warnings)
    assert warnings
    assert all(marker not in warning and "<unicode string>" not in warning for warning in warnings)


def test_collect_acceptance_command_without_a_local_hermes_home(tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = ["python3", "-c", "import time,pixelhq.collect as c;t=time.time();d=c.collect();print(round(1000*(time.time()-t)),'ms',len(d['bots']),'bots',d['cfg']['rosterSource'])"]
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONNOUSERSITE": "1", "HERMES_HOME": str(tmp_path / "absent")}
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    parts = result.stdout.split()
    assert len(parts) == 5
    assert int(parts[0]) < 500
    assert parts[1:] == ["ms", "0", "bots", "generated"]
    print("collect acceptance command:", result.stdout.strip())


def test_twenty_profile_snapshot_meets_the_collection_budget(fleet, monkeypatch):
    import shutil
    import time

    from tests.test_scoring_collect import collector

    for number in range(18):
        directory = fleet.root / "profiles" / f"crew-{number:02d}"
        directory.mkdir()
        (directory / "config.yaml").write_text("model:\n  default: sample/model\n  provider: sample\n", encoding="utf-8")
        shutil.copyfile(fleet.root / "state.db", directory / "state.db")
    (fleet.root / "plugin-data" / "pixel-hq" / "roster.json").unlink()
    module = collector(fleet, monkeypatch)
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        data = module.collect()
        timings.append(round(1000 * (time.perf_counter() - start), 2))
        assert len(data["bots"]) == 20
        assert data["cfg"]["rosterSource"] == "generated"
        assert data["warnings"] == []
    assert max(timings) < 500
    print("20-profile snapshot timings (ms):", timings)


def test_yaml_profiles_include_root_and_valid_profile_directories(fleet, monkeypatch):
    from pixelhq import profiles

    root = fleet.root
    named = root / "profiles" / "research-with-a-long-profile-name"
    named.mkdir()
    (named / "config.yaml").write_text(
        'model:\n  default: "vendor/model-with-a-long-name"\n  provider: sample\n', encoding="utf-8")
    (named / "profile.yaml").write_text('description: "Research: planning"\n', encoding="utf-8")
    for name in ("_internal", ".private", "empty"):
        directory = root / "profiles" / name
        directory.mkdir()
        if name != "empty":
            (directory / "config.yaml").write_text("{}", encoding="utf-8")
    metadata_only = root / "profiles" / "metadata-only"
    metadata_only.mkdir()
    (metadata_only / "profile.yaml").write_text("description: Scout\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(named))

    assert profiles.root_home() == root
    found = profiles.list_profiles()
    assert set(found) == {"default", "ops-bot", named.name, "metadata-only"}
    assert found[named.name] == {
        "model": "vendor/model-with-a-long-name", "provider": "sample", "gateway": None,
        "description": "Research: planning", "dir": named,
    }
    assert found["default"]["dir"] == root
    assert found["metadata-only"]["model"] == "?"
    assert found["metadata-only"]["provider"] == "?"
    assert isinstance(found["default"]["dir"], Path)
