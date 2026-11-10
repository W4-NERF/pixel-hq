"""Shared read helpers retain each view's text and source-selection contracts."""
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_readers_use_one_clip_state_path_and_board_iterator():
    from pixelhq import collect, live, scoring

    common = importlib.import_module("pixelhq.common")
    assert collect.clip is live.clip is scoring.clip is common.clip
    assert collect.state_db is live.state_db is common.state_db
    assert collect.boards is live.boards is common.boards
    assert "ro" not in vars(collect)
    assert "ro" not in vars(live)
    assert "level_of" not in vars(collect)


def test_blockers_import_is_quiet_and_does_not_read_configuration(monkeypatch, capsys):
    from pixelhq import collect, config

    def no_import_reads():
        raise AssertionError("Import must not read fleet data")

    monkeypatch.setattr(config, "load", no_import_reads)
    monkeypatch.setattr(config, "load_roster", no_import_reads)
    blockers = importlib.import_module("pixelhq.blockers")
    assert capsys.readouterr().out == ""
    assert blockers.read_blockers is collect.read_blockers
    common = importlib.import_module("pixelhq.common")
    assert blockers.clip is common.clip
    assert blockers.boards is common.boards


@pytest.mark.parametrize("value,limit,expected", [
    (None, 4, ""), (0, 4, ""), (42, 4, "42"), ("ABCD", 4, "ABCD"),
    ("ABCDE", 4, "ABC…"), ("AB  DE", 5, "AB…"), ("ABCDE", 1, "…"),
    ("  A\n B\t", 20, "  A\n B\t"), ("αβγδε", 4, "αβγ…"),
])
def test_shared_clip_keeps_collector_and_scoring_text(value, limit, expected):
    from pixelhq.common import clip

    assert clip(value, limit) == expected


@pytest.mark.parametrize("limit,expected", [(20, "A B C"), (4, "A B…"), (1, "…")])
def test_shared_clip_can_keep_the_existing_live_whitespace_policy(limit, expected):
    from pixelhq.common import clip

    assert clip("  A\n B\tC  ", limit, collapse_whitespace=True) == expected


def test_shared_state_paths_use_only_the_supplied_request_home(tmp_path):
    from pixelhq.common import state_db

    for home in (tmp_path / "first", tmp_path / "second"):
        cfg = {"hermes_home": str(home)}
        assert state_db("default", cfg) == home / "state.db"
        assert state_db("ops-bot", cfg) == home / "profiles/ops-bot/state.db"


def test_shared_board_discovery_is_sorted_and_skips_missing_or_excluded_sources(fleet):
    from pixelhq.common import boards

    root = fleet.root / "kanban/boards"
    (root / "empty").mkdir()
    cfg = {"hermes_home": str(fleet.root), "exclude_boards": []}
    assert list(boards(cfg)) == sorted(fleet.boards.items())
    cfg["exclude_boards"] = ["platform"]
    assert list(boards(cfg)) == [("website", fleet.boards["website"])]
    assert list(boards({"hermes_home": str(root / "absent")})) == []


def test_explicit_board_candidates_keep_order_duplicates_and_missing_path_diagnostics(fleet):
    from pixelhq.common import boards

    missing = fleet.root / "missing.db"
    candidates = [("website", fleet.boards["website"]), ("missing", missing),
                  ("platform", fleet.boards["platform"]), ("website", fleet.boards["website"])]
    assert list(boards({"exclude_boards": ["platform"]}, iter(candidates))) == [
        candidates[0], candidates[1], candidates[3]]


@pytest.mark.parametrize("excluded", [[], ["platform"], ["website"]])
def test_collector_blockers_live_and_scoring_share_board_selection(fleet, excluded):
    from pixelhq import blockers, collect, config, live

    now = time.time()
    for board, path in fleet.boards.items():
        blocked = fleet.events(board, "ops-bot", ["blocked"], title="  Sample\n  queue  ", ts=now)
        running = fleet.events(board, "remote-bot", ["claimed"], title="  Sample\n  job  ", ts=now)
        with sqlite3.connect(path) as con:
            con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (blocked,))
            con.execute("UPDATE tasks SET status='running' WHERE id=?", (running,))
    cfg = config.load() | {"exclude_boards": excluded}
    expected = set(fleet.boards) - set(excluded)
    index = collect.read_kanban(cfg)
    cards, errors = blockers.read_blockers(cfg, config.load_roster())
    tasks = live.read_running_tasks(now, cfg=cfg)["remote-bot"]
    assert {card["board"] for card in cards} == expected
    assert {task["board"] for task in tasks} == expected
    assert {quest["board"] for quests in index.quests.values() for quest in quests} == expected
    assert errors == index.warnings == []
    assert all(card["title"] == "  Sample\n  queue  " for card in cards)
    assert all(task["title"] == "Sample job" for task in tasks)


def test_live_sessions_keep_single_line_text_after_helper_deduplication(fleet):
    from pixelhq import live

    now = time.time()
    title, step, model = "  Sample\n  session  ", "  terminal\n running  ", "  sample/\nmodel  "
    call = [{"function": {"name": "terminal", "arguments": json.dumps({"command": "  sample\n command  "})}}]
    with sqlite3.connect(fleet.root / "state.db") as con:
        con.execute("INSERT INTO sessions (id, title, started_at, last_activity_description, model) "
                    "VALUES ('s_example', ?, ?, ?, ?)", (title, now, step, model))
        con.execute("INSERT INTO messages (session_id, role, tool_calls, timestamp) "
                    "VALUES ('s_example', 'assistant', ?, ?)", (json.dumps(call), now))
    data = live.read_sessions("default", now)
    session = data["active"][0]
    assert (session["title"], session["step"], session["model"]) == (
        "Sample session", "terminal running", "sample/ model")
    assert session["tool"]["arg"] == "sample command"
    assert (data["last"]["title"], data["last"]["step"]) == ("Sample session", "terminal running")
    assert data["error"] is None and data["warnings"] == []


@pytest.mark.parametrize("mode", ["script", "module"])
def test_blockers_cli_selection_and_missing_keys_are_unchanged(fleet, mode):
    selected = fleet.events("platform", "ops-bot", ["blocked"])
    with sqlite3.connect(fleet.boards["platform"]) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (selected,))
    prefix = [sys.executable, str(ROOT / "pixelhq/blockers.py")] if mode == "script" else [
        sys.executable, "-m", "pixelhq.blockers"]
    key = f"platform/{selected}"
    result = subprocess.run(prefix + [key, "website/t_missing"], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["count"] == 1
    assert data["cards"][0]["id"] == selected
    assert data["notBlockedAnymore"] == ["website/t_missing"]
    assert data["boardErrors"] == data["warnings"] == []


@pytest.mark.parametrize("mode", ["package", "file"])
def test_blockers_import_is_quiet_in_a_fresh_standalone_interpreter(tmp_path, mode):
    probe = tmp_path / "import_probe.py"
    probe.write_text(
        "import importlib, importlib.util, sys\n"
        "if sys.argv[1] == 'package':\n"
        "    module = importlib.import_module('pixelhq.blockers')\n"
        "else:\n"
        "    spec = importlib.util.spec_from_file_location('pixelhq_blockers_probe', sys.argv[2])\n"
        "    module = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(module)\n"
        "assert callable(module.query)\n"
        "print('quiet import: ok')\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(probe), mode, str(ROOT / "pixelhq/blockers.py")],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "quiet import: ok\n"


def test_dashboard_load_reexecutes_entry_modules_but_keeps_sibling_imports(tmp_path, monkeypatch):
    from dashboard import plugin_api as api
    from pixelhq import config

    monkeypatch.setattr(api, "_PIXELHQ", tmp_path)
    entry = tmp_path / "entry.py"
    entry.write_text("from pixelhq import config\nvalue = 'before'\n", encoding="utf-8")
    first = api._load("pixelhq_entry_probe", "entry.py")
    entry.write_text("from pixelhq import config\nvalue = 'after source edit'\n", encoding="utf-8")
    second = api._load("pixelhq_entry_probe", "entry.py")
    assert first is not second
    assert first.value == "before" and second.value == "after source edit"
    assert first.config is second.config is config


@pytest.mark.parametrize("module_name,entrypoint", [("collect", "collect"), ("live", "query")])
def test_dashboard_entries_read_config_and_roster_changes_after_import(fleet, module_name, entrypoint):
    from dashboard import plugin_api as api

    def snapshot(module):
        return getattr(module, entrypoint)()

    def ids(data):
        return set(data["bots"]) if isinstance(data["bots"], dict) else {bot["id"] for bot in data["bots"]}

    module = api._load("pixelhq_lazy_probe", module_name + ".py")
    assert ids(snapshot(module)) == {"default", "ops-bot", "remote-bot"}
    data_dir = fleet.root / "plugin-data/pixel-hq"
    (data_dir / "roster.json").write_text("{invalid", encoding="utf-8")
    (data_dir / "config.json").write_text('{"stale_days":"invalid"}', encoding="utf-8")
    for loaded in (module, api._load("pixelhq_lazy_probe", module_name + ".py")):
        data = snapshot(loaded)
        assert ids(data) == {"default", "ops-bot"}
        assert "stale_days: expected int" in data["warnings"]
        assert any("roster.json" in warning for warning in data["warnings"])
