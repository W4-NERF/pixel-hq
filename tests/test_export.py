"""R5-01: the remote exporter prints one read-only, schema-valid document for a host with several homes."""
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

from pixelhq import dbutil, export, remote_schema
from tests import remote_fixture as rf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def remote(tmp_path):
    return rf.build(tmp_path)


def run_export(remote, *extra, label="atlas") -> dict:
    text = export.export(remote.homes, [remote.shared_db], label, "--include-tool-args" in extra, now=remote.now)
    return json.loads(text)


def by_key(rows, key, value):
    return next(row for row in rows if row[key] == value)


# ---------------------------------------------------------------- document
def test_document_has_the_schema_and_round_trips_through_the_shared_validator(remote):
    doc = run_export(remote)
    assert doc["schema"] == "pixelhq-remote/1" and doc["source"] == "atlas"
    assert doc["pixelhq"] == export.cfgmod.disk_version()
    assert remote_schema.validate(doc) == doc
    assert sorted(doc) == ["blockers", "boards", "bots", "generated", "pixelhq", "schema", "source", "warnings"]
    assert doc["generated"].endswith("Z") and len(doc["generated"]) == 20


def test_bots_come_from_both_homes_with_the_collectors_numbers(remote):
    bots = run_export(remote)["bots"]
    assert [bot["id"] for bot in bots] == ["default", "ops-bot", "harbor-bot"]
    ops = by_key(bots, "id", "ops-bot")
    assert (ops["status"], ops["xp"], ops["level"], ops["hp"]) == ("running", 20, 1, 100)
    assert ops["model"] == "sample/model" and ops["cls"] == "Sample operator"
    assert ops["currentStep"] == "terminal command running (12s elapsed)" and ops["quest"] == "Check the sample service"
    assert isinstance(ops["lastActive"], int)
    assert by_key(bots, "id", "default")["status"] == "running"      # a running card on the website board
    assert by_key(bots, "id", "harbor-bot")["status"] == "blocked"   # a blocked card on the shared board
    assert by_key(bots, "id", "harbor-bot")["lastActive"] is None


def test_settings_are_read_from_the_home_of_each_profile(remote):
    bots = run_export(remote)["bots"]
    # one completed card each: 10 XP with the defaults of the first home, 50 with xp_pass of the second home
    assert by_key(bots, "id", "harbor-bot")["xp"] == 50
    assert by_key(bots, "id", "ops-bot")["xp"] == 20


def test_a_home_can_exclude_a_board(remote):
    (remote.atlas.root / "plugin-data" / "pixel-hq" / "config.json").write_text(
        json.dumps({"exclude_boards": ["website"]}), encoding="utf-8")
    slugs = {board["slug"] for board in run_export(remote)["boards"]}
    assert "website" not in slugs and "platform" in slugs


def test_duplicate_profile_name_is_kept_once_and_reported(remote):
    doc = run_export(remote)
    assert [bot["id"] for bot in doc["bots"]].count("default") == 1
    assert "duplicate profile default: kept from home 1, ignored in home 2" in doc["warnings"]
    assert not any("ops-bot" in warning or "harbor-bot" in warning for warning in doc["warnings"])


def filtered(remote, *names_by_home):
    """Run the exporter with ``HomeArg`` values: one tuple of names (or None) per home of the fixture."""
    homes = [export.HomeArg(path, names) for path, names in zip(remote.homes, names_by_home, strict=True)]
    return json.loads(export.export(homes, [remote.shared_db], "atlas", now=remote.now))


def test_a_home_filter_keeps_only_the_named_profiles(remote):
    doc = filtered(remote, ("ops-bot",), ("harbor-bot",))
    assert sorted(bot["id"] for bot in doc["bots"]) == ["harbor-bot", "ops-bot"]


def test_filtering_out_the_root_default_leaves_no_duplicate_warning(remote):
    doc = filtered(remote, None, ("harbor-bot",))
    assert [bot["id"] for bot in doc["bots"]] == ["default", "ops-bot", "harbor-bot"]
    assert not any("duplicate" in warning for warning in doc["warnings"])
    # the order of the homes no longer decides which default is shown: the filtered home never contributes one
    swapped = json.loads(export.export([export.HomeArg(remote.harbor, ("harbor-bot",)), export.HomeArg(remote.atlas.root)],
                                       [], "atlas", now=remote.now))
    assert sorted(bot["id"] for bot in swapped["bots"]) == ["default", "harbor-bot", "ops-bot"]
    assert not any("duplicate" in warning for warning in swapped["warnings"])


def test_a_filter_can_name_the_root_default_and_it_is_still_a_duplicate_check(remote):
    doc = filtered(remote, ("default",), ("default", "harbor-bot"))
    assert "duplicate profile default: kept from home 1, ignored in home 2" in doc["warnings"]
    assert sorted(bot["id"] for bot in doc["bots"]) == ["default", "harbor-bot"]


def test_an_unknown_name_in_a_filter_is_a_warning_not_an_error(remote):
    doc = filtered(remote, ("ops-bot",), ("harbor-bot", "ghost-bot"))
    assert "profile ghost-bot not found in home 2" in doc["warnings"]
    assert sorted(bot["id"] for bot in doc["bots"]) == ["harbor-bot", "ops-bot"]


def test_home_filter_syntax_splits_on_the_last_equals_sign(remote, tmp_path, capsys):
    odd = tmp_path / "odd=home"
    rf.profile_home(odd)
    rf.profile_home(odd / "profiles" / "odd-bot")
    assert export.main(["--home", f"{odd}=odd-bot,default", "--home", f"{remote.harbor}=harbor-bot", "--label", "atlas"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [bot["id"] for bot in doc["bots"]] == ["odd-bot", "default", "harbor-bot"]
    assert not any("not found" in warning or "duplicate" in warning for warning in doc["warnings"])


def test_home_filter_without_a_name_part_reads_every_profile(remote, capsys):
    assert export.main(["--home", str(remote.harbor), "--label", "atlas"]) == 0
    assert [bot["id"] for bot in json.loads(capsys.readouterr().out)["bots"]] == ["default", "harbor-bot"]


def test_home_filter_names_are_deduplicated_and_parsed(tmp_path):
    arg = export.parse_home(f"{tmp_path}=a,b,a,c.d_e-f")
    assert arg == export.HomeArg(tmp_path, ("a", "b", "c.d_e-f"))
    assert export.parse_home(str(tmp_path)) == export.HomeArg(tmp_path)


@pytest.mark.parametrize("tail", ["=", "=a,", "=,a", "=bad name", "=a/b", "=" + "x" * 65])
def test_an_invalid_name_in_a_home_filter_is_a_usage_error(remote, capsys, tail):
    assert export.main(["--home", f"{remote.atlas.root}{tail}"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("pixelhq-export: ") and "NAME" in captured.err
    assert str(remote.atlas.root) not in captured.err


def test_help_describes_the_home_filter(capsys):
    with pytest.raises(SystemExit):
        export.parse_args(["--help"])
    assert "PATH=NAME[,NAME...]" in capsys.readouterr().out


def test_the_same_home_listed_twice_is_read_once(remote):
    text = export.export([remote.atlas.root, remote.atlas.root], [], "atlas", now=remote.now)
    doc = json.loads(text)
    assert [bot["id"] for bot in doc["bots"]] == ["default", "ops-bot"]
    assert "home 2 listed twice: ignored" in doc["warnings"]


def test_boards_from_every_home_and_the_extra_database_without_duplicates(remote):
    doc = run_export(remote)
    # the extra database is also reachable through the symlinked board directory of the second home: listed once
    assert [board["slug"] for board in doc["boards"]] == ["platform", "website", "harbor", "mirror"]
    shared = by_key(doc["boards"], "slug", "mirror")
    assert shared == {"slug": "mirror", "ready": 1, "running": 0, "blocked": 1, "todo": 0, "done24h": 1}
    assert by_key(doc["boards"], "slug", "platform")["blocked"] == 2


def test_extra_database_alone_is_named_after_its_directory(remote):
    doc = json.loads(export.export([remote.atlas.root], [remote.shared_db], "atlas", now=remote.now))
    assert [board["slug"] for board in doc["boards"]] == ["platform", "website", "ledger"]
    assert by_key(doc["bots"], "id", "default")["status"] == "running"


def test_board_slug_collision_renames_the_second_database(remote, tmp_path):
    other = rf.board_db(tmp_path / "elsewhere" / "platform" / "kanban.db")
    doc = json.loads(export.export([remote.atlas.root], [other], "atlas", now=remote.now))
    assert "platform-2" in {board["slug"] for board in doc["boards"]}
    assert "board slug platform used twice: second database exported as platform-2" in doc["warnings"]


def test_blocked_cards_have_category_age_and_a_valid_card_id(remote):
    doc = run_export(remote)
    assert [card["id"] for card in doc["blockers"]] == ["t_00aa11bb", "t_00cc33dd"]
    first = doc["blockers"][0]
    assert first == {"board": "platform", "id": "t_00aa11bb", "title": "Approve the sample change", "category": "you",
                     "assignee": "ops-bot", "ageDays": 3, "reason": "Need approval for the sample change"}
    assert by_key(doc["blockers"], "id", "t_00cc33dd")["category"] == "technical"
    assert "a blocked card with a non-standard id was skipped" in doc["warnings"]


def test_reviews_raise_xp_but_their_content_is_never_exported(remote):
    marker = "marker-" + "ledger-text"
    remote.atlas.reviews([{"agent": "ops-bot", "verdict": "pass", "ts": "2026-01-01T00:00:00+00:00", "ref": marker,
                           "reviewer": "someone", "source": "ui"}])
    text = export.export(remote.homes, [remote.shared_db], "atlas", now=remote.now)
    assert marker not in text
    assert by_key(json.loads(text)["bots"], "id", "ops-bot")["xp"] == 30


def test_profile_without_readable_activity_is_unknown(remote):
    (remote.harbor / "profiles" / "harbor-bot" / "state.db").unlink()
    add_idle = remote.harbor / "profiles" / "quiet-bot"
    rf.profile_home(add_idle)
    (add_idle / "state.db").write_bytes(b"this is not a database" * 40)
    doc = run_export(remote)
    assert by_key(doc["bots"], "id", "quiet-bot")["status"] == "unknown"
    assert by_key(doc["bots"], "id", "harbor-bot")["status"] == "blocked"  # the blocked card still wins
    assert by_key(doc["bots"], "id", "ops-bot")["status"] == "running"


def test_idle_profile_and_missing_gateway_do_not_matter(remote):
    doc = run_export(remote)
    assert not [bot for bot in doc["bots"] if bot["status"] == "unknown"]
    with sqlite3.connect(remote.atlas.root / "profiles" / "ops-bot" / "state.db") as con:
        con.execute("UPDATE sessions SET ended_at = 1")
    quiet = by_key(run_export(remote)["bots"], "id", "ops-bot")
    assert quiet["status"] == "blocked" and "currentStep" not in quiet and "lastTool" not in quiet


# ---------------------------------------------------------------- redaction
def test_tool_arguments_are_left_out_by_default(remote):
    text = export.export(remote.homes, [remote.shared_db], "atlas", now=remote.now)
    assert by_key(json.loads(text)["bots"], "id", "ops-bot")["lastTool"] == "terminal"
    assert rf.SECRET_ARG not in text and "private-sample-dir" not in text


def test_tool_arguments_appear_only_with_the_flag(remote):
    doc = run_export(remote, "--include-tool-args")
    assert by_key(doc["bots"], "id", "ops-bot")["lastTool"] == "terminal: " + rf.SECRET_ARG
    assert remote_schema.validate(doc) == doc


def test_flag_clips_a_long_argument_to_160_characters(remote):
    with sqlite3.connect(remote.atlas.root / "profiles" / "ops-bot" / "state.db") as con:
        calls = [{"function": {"name": "terminal", "arguments": json.dumps({"command": "x" * 900})}}]
        con.execute("UPDATE messages SET tool_calls = ?", (json.dumps(calls),))
    assert len(by_key(run_export(remote, "--include-tool-args")["bots"], "id", "ops-bot")["lastTool"]) == 160
    assert by_key(run_export(remote)["bots"], "id", "ops-bot")["lastTool"] == "terminal"


def test_no_absolute_path_of_the_host_reaches_the_document(remote, tmp_path):
    (remote.harbor / "profiles" / "harbor-bot" / "state.db").write_bytes(b"x" * 100)
    text = export.export(remote.homes, [remote.shared_db], "atlas", now=remote.now)
    assert str(tmp_path) not in text and "atlas-home" not in text and "harbor-home" not in text


def test_warning_text_hides_paths_and_is_clipped():
    assert export._warning("cannot open /srv/private/area/x.db: denied") == "cannot open <path>: denied"
    assert "C:" not in export._warning("cannot open C:\\Users\\sample\\x.db: denied")
    assert export._warning("ok platform/tasks: no such table") == "ok platform/tasks: no such table"
    assert len(export._warning("w" * 500)) == 160


# ---------------------------------------------------------------- limits
def many_profiles(home: Path, count: int, prefix: str) -> None:
    for number in range(count):
        directory = home / "profiles" / f"{prefix}{number:03d}"
        directory.mkdir(parents=True)
        (directory / "config.yaml").write_text("model: sample/model\n", encoding="utf-8")


def test_at_most_200_bots_and_the_cut_is_reported(remote):
    many_profiles(remote.harbor, 205, "bulk-")
    doc = run_export(remote)
    assert len(doc["bots"]) == 200
    assert doc["warnings"][0] == "bots: truncated to 200 of 208"
    assert remote_schema.validate(doc) == doc


def test_at_most_500_blockers(remote):
    with sqlite3.connect(remote.shared_db) as con:
        con.executemany("INSERT INTO tasks (id, title, assignee, status, created_at) VALUES (?, ?, 'harbor-bot', 'blocked', 1)",
                        [(f"t_{number:08x}", f"Bulk sample {number}") for number in range(520)])
    doc = run_export(remote)
    assert len(doc["blockers"]) == 500
    assert doc["warnings"][0] == "blockers: truncated to 500 of 522"
    assert remote_schema.validate(doc) == doc


def test_at_most_64_boards(remote):
    for number in range(70):
        rf.board_db(remote.harbor / "kanban" / "boards" / f"bulk-{number:02d}" / "kanban.db")
    doc = run_export(remote)
    assert len(doc["boards"]) == 64
    assert doc["warnings"][0] == "boards: truncated to 64 of 74"
    assert remote_schema.validate(doc) == doc


def test_at_most_20_warnings_each_at_most_160_characters(remote):
    many_profiles(remote.atlas.root, 30, "twin-")
    many_profiles(remote.harbor, 30, "twin-")
    doc = run_export(remote)
    assert len(doc["warnings"]) == 20
    assert doc["warnings"][-1].endswith("more warnings omitted")
    assert all(len(warning) <= 160 for warning in doc["warnings"])
    assert len([bot for bot in doc["bots"] if bot["id"].startswith("twin-")]) == 30


def test_text_fields_are_clipped_and_cleaned(remote):
    add = rf.add_task
    add(remote.shared_db, "t_00112233", "T" * 400 + "\u202e\x07", "harbor-bot", "blocked")
    rf.add_event(remote.shared_db, "t_00112233", "blocked", {"actor": "harbor-bot", "reason": "R\n" * 300})
    rf.add_session(remote.harbor / "profiles" / "harbor-bot", remote.now, step="S" * 400, title="Q" * 300)
    (remote.harbor / "profiles" / "harbor-bot" / "profile.yaml").write_text("description: " + "D" * 90 + "\n", encoding="utf-8")
    doc = run_export(remote)
    bot = by_key(doc["bots"], "id", "harbor-bot")
    assert (len(bot["currentStep"]), len(bot["quest"]), len(bot["cls"])) == (120, 80, 40)  # the reader clips steps at 120
    card = by_key(doc["blockers"], "id", "t_00112233")
    assert (len(card["title"]), len(card["reason"])) == (120, 160)
    assert "\u202e" not in json.dumps(doc, ensure_ascii=False) and "\x07" not in json.dumps(doc, ensure_ascii=False)
    assert "\n" not in card["reason"]


def test_a_document_over_the_size_limit_loses_list_entries_not_validity(remote, monkeypatch):
    many_profiles(remote.harbor, 150, "bulk-")
    full = len(export.export(remote.homes, [remote.shared_db], "atlas", now=remote.now))
    monkeypatch.setattr(remote_schema, "MAX_BYTES", full // 2)
    text = export.export(remote.homes, [remote.shared_db], "atlas", now=remote.now)
    doc = json.loads(text)
    assert len(text.encode()) + 1 <= full // 2
    assert any(warning.startswith("bots: truncated to") and warning.endswith("(document size)") for warning in doc["warnings"])
    assert remote_schema.validate(doc) == doc


# ---------------------------------------------------------------- nothing is written
def test_nothing_is_written_to_homes_or_boards(remote):
    before = rf.tree_hash(*remote.trees())
    run_export(remote, "--include-tool-args")
    run_export(remote)
    assert rf.tree_hash(*remote.trees()) == before


def test_tree_hash_notices_a_change(remote):
    before = rf.tree_hash(*remote.trees())
    (remote.harbor / "new-file").write_text("x", encoding="utf-8")
    assert rf.tree_hash(*remote.trees()) != before


def wal_databases(remote):
    """Every database of the fixture, switched to WAL mode and closed cleanly (no `-wal`/`-shm` file stays behind)."""
    found = [*(path for home in (remote.atlas.root, remote.harbor) for path in home.rglob("*.db")), remote.shared_db]
    for path in found:
        with contextlib.closing(sqlite3.connect(path)) as con:
            assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    assert not [p for root in remote.trees() for p in root.rglob("*") if p.name.endswith(("-wal", "-shm"))]
    return found


def test_wal_databases_without_side_files_are_read_without_creating_any(remote):
    """R5-D5: neither `-wal` nor `-shm` exists: the database is opened immutable, so nothing appears next to it."""
    found = wal_databases(remote)
    names = {str(p.relative_to(remote.atlas.root.parent)) for root in remote.trees() for p in root.rglob("*")}
    before = rf.tree_hash(*remote.trees())
    doc = run_export(remote, "--include-tool-args")
    assert doc["bots"] and doc["blockers"] and doc["boards"], "the databases were really read"
    assert {str(p.relative_to(remote.atlas.root.parent)) for root in remote.trees() for p in root.rglob("*")} == names
    assert rf.tree_hash(*remote.trees()) == before
    assert found


# ---------------------------------------------------------------- R5-D10: the open rule follows the journal mode
WAL_WARNING = "write-ahead log without its -shm file was not read; data may be older"


def spy_uris(monkeypatch) -> list[str]:
    """Every URI the exporter's own database opens use (`dbutil.sqlite3.connect` is wrapped, not replaced)."""
    seen: list[str] = []
    spy = types.SimpleNamespace(**{**vars(sqlite3), "connect": lambda target, *a, **k: seen.append(target) or sqlite3.connect(target, *a, **k)})
    monkeypatch.setattr(dbutil, "sqlite3", spy)
    return seen


def queries(seen: list[str], name: str) -> list[str]:
    """The URI query of every open of the database file ``name``."""
    return [uri.split("?")[1] for uri in seen if uri.split("?")[0].endswith("/" + name)]


def export_home(home: Path, *extra: Path, now=None) -> dict:
    return json.loads(export.export([home], list(extra), "atlas", now=now))


def wal_board(path: Path) -> Path:
    """A board database in WAL mode with one blocked card, closed cleanly (no side files stay behind)."""
    rf.board_db(path)
    rf.add_task(path, "t_00aa11bb", "Sample", "harbor-bot", "blocked")
    with contextlib.closing(sqlite3.connect(path)) as con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    return path


def wal_profile(home: Path, now: float) -> sqlite3.Connection:
    """A profile whose newest session is committed only to the WAL; the returned writer keeps `-wal` and `-shm` alive."""
    rf.profile_home(home)
    writer = sqlite3.connect(home / "state.db")
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    rf.add_session(home, now, title="Committed only to the log")
    assert (home / "state.db-wal").is_file() and (home / "state.db-shm").is_file()
    return writer


def test_a_rollback_journal_database_is_opened_read_only_with_shared_locks(tmp_path, monkeypatch):
    """R5-D10: header byte 18 is 1: plain `mode=ro`, never `immutable` (a concurrent writer is never read half-way)."""
    home, board = tmp_path / "home", rf.board_db(tmp_path / "ledger" / "kanban.db")
    rf.profile_home(home)
    for path in (home / "state.db", board):
        assert path.read_bytes()[18:20] == b"\x01\x01"
    seen, before = spy_uris(monkeypatch), rf.tree_hash(home, board.parent)
    doc = export_home(home, board)
    assert doc["bots"] and doc["boards"] and doc["warnings"] == []
    assert queries(seen, "state.db") and set(queries(seen, "state.db")) == {"mode=ro"}
    assert queries(seen, "kanban.db") and set(queries(seen, "kanban.db")) == {"mode=ro"}
    assert rf.tree_hash(home, board.parent) == before


def test_a_wal_database_with_its_wal_and_shm_files_is_opened_read_only(tmp_path, monkeypatch):
    """R5-D10: WAL with `-wal` and `-shm` (a live writer): `mode=ro`, the committed log data is read, nothing is created."""
    home = tmp_path / "home"
    writer = wal_profile(home, 1_700_000_000.0)
    with contextlib.closing(writer):
        assert home.joinpath("state.db").read_bytes()[18:20] == b"\x02\x02"
        seen, names = spy_uris(monkeypatch), {p.name for p in home.iterdir()}
        kept = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in home.iterdir() if p.name != "state.db-shm"}
        shm_size = (home / "state.db-shm").stat().st_size
        doc = export_home(home, now=1_700_000_030.0)
        assert doc["bots"][0]["quest"] == "Committed only to the log" and doc["warnings"] == []
        assert set(queries(seen, "state.db")) == {"mode=ro"}
        assert {p.name for p in home.iterdir()} == names
        # SQLite itself may fill in the wal-index inside the existing -shm file on the first read; nothing else changes
        assert {n: (home / n).stat().st_mtime_ns for n in kept} == {n: v[0] for n, v in kept.items()}
        assert {n: (home / n).read_bytes() for n in kept} == {n: v[1] for n, v in kept.items()}
        assert (home / "state.db-shm").stat().st_size == shm_size
        before = rf.tree_hash(home)  # the wal-index is warm now: a second export leaves the whole tree unchanged
        export_home(home, now=1_700_000_030.0)
        assert rf.tree_hash(home) == before


def test_a_wal_database_with_neither_side_file_is_opened_immutable(tmp_path, monkeypatch):
    """R5-D10: WAL with neither `-wal` nor `-shm` (no process has it open): `mode=ro&immutable=1`, no warning."""
    home, board = tmp_path / "home", tmp_path / "ledger" / "kanban.db"
    rf.profile_home(home)
    wal_board(board)
    with contextlib.closing(sqlite3.connect(home / "state.db")) as con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    assert not [p for root in (home, board.parent) for p in root.rglob("*") if p.name.endswith(("-wal", "-shm"))]
    seen, before = spy_uris(monkeypatch), rf.tree_hash(home, board.parent)
    doc = export_home(home, board)
    assert doc["blockers"] and doc["boards"] and doc["warnings"] == []
    assert set(queries(seen, "state.db")) == set(queries(seen, "kanban.db")) == {"mode=ro&immutable=1"}
    assert rf.tree_hash(home, board.parent) == before


def test_a_wal_without_its_shm_file_is_read_immutable_with_a_warning_for_profile_and_board(tmp_path, monkeypatch):
    """R5-D10: `-wal` but no `-shm` (crash or copy): `mode=ro&immutable=1`, the log is skipped, the warning names the item."""
    source, home, board_dir = tmp_path / "source", tmp_path / "copied-home", tmp_path / "copied-ledger"
    writer = wal_profile(source, 1_700_000_000.0)
    board_writer = sqlite3.connect(wal_board(tmp_path / "ledger" / "kanban.db"))
    with contextlib.closing(writer), contextlib.closing(board_writer):
        assert board_writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        board_writer.execute("UPDATE tasks SET status='ready'")
        board_writer.commit()
        home.mkdir()
        board_dir.mkdir()
        for name in ("config.yaml", "state.db", "state.db-wal"):
            shutil.copy2(source / name, home / name)
        for name in ("kanban.db", "kanban.db-wal"):
            shutil.copy2(tmp_path / "ledger" / name, board_dir / name)
    assert (home / "state.db-wal").is_file() and (board_dir / "kanban.db-wal").is_file()
    assert not (home / "state.db-shm").exists() and not (board_dir / "kanban.db-shm").exists()
    seen, before = spy_uris(monkeypatch), rf.tree_hash(home, board_dir)
    doc = export_home(home, board_dir / "kanban.db", now=1_700_000_030.0)
    assert set(queries(seen, "state.db")) == set(queries(seen, "kanban.db")) == {"mode=ro&immutable=1"}
    assert f"profile default: {WAL_WARNING}" in doc["warnings"]
    assert f"board {board_dir.name}: {WAL_WARNING}" in doc["warnings"]
    assert doc["bots"][0].get("quest") is None, "the log was not read: the session committed only to it is not visible"
    assert doc["boards"], "the board file itself is still read"
    assert rf.tree_hash(home, board_dir) == before
    assert not (home / "state.db-shm").exists() and not (board_dir / "kanban.db-shm").exists()


def test_an_unreadable_header_is_a_warning_and_the_item_is_skipped_with_exit_zero(tmp_path, capsys):
    """R5-D10: a file shorter than the 100-byte header: warning with the item's name, the item is skipped, exit code 0."""
    home, board = tmp_path / "home", rf.board_db(tmp_path / "ledger" / "kanban.db")
    other = rf.board_db(tmp_path / "other" / "kanban.db")
    rf.add_task(other, "t_00aa11bb", "Sample", "harbor-bot", "blocked")
    rf.profile_home(home)
    (home / "state.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 30)
    board.write_bytes(b"short")
    before = rf.tree_hash(home, board.parent, other.parent)
    args = ["--home", str(home), "--kanban-db", str(board), "--kanban-db", str(other), "--label", "atlas"]
    assert export.main(args) == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert captured.err == "" and remote_schema.validate(doc) == doc
    assert "header unreadable" in dbutil.HEADER_UNREADABLE
    assert f"profile default: {dbutil.HEADER_UNREADABLE}" in doc["warnings"]
    assert f"board {board.parent.name}: {dbutil.HEADER_UNREADABLE}" in doc["warnings"]
    assert [bot["status"] for bot in doc["bots"]] == ["unknown"], "the unreadable profile stays listed but unknown"
    assert [row["slug"] for row in doc["boards"]] == [other.parent.name], "the unreadable board is skipped"
    assert [card["board"] for card in doc["blockers"]] == [other.parent.name]
    assert len([w for w in doc["warnings"] if "header unreadable" in w]) == 2, doc["warnings"]
    assert rf.tree_hash(home, board.parent, other.parent) == before


def test_the_collectors_own_reads_are_unchanged_outside_the_exporter_block(tmp_path, monkeypatch):
    """R5-D10 concerns the exporter only: outside `create_nothing` every open is `mode=ro` and no header is read."""
    path = tmp_path / "state.db"
    with contextlib.closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (x)")
    seen = spy_uris(monkeypatch)
    monkeypatch.setattr(dbutil, "_journal_version", lambda _path: pytest.fail("header read outside the exporter"))
    dbutil.ro(path).close()
    assert [uri.split("?")[1] for uri in seen] == ["mode=ro"]


@pytest.mark.parametrize("module", [True, False])
def test_command_line_prints_one_document_and_writes_nothing(remote, tmp_path, module):
    before = rf.tree_hash(*remote.trees())
    command = ([sys.executable, "-B", "-m", "pixelhq.export"] if module
               else [sys.executable, "-B", str(ROOT / "pixelhq" / "export.py")])
    args = ["--home", str(remote.atlas.root), "--home", str(remote.harbor), "--kanban-db", str(remote.shared_db), "--label", "atlas"]
    env = {**os.environ, "HERMES_HOME": str(tmp_path / "unused-home"), "PYTHONPATH": os.pathsep.join(
        [str(ROOT), os.environ.get("PYTHONPATH", "")])}
    result = subprocess.run(command + args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("\n")
    doc = json.loads(result.stdout)
    assert (doc["schema"], len(doc["bots"])) == ("pixelhq-remote/1", 3)
    assert remote_schema.validate(doc) == doc
    assert rf.tree_hash(*remote.trees()) == before
    assert list(tmp_path.glob("unused-home*")) == []


def test_main_prints_to_stdout_and_exits_zero(remote, capsys):
    assert export.main(["--home", str(remote.atlas.root), "--label", "atlas"]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out)["source"] == "atlas"


def test_default_home_follows_the_environment(remote, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(remote.atlas.root))
    assert export.main(["--label", "atlas"]) == 0
    assert [bot["id"] for bot in json.loads(capsys.readouterr().out)["bots"]] == ["default", "ops-bot"]


# ---------------------------------------------------------------- command line errors
@pytest.mark.parametrize("args", [
    ["--label", "Not Valid"], ["--label", "-lead"], ["--label", "a" * 33], ["--bogus"],
    ["--home"], ["--home", "{missing}"], ["--kanban-db", "{missing}"], ["--kanban-db", "{home}"],
])
def test_errors_go_to_stderr_with_exit_code_one(remote, tmp_path, capsys, args):
    values = {"{missing}": str(tmp_path / "does-not-exist"), "{home}": str(remote.atlas.root)}
    assert export.main([values.get(arg, arg) for arg in args]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("pixelhq-export: ")
    assert str(tmp_path) not in captured.err


def test_missing_default_home_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "nowhere"))
    assert export.main([]) == 1
    assert capsys.readouterr().out == ""


def test_unexpected_failures_name_only_the_exception_type(remote, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("secret path /srv/private")
    monkeypatch.setattr(export, "read_homes", boom)
    assert export.main(["--home", str(remote.atlas.root)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "pixelhq-export: failed (RuntimeError)\n"


def test_label_defaults_to_the_short_host_name(remote, monkeypatch, capsys):
    monkeypatch.setattr(export.socket, "gethostname", lambda: "Build-Box.example.test")
    assert export.main(["--home", str(remote.atlas.root)]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "build-box"
    monkeypatch.setattr(export.socket, "gethostname", lambda: "....")
    assert export.default_label() == "host"


def test_exporter_is_a_plain_module_of_the_loaded_package():
    import pixelhq_loader
    module = pixelhq_loader.module("export")
    assert module.__name__.endswith(".export") and callable(module.main)
    assert pixelhq_loader.module("remote_schema").SCHEMA == "pixelhq-remote/1"


def test_the_script_entry_stops_bytecode_before_any_package_import():
    """R5-D7: `sys.dont_write_bytecode` is the first statement after the imports of the standard library."""
    source = (ROOT / "pixelhq" / "export.py").read_text(encoding="utf-8")
    switch = source.index("sys.dont_write_bytecode = True")
    assert switch < source.index("from . import"), "the switch must come before the first package import"
    assert source[:switch].count("\nfrom .") == 0 and 'if __name__ == "__main__":' in source[switch - 80:switch]
