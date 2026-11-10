"""Action guards and CLI argv; subprocesses are always replaced by an in-memory fake."""
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest


ALLOWED = {
    "you": {"answer", "comment", "archive"},
    "technical": {"retry", "comment", "archive"},
    "stale": {"retry", "comment", "archive"},
    "unknown": {"retry", "comment", "archive"},
    "upstream": {"comment"},
}


@pytest.fixture
def action_case(fleet, monkeypatch, tmp_path):
    from pixelhq import actions, collect

    tid = fleet.events("platform", "ops-bot", ["blocked"], task_id="t_abcdef12")
    db = fleet.boards["platform"]
    with sqlite3.connect(db) as con:
        con.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))
    state = {"cat": "technical", "include": True, "remote": False,
             "rc": 0, "change_status": True}
    calls = []
    (fleet.root / "plugin-data" / "pixel-hq" / "config.json").write_text(
        json.dumps({"operator_name": "sample-operator"}), encoding="utf-8")
    monkeypatch.setattr(actions, "WS_BACKUP", tmp_path / "archived-workspaces")
    monkeypatch.setattr(actions, "LOG", tmp_path / "actions.jsonl")

    monkeypatch.setattr(actions.shutil, "which", lambda name: "hermes" if name == "hermes" else None)
    def read_blockers():
        cards = [{"id": tid, "board": "platform", "cat": state["cat"], "remote": state["remote"]}]
        return (cards if state["include"] else []), []
    monkeypatch.setattr(actions, "_collect", lambda: SimpleNamespace(
        ALLOWED=collect.ALLOWED, read_blockers=read_blockers))
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs == {"capture_output": True, "text": True, "timeout": 45}
        if state["rc"] == 0 and state["change_status"] and argv[4] != "comment":
            after = "archived" if argv[4] == "archive" else "ready"
            with sqlite3.connect(db) as con:
                con.execute("UPDATE tasks SET status=? WHERE id=?", (after, tid))
        return SimpleNamespace(returncode=state["rc"], stdout="Sample CLI output\n", stderr="")
    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    body = {"board": "platform", "id": tid, "action": "retry", "text": "Ready to continue"}
    return SimpleNamespace(module=actions, db=db, tid=tid, body=body, state=state, calls=calls,
                           fake_run=fake_run)


def test_category_whitelist_matches_the_public_action_contract(action_case):
    from pixelhq import collect

    assert {cat: set(actions) for cat, actions in collect.ALLOWED.items()} == ALLOWED


@pytest.mark.parametrize("category", ALLOWED)
@pytest.mark.parametrize("action", ["answer", "retry", "comment", "archive"])
def test_category_whitelist_is_enforced_server_side(action_case, category, action):
    case = action_case
    case.state["cat"] = category
    result = case.module.run(case.body | {"action": action})
    allowed = action in ALLOWED[category]
    assert result["ok"] is allowed
    assert len(case.calls) == int(allowed)
    if not allowed:
        assert "not allowed" in result["error"]
        assert not case.module.LOG.exists()


@pytest.mark.parametrize("category, include", [(None, True), ("unlisted", True), (None, False)])
@pytest.mark.parametrize("action", ["retry", "archive"])
def test_unknown_or_missing_blocker_category_fails_closed(action_case, category, include, action):
    case = action_case
    case.state.update(cat=category, include=include)
    result = case.module.run(case.body | {"action": action})
    assert result["ok"] is False and "not allowed" in result["error"]
    assert case.calls == []


@pytest.mark.parametrize("change, message", [
    ({"board": "../platform"}, "board"), ({"board": "missing"}, "board"),
    ({"board": "Platform"}, "board"), ({"board": "platform; sample"}, "board"),
    ({"board": ""}, "board"), ({"board": "a" * 65}, "board"),
    ({"id": "../t_abcdef12"}, "id"), ({"id": "t_short"}, "id"),
    ({"id": "t_abcdef12; sample"}, "id"), ({"id": "t_ABCDEF12"}, "id"),
    ({"id": "t_" + "a" * 17}, "id"), ({"id": ""}, "id"),
    ({"action": "delete"}, "action"), ({"action": "archive --rm"}, "action"),
    ({"action": ""}, "action"),
])
def test_bad_board_id_or_action_never_invokes_cli(action_case, change, message):
    case = action_case
    result = case.module.run(case.body | change)
    assert result["ok"] is False and message in result["error"]
    assert case.calls == [] and not case.module.LOG.exists()


@pytest.mark.parametrize("action", ["answer", "comment"])
@pytest.mark.parametrize("text", ["", "  ", "ab", "a" * 4001])
def test_text_length_guards_reject_after_trimming(action_case, action, text):
    case = action_case
    case.state["cat"] = "you"
    result = case.module.run(case.body | {"action": action, "text": text})
    assert result["ok"] is False and "3–4000" in result["error"]
    assert case.calls == []


@pytest.mark.parametrize("action", ["answer", "comment"])
@pytest.mark.parametrize("text", ["abc", "a" * 4000])
def test_text_length_boundaries_are_accepted(action_case, action, text):
    case = action_case
    case.state["cat"] = "you"
    result = case.module.run(case.body | {"action": action, "text": text})
    assert result["ok"] is True and len(case.calls) == 1


@pytest.mark.parametrize("action, category, text, suffix", [
    ("answer", "you", "  Ready to continue  ",
     ["unblock", "--reason", "[Pixel HQ · sample-operator] Ready to continue", "t_abcdef12"]),
    ("retry", "technical", "", ["unblock", "--reason",
     "[Pixel HQ · sample-operator] retry (from Pixel HQ)", "t_abcdef12"]),
    ("comment", "upstream", "Keep 'quotes'; $(sample) as text",
     ["comment", "--author", "sample-operator (Pixel HQ)", "t_abcdef12", "Keep 'quotes'; $(sample) as text"]),
    ("archive", "stale", "", ["archive", "t_abcdef12"]),
])
def test_allowed_actions_use_exact_cli_argv(action_case, action, category, text, suffix):
    case = action_case
    case.state["cat"] = category
    result = case.module.run(case.body | {"action": action, "text": text})
    assert result["ok"] is True
    assert case.calls == [(["hermes", "kanban", "--board", "platform", *suffix],
                           {"capture_output": True, "text": True, "timeout": 45})]
    assert "--rm" not in case.calls[0][0]
    entry = json.loads(case.module.LOG.read_text(encoding="utf-8"))
    assert entry["board"] == "platform" and entry["id"] == case.tid
    assert entry["action"] == action and entry["cat"] == category
    assert entry["ok"] is True and entry["rc"] == 0
    assert entry["text"] == (text.strip() or None)


def test_archive_copies_workspace_and_symlinks_before_calling_cli(action_case, monkeypatch):
    case = action_case
    workspace = case.db.parent / "workspaces" / case.tid
    (workspace / "nested").mkdir(parents=True)
    (workspace / "nested" / "notes.txt").write_text("Sample deliverable", encoding="utf-8")
    (workspace / "link.txt").symlink_to("nested/notes.txt")
    def archive(argv, **kwargs):
        backups = list((case.module.WS_BACKUP / "platform").iterdir())
        assert len(backups) == 1
        backup = backups[0]
        assert backup.name.startswith(case.tid + "-")
        assert (backup / "nested" / "notes.txt").read_text(encoding="utf-8") == "Sample deliverable"
        assert (backup / "link.txt").is_symlink()
        assert (backup / "link.txt").readlink().as_posix() == "nested/notes.txt"
        return case.fake_run(argv, **kwargs)
    monkeypatch.setattr(case.module.subprocess, "run", archive)
    result = case.module.run(case.body | {"action": "archive"})
    assert result["ok"] is True and result["after"] == "archived"
    assert len(case.calls) == 1


def test_archive_backup_failure_prevents_cli_and_preserves_blocked_card(action_case, monkeypatch):
    case = action_case
    def failed_backup(board, tid, cfg):
        raise OSError("Sample backup error")
    monkeypatch.setattr(case.module, "_backup_workspace", failed_backup)
    result = case.module.run(case.body | {"action": "archive"})
    assert result["ok"] is False and result["after"] == "blocked"
    assert "Sample backup error" in result["output"] and case.calls == []


@pytest.mark.parametrize("status", ["ready", "running", "done"])
def test_nonblocked_card_rejects_retry_but_still_allows_comments(action_case, status):
    case = action_case
    with sqlite3.connect(case.db) as con:
        con.execute("UPDATE tasks SET status=? WHERE id=?", (status, case.tid))
    result = case.module.run(case.body)
    assert result["ok"] is False and "no longer blocked" in result["error"]
    assert case.calls == []
    case.state["include"] = False
    result = case.module.run(case.body | {"action": "comment"})
    assert result["ok"] is True and result["after"] == status


def test_missing_card_never_invokes_cli(action_case):
    case = action_case
    result = case.module.run(case.body | {"id": "t_00000000"})
    assert result == {"ok": False, "error": "card not found"}
    assert case.calls == []


@pytest.mark.parametrize("failure", ["return-code", "unchanged-status", "timeout"])
def test_cli_failures_cannot_report_success(action_case, monkeypatch, failure):
    case = action_case
    if failure == "return-code":
        case.state["rc"] = 2
    elif failure == "unchanged-status":
        case.state["change_status"] = False
    else:
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("hermes", 45)
        monkeypatch.setattr(case.module.subprocess, "run", timeout)
    result = case.module.run(case.body)
    assert result["ok"] is False and result["after"] == "blocked"
    entry = json.loads(case.module.LOG.read_text(encoding="utf-8"))
    assert entry["ok"] is False
