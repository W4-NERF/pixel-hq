"""Exercise real roster files, backup generations and failures around replacement."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_roster_save import body, target, writer  # noqa: F401


def test_atomic_save_and_one_previous_generation(writer, body, tmp_path, monkeypatch):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"previous bytes, even if not valid JSON\n")
    calls, replace = [], writer.os.replace
    def checked_replace(source, destination):
        source, destination = Path(source), Path(destination)
        assert source.parent == destination.parent == path.parent
        calls.append(destination.name)
        if destination == path:
            assert path.read_bytes() == b"previous bytes, even if not valid JSON\n"
            assert json.loads(source.read_bytes()) == body["roster"]
        return replace(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr(writer.os, "replace", checked_replace)
        assert writer.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})["ok"]
    bak = path.with_suffix(".json.bak")
    assert bak.read_bytes() == b"previous bytes, even if not valid JSON\n"
    assert calls == ["roster.json.bak", "roster.json"]
    first = path.read_bytes()
    body["roster"]["bots"][0]["title"] = "Senior"
    assert writer.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})["ok"]
    assert bak.read_bytes() == first
    assert json.loads(path.read_bytes())["bots"][0]["title"] == "Senior"
    assert sorted(p.name for p in path.parent.iterdir()) == ["roster.json", "roster.json.bak"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_reset_moves_to_backup_and_is_idempotent(writer, body, tmp_path):
    cfg = {"hermes_home": str(tmp_path)}
    assert writer.save(body, cfg, {"ops-bot": {}})["ok"]
    path = target(tmp_path)
    previous = path.read_bytes()
    path.with_suffix(".json.bak").write_bytes(b"older")
    assert writer.save({"reset": True, "path": "elsewhere"}, cfg, {}) == {
        "ok": True, "message": "Roster reset to generated."}
    assert not path.exists()
    assert path.with_suffix(".json.bak").read_bytes() == previous
    assert writer.save({"reset": True}, cfg, {})["ok"]
    assert path.with_suffix(".json.bak").read_bytes() == previous
    fresh = tmp_path / "fresh"
    assert writer.save({"reset": True}, {"hermes_home": str(fresh)}, {})["ok"]
    assert not fresh.exists()


@pytest.mark.parametrize("failure", ["write", "fsync", "backup", "replace", "reset"])
def test_io_failure_is_bounded_and_cleans_temp_files(writer, body, tmp_path, monkeypatch, failure):
    cfg, path = {"hermes_home": str(tmp_path)}, target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"original")
    path.with_suffix(".json.bak").write_bytes(b"older")
    replace = writer.os.replace
    def fail(*args, **kwargs):
        raise OSError("private path and diagnostic")
    def replace_failure(source, destination):
        if Path(destination) == (path.with_suffix(".json.bak") if failure in ("backup", "reset") else path):
            fail()
        return replace(source, destination)
    if failure == "write":
        monkeypatch.setattr(writer.tempfile, "mkstemp", fail)
    elif failure == "fsync":
        monkeypatch.setattr(writer.os, "fsync", fail)
    else:
        monkeypatch.setattr(writer.os, "replace", replace_failure)
    result = writer.save({"reset": True} if failure == "reset" else body, cfg, {"ops-bot": {}})
    assert result["ok"] is False and "private" not in result["message"]
    assert path.read_bytes() == b"original"
    assert sorted(p.name for p in path.parent.iterdir()) == ["roster.json", "roster.json.bak"]


def test_maximum_limits_and_optional_fields_are_accepted(writer, body, tmp_path):
    roster = body["roster"]
    roster["rooms"] = [{"id": f"room-{i}", "label": "R" * 40, "main": i == 0,
                        "zones": [{"id": f"z-{i}-{j}", "label": "Z" * 40, "quarantine": False} for j in range(3)]}
                       for i in range(8)]
    roster["bots"] = [{"id": f"r{i:03d}" + "x" * 60, "cls": "C" * 40, "title": "T" * 40, "loc": "L" * 40,
                       "zone": "z-0-0", "color": "#aAbB09", "remote": True} for i in range(200)]
    roster["rooms"][0]["id"] = "A" * 64
    roster["rooms"][0]["zones"][0]["id"] = "B" * 64
    for bot in roster["bots"]:
        bot["zone"] = "B" * 64
    assert writer.save(body, {"hermes_home": str(tmp_path)}, {})["ok"]
    assert json.loads(target(tmp_path).read_bytes()) == roster


@pytest.mark.parametrize("variant", ["default", "wizard", "knight", "engineer", "scout", "medic", "scribe", "rogue"])
def test_each_sprite_is_accepted(writer, body, tmp_path, variant):
    body["roster"]["bots"][0]["sprite"] = variant
    assert writer.save(body, {"hermes_home": str(tmp_path)}, {"ops-bot": {}})["ok"]


def test_root_fallback_unwraps_profile_home_and_body_paths_never_win(writer, body, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "root" / "profiles" / "ops-bot"))
    body["hermes_home"] = body["root"] = body["roster_path"] = str(tmp_path / "escape")
    body["roster"]["path"] = "../escape"
    assert writer.save(body, {}, {"ops-bot": {}})["ok"]
    assert target(tmp_path / "root").exists()
    assert not (tmp_path / "escape").exists()


def test_loader_import_works_in_a_fresh_interpreter(tmp_path):
    path = Path(__file__).resolve().parents[1] / "pixelhq_loader.py"
    script = tmp_path / "probe.py"
    script.write_text("import importlib.util\n"
                      f"spec = importlib.util.spec_from_file_location('probe_loader', {str(path)!r})\n"
                      "loader = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(loader)\n"
                      "mod = loader.module('roster')\n"
                      "assert mod.save({}, {}, {})['ok'] is False\nprint('roster loader import: ok')\n")
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env={**os.environ, "PYTHONPATH": ""},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
