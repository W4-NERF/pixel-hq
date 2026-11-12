"""Nothing in the plugin may signal a process or need POSIX-only modules: it must be harmless on Windows.

On Windows ``os.kill(pid, 0)`` is not an existence probe. Python maps every signal value except
CTRL_C_EVENT/CTRL_BREAK_EVENT to TerminateProcess, so the gateway liveness check would kill the gateway.
"""
import ast
import importlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "__init__.py", ROOT / "pixelhq_loader.py", *sorted((ROOT / "pixelhq").glob("*.py")),
           *sorted((ROOT / "dashboard").glob("*.py"))]


def _calls(tree, dotted):
    owner, attr = dotted.split(".")
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attr
            and isinstance(node.func.value, ast.Name) and node.func.value.id == owner]


def test_the_only_os_kill_sits_behind_the_windows_return():
    hits = {}
    for path in SOURCES:
        found = _calls(ast.parse(path.read_text(encoding="utf-8")), "os.kill")
        if found:
            hits[path.relative_to(ROOT).as_posix()] = found
    assert list(hits) == ["pixelhq/profiles.py"] and len(hits["pixelhq/profiles.py"]) == 1

    tree = ast.parse((ROOT / "pixelhq" / "profiles.py").read_text(encoding="utf-8"))
    probe = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_pid_alive")
    guard = next(node for node in probe.body if isinstance(node, ast.If))
    assert ast.unparse(guard.test) == "IS_WINDOWS"
    assert "IS_WINDOWS = os.name == 'nt'" in ast.unparse(tree)
    assert isinstance(guard.body[-1], ast.Return), "the Windows branch must return before any signal is sent"
    assert guard.lineno < hits["pixelhq/profiles.py"][0].lineno


def test_no_other_process_signalling_or_posix_only_imports():
    forbidden_calls = ("os.killpg", "signal.raise_signal", "signal.pthread_kill")
    posix_only = {"fcntl", "pwd", "grp", "termios", "resource", "posix"}
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for dotted in forbidden_calls:
            assert not _calls(tree, dotted), f"{path.name}: {dotted}"
        # A POSIX-only module may only be imported inside try/except ImportError.
        guarded = {id(node) for block in ast.walk(tree) if isinstance(block, ast.Try) for node in ast.walk(block)}
        for node in ast.walk(tree):
            names = ([alias.name.split(".")[0] for alias in node.names] if isinstance(node, ast.Import)
                     else [str(node.module).split(".")[0]] if isinstance(node, ast.ImportFrom) and node.level == 0
                     else [])
            for name in names:
                assert name not in posix_only or id(node) in guarded, f"{path.name}: unguarded import {name}"


@pytest.mark.parametrize("fmt", ["int", "json"])
def test_on_windows_the_gateway_probe_never_calls_os_kill(fleet, monkeypatch, fmt):
    from pixelhq import profiles

    pid = os.getpid()
    text = str(pid) if fmt == "int" else json.dumps({"pid": pid, "kind": "hermes-gateway"})
    (fleet.root / "gateway.pid").write_text(text, encoding="utf-8")

    def must_not_signal(*args):
        raise AssertionError(f"os.kill{args} was called on Windows")

    monkeypatch.setattr(profiles, "IS_WINDOWS", True)
    monkeypatch.setattr(profiles.os, "kill", must_not_signal)
    # No kernel32 on this platform: the Windows probe cannot tell, so the status is unknown, not guessed.
    assert profiles.list_profiles()["default"]["gateway"] is None


@pytest.mark.parametrize("answer, expected", [(True, "running"), (False, "stopped"), (None, None)])
def test_windows_probe_result_maps_to_the_status(fleet, monkeypatch, answer, expected):
    from pixelhq import profiles

    (fleet.root / "gateway.pid").write_text("4242", encoding="utf-8")
    seen = []
    monkeypatch.setattr(profiles, "IS_WINDOWS", True)
    monkeypatch.setattr(profiles.os, "kill", lambda *args: (_ for _ in ()).throw(AssertionError("signalled")))
    monkeypatch.setattr(profiles, "_pid_alive_windows", lambda pid: seen.append(pid) or answer)
    assert profiles.list_profiles()["default"]["gateway"] == expected
    assert seen == [4242]


def test_windows_probe_swallows_every_failure(monkeypatch):
    from pixelhq import profiles

    class Boom:
        def __getattr__(self, name):
            raise OSError("no kernel32 here")

    monkeypatch.setitem(sys.modules, "ctypes", Boom())
    assert profiles._pid_alive_windows(1234) is None


def test_posix_probe_still_reports_dead_and_foreign_processes(monkeypatch):
    from pixelhq import profiles

    monkeypatch.setattr(profiles, "IS_WINDOWS", False)
    monkeypatch.setattr(profiles.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))
    assert profiles._pid_alive(99) is False
    monkeypatch.setattr(profiles.os, "kill", lambda pid, sig: (_ for _ in ()).throw(PermissionError()))
    assert profiles._pid_alive(99) is True
    calls = []
    monkeypatch.setattr(profiles.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert profiles._pid_alive(99) is True and calls == [(99, 0)]


def test_reviews_module_imports_and_appends_without_fcntl(tmp_path, monkeypatch):
    from pixelhq import reviews

    monkeypatch.setattr(reviews, "fcntl", None)
    cfg = {"reviews_path": str(tmp_path / "reviews.jsonl"), "operator_name": "sample-operator"}
    for verdict in ("pass", "revise"):
        result = reviews.append({"agent": "ops-bot", "verdict": verdict, "ref": "line one"}, cfg, {"ops-bot"})
        assert result["ok"], result
    raw = (tmp_path / "reviews.jsonl").read_bytes()
    assert raw.count(b"\n") == 2 and b"\r" not in raw
    assert [json.loads(line)["verdict"] for line in raw.decode("utf-8").splitlines()] == ["pass", "revise"]


def test_reviews_source_tolerates_a_missing_fcntl_module(monkeypatch):
    """Simulate Windows: importing the module must not fail when ``fcntl`` does not exist."""
    import pixelhq.reviews as loaded

    monkeypatch.setitem(sys.modules, "fcntl", None)  # makes ``import fcntl`` raise ImportError
    try:
        fresh = importlib.reload(loaded)
        assert fresh.fcntl is None
    finally:
        monkeypatch.undo()
        importlib.reload(loaded)
    assert re.search(r"O_BINARY", (ROOT / "pixelhq" / "reviews.py").read_text(encoding="utf-8"))
