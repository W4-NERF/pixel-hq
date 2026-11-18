"""R5-02: fetching remote sources: the fixed ssh call, file sources, validation, last good document, footer status.

``subprocess.run`` is replaced by ``tests.remote_samples.FakeSsh``; nothing here runs ssh, and ``conftest`` denies any
other process start.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from pixelhq import remote, remote_schema
from tests.remote_samples import FakeSsh, bot, card, document, done, raw

ROOT = Path(__file__).resolve().parents[1]
MiB = 1 << 20


@pytest.fixture
def ssh(monkeypatch):
    fake = FakeSsh()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def fetch(entries, tmp_path, *, timeout=5, now=None):
    return remote.fetch_all(entries, timeout=timeout, root=tmp_path, now=now)


def one(entry, tmp_path, **kw):
    [src] = fetch([entry], tmp_path, **kw)
    return src, remote.status(src, kw.get("now") or time.time(), 300)


def put(tmp_path, name, content, *, mode="w"):
    folder = tmp_path / "plugin-data" / "pixel-hq" / "remote"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    if mode == "wb":
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------- the ssh call
def test_the_ssh_call_is_the_exact_fixed_argument_list_without_a_shell(ssh, tmp_path):
    ssh.outcomes["ops@atlas.example"] = raw(document())
    src, status = one("ssh:ops@atlas.example", tmp_path, timeout=7)
    [(argv, kwargs)] = ssh.calls
    assert argv == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-T", "ops@atlas.example", "pixelhq-export"]
    assert {key: kwargs[key] for key in ("shell", "timeout", "capture_output")} == {"shell": False, "timeout": 7,
                                                                                    "capture_output": True}
    assert set(kwargs) == {"shell", "timeout", "capture_output", "env"}
    assert status["text"] == "ok · 0 s" and src.doc["source"] == "atlas"


def test_only_ssh_sources_start_a_process_and_each_exactly_once(ssh, tmp_path):
    ssh.outcomes.update({"atlas": raw(document()), "harbor": raw(document("harbor"))})
    put(tmp_path, "mirror", json.dumps(document("mirror")))
    sources = fetch(["ssh:atlas", "file:mirror", "ssh:harbor"], tmp_path)
    assert sorted(ssh.destinations) == ["atlas", "harbor"]
    assert [src.label for src in sources] == ["atlas", "mirror", "harbor"]


def test_no_shell_flag_and_a_single_run_call_in_the_sources():
    forbidden = "shell" + "=True"  # assembled: the acceptance grep must find no such text in any source file
    for folder in ("pixelhq", "dashboard"):
        for path in (ROOT / folder).rglob("*.py"):
            assert forbidden not in path.read_text(encoding="utf-8"), path
    code = (ROOT / "pixelhq" / "remote.py").read_text(encoding="utf-8")
    assert code.count("subprocess.run(") == 1 and "shell=False" in code
    assert not any(word in code for word in ("os.system", "Popen", "os.popen", "check_output", "shlex"))


@pytest.mark.parametrize("outcome, text", [
    (subprocess.TimeoutExpired(["ssh"], 5), "unreachable (timeout)"),
    (FileNotFoundError("ssh"), "unreachable (ssh unavailable)"),
    (PermissionError("denied"), "unreachable (ssh unavailable)"),
    (done(b"", 255, b"ssh: Could not resolve hostname secret-host-name"), "unreachable (exit 255)"),
    (done(raw(document()), 1), "unreachable (exit 1)"),
    (done(b"", -9), "unreachable (exit -9)"),
    (RuntimeError("secret-host-name"), "unreachable (error)"),
    (done(None), "invalid (no output)"),
])
def test_failed_runs_are_unreachable_without_leaking_stderr(ssh, tmp_path, outcome, text):
    ssh.outcomes["atlas"] = outcome
    src, status = one("ssh:atlas", tmp_path)
    assert status["text"] == text and src.doc is None
    assert "secret-host-name" not in json.dumps(status)


def test_output_over_one_mib_is_refused_and_exactly_one_mib_is_not(ssh, tmp_path):
    body = raw(document())
    ssh.outcomes["atlas"] = body + b" " * (MiB - len(body))
    assert one("ssh:atlas", tmp_path)[1]["state"] == "ok"
    ssh.outcomes["atlas"] = body + b" " * (MiB + 1 - len(body))
    remote.reset()
    assert one("ssh:atlas", tmp_path)[1]["text"] == "invalid (output over 1 MiB)"


@pytest.mark.parametrize("stdout, reason", [
    (b"", "not JSON"), (b"not json", "not JSON"), (b'{"schema": ', "not JSON"), (b"\xff\xfe\x00", "not UTF-8"),
    (b"[" * 200000, "not JSON"), (b"null", "document: expected an object"), (b"[]", "document: expected an object"),
    (b'"text"', "document: expected an object"), (b"1e999", "document: expected an object"),
])
def test_unparseable_output_is_invalid_with_a_short_reason(ssh, tmp_path, stdout, reason):
    ssh.outcomes["atlas"] = stdout
    src, status = one("ssh:atlas", tmp_path)
    assert status["text"] == f"invalid ({reason})" and src.doc is None and len(status["detail"]) <= 80


@pytest.mark.parametrize("change, reason", [
    ({"schema": "pixelhq-remote/2"}, "schema: unsupported"),
    ({"schema": None}, "schema: unsupported"),
    ({"generated": "yesterday"}, "generated: expected an ISO-8601 UTC time"),
    ({"generated": "2026-13-45T25:61:61Z"}, "generated: not a valid time"),
    ({"pixelhq": 4}, "pixelhq: expected text"),
    ({"bots": "none"}, "bots: expected a list"),
    ({"bots": [bot(status="exploding")]}, "bots[0].status: unknown value"),
    ({"bots": [bot(id="../etc")]}, "bots[0].id: invalid format"),
    ({"bots": [bot(id="a/b")]}, "bots[0].id: invalid format"),
    ({"bots": [bot(), bot()]}, "bots: duplicate id"),
    ({"bots": [bot(xp="many")]}, "bots[0].xp: expected a number"),
    ({"bots": [bot(hp=101)]}, "bots[0].hp: expected an integer 0..100"),
    ({"blockers": [card(id="t_nothex")]}, "blockers[0].id: invalid format"),
    ({"blockers": [card(board="Bad Board")]}, "blockers[0].board: invalid format"),
    ({"boards": [{"slug": "platform"}]}, "boards[0].ready: missing"),
    ({"bots": [bot(id=str(index)) for index in range(201)]}, "bots: more than 200 entries"),
    ({"warnings": [str(index) for index in range(21)]}, "warnings: more than 20 entries"),
])
def test_a_document_that_breaks_the_schema_is_invalid_and_not_merged(ssh, tmp_path, change, reason):
    ssh.outcomes["atlas"] = raw(document(**change))
    src, status = one("ssh:atlas", tmp_path)
    assert status["text"] == f"invalid ({reason})" and src.doc is None


def test_hostile_strings_are_cleaned_clipped_and_unknown_fields_dropped(ssh, tmp_path):
    bidi, nul, esc = "\u202e", "\x00", "\x1b[31m"
    doc = document(
        bots=[bot(model=f"m{bidi}odel{nul}", currentStep="line one\nline two\t" + "x" * 500, quest=f"{esc}red",
                  lastTool="t" * 500, cls="c" * 99, command="rm -rf /", extra={"nested": [1]})],
        blockers=[card(title="<script>alert(1)</script>" + "y" * 300, reason="\x07bell\r\nreason")],
        warnings=["w" * 500], injected={"__proto__": {"polluted": True}})
    ssh.outcomes["atlas"] = raw(doc)
    src, _ = one("ssh:atlas", tmp_path)
    [b], [c] = src.doc["bots"], src.doc["blockers"]
    assert b["model"] == "model" and b["quest"] == "[31mred" and "\n" not in b["currentStep"] and len(b["currentStep"]) == 160
    assert len(b["lastTool"]) == 160 and len(b["cls"]) == 40 and "command" not in b and "extra" not in b
    assert c["title"].startswith("<script>") and len(c["title"]) == 120  # the UI escapes; the backend only bounds
    assert c["reason"] == "bell reason" and len(src.doc["warnings"][0]) == 160 and "injected" not in src.doc


def test_a_label_that_is_no_name_is_replaced_by_the_configured_one(ssh, tmp_path):
    ssh.outcomes["ops@atlas.example"] = raw(document("Not A Label!"))
    src, status = one("ssh:ops@atlas.example", tmp_path)
    assert (src.name, src.label, status["state"]) == ("atlas.example", "atlas.example", "ok")


# ---------------------------------------------------------------- parallel and bounded
def test_sources_are_fetched_in_parallel(ssh, tmp_path):
    for dest in ("a", "b", "c", "d"):
        ssh.outcomes[dest] = lambda dest=dest: (time.sleep(0.4), raw(document(f"src-{dest}")))[1]
    began = time.monotonic()
    sources = fetch([f"ssh:{dest}" for dest in "abcd"], tmp_path)
    assert time.monotonic() - began < 1.2  # four sequential runs would need 1.6 s
    assert [src.state for src in sources] == ["ok"] * 4


def test_a_hanging_source_cannot_hold_the_snapshot_longer_than_timeout_plus_one_second(ssh, tmp_path):
    release = threading.Event()
    ssh.outcomes["stuck"] = lambda: (release.wait(15), raw(document("stuck")))[1]
    ssh.outcomes["fine"] = raw(document("fine"))
    began = time.monotonic()
    try:
        stuck, fine = fetch(["ssh:stuck", "ssh:fine"], tmp_path, timeout=0.5)
        elapsed = time.monotonic() - began
    finally:
        release.set()
    assert 0.5 <= elapsed < 0.5 + remote.GRACE_S + 0.6
    assert remote.status(stuck, time.time(), 300)["text"] == "unreachable (timeout)"
    assert fine.state == "ok"


def test_one_failing_source_does_not_touch_the_others(ssh, tmp_path):
    ssh.outcomes.update({"bad": RuntimeError("boom"), "good": raw(document("good")), "late": subprocess.TimeoutExpired(["ssh"], 1)})
    states = [(src.name, src.state, src.error) for src in fetch(["ssh:bad", "ssh:good", "ssh:late"], tmp_path)]
    assert states == [("bad", "unreachable", "error"), ("good", "ok", ""), ("late", "unreachable", "timeout")]


def test_no_sources_means_no_threads_and_no_state(ssh, tmp_path):
    assert fetch([], tmp_path) == [] and ssh.calls == []


# ---------------------------------------------------------------- file sources
def test_a_file_source_reads_only_its_fixed_path(tmp_path):
    put(tmp_path, "atlas", json.dumps(document("atlas", age=30)))
    src, status = one("file:atlas", tmp_path)
    assert src.kind == "file" and status["text"] == "ok · 30 s" and src.doc["bots"][0]["id"] == "ops-bot"


def test_a_missing_file_is_unreachable(tmp_path):
    assert one("file:atlas", tmp_path)[1]["text"] == "unreachable (file missing)"


def test_a_symlink_is_refused_even_when_it_points_at_a_good_document(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(document()), encoding="utf-8")
    put(tmp_path, "placeholder", "{}")
    link = tmp_path / "plugin-data" / "pixel-hq" / "remote" / "atlas.json"
    link.symlink_to(target)
    src, status = one("file:atlas", tmp_path)
    assert status["text"] == "invalid (symlink refused)" and src.doc is None


def test_a_dangling_symlink_is_refused_too(tmp_path):
    put(tmp_path, "placeholder", "{}")
    (tmp_path / "plugin-data" / "pixel-hq" / "remote" / "atlas.json").symlink_to(tmp_path / "nowhere.json")
    assert one("file:atlas", tmp_path)[1]["text"] == "invalid (symlink refused)"


def test_a_directory_or_fifo_is_not_a_regular_file(tmp_path):
    (tmp_path / "plugin-data" / "pixel-hq" / "remote" / "atlas.json").mkdir(parents=True)
    assert one("file:atlas", tmp_path)[1]["text"] == "invalid (not a regular file)"
    if hasattr(os, "mkfifo"):
        os.mkfifo(tmp_path / "plugin-data" / "pixel-hq" / "remote" / "harbor.json")
        began = time.monotonic()
        assert one("file:harbor", tmp_path)[1]["text"] == "invalid (not a regular file)"
        assert time.monotonic() - began < 1  # never opened, so it cannot block


def test_a_symlinked_folder_in_the_path_is_the_operators_choice_but_the_file_itself_must_be_regular(tmp_path):
    real = tmp_path / "synced"
    real.mkdir()
    (real / "atlas.json").write_text(json.dumps(document()), encoding="utf-8")
    (tmp_path / "plugin-data" / "pixel-hq").mkdir(parents=True)
    (tmp_path / "plugin-data" / "pixel-hq" / "remote").symlink_to(real, target_is_directory=True)
    assert one("file:atlas", tmp_path)[1]["state"] == "ok"


def test_file_size_limit_is_one_mib(tmp_path):
    body = raw(document())
    put(tmp_path, "atlas", body + b" " * (MiB - len(body)), mode="wb")
    assert one("file:atlas", tmp_path)[1]["state"] == "ok"
    put(tmp_path, "harbor", body + b" " * (MiB + 1 - len(body)), mode="wb")
    assert one("file:harbor", tmp_path)[1]["text"] == "invalid (file over 1 MiB)"


def test_a_file_that_grows_while_it_is_read_is_still_bounded(tmp_path, monkeypatch):
    path = put(tmp_path, "atlas", "{}")
    real_lstat = os.lstat

    def lying_lstat(target, *args, **kwargs):
        info = real_lstat(target, *args, **kwargs)
        if str(target) == str(path):
            path.write_bytes(b" " * (MiB + 10))  # grows after the size check
        return info

    monkeypatch.setattr(os, "lstat", lying_lstat)
    assert one("file:atlas", tmp_path)[1]["text"] == "invalid (file over 1 MiB)"


@pytest.mark.parametrize("content, text", [
    ("", "invalid (not JSON)"), ("{not json", "invalid (not JSON)"), ("[]", "invalid (document: expected an object)"),
    (json.dumps(document(schema="other/1")), "invalid (schema: unsupported)"),
])
def test_a_broken_file_is_invalid(tmp_path, content, text):
    put(tmp_path, "atlas", content)
    assert one("file:atlas", tmp_path)[1]["text"] == text


def test_a_file_is_as_old_as_its_generated_stamp_and_never_from_the_future(tmp_path):
    put(tmp_path, "old", json.dumps(document("old", age=720)))
    put(tmp_path, "ahead", json.dumps(document("ahead", age=-60)))
    put(tmp_path, "far", json.dumps(document("far", age=-3600)))
    old, ahead, far = fetch(["file:old", "file:ahead", "file:far"], tmp_path)
    now = time.time()
    assert remote.status(old, now, 300)["text"] == "stale · 12 min"
    assert remote.status(ahead, now, 300)["age"] == 0
    assert remote.status(far, now, 300)["text"] == "invalid (generated: in the future)"


# ---------------------------------------------------------------- last good document, age, stale
def test_a_failing_source_keeps_its_last_good_document_with_its_age(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0, bots=[bot(id="kept")]))
    first, = fetch(["ssh:atlas"], tmp_path, now=1000.0)
    assert remote.status(first, 1035.0, 300)["text"] == "ok · 35 s"
    ssh.outcomes["atlas"] = subprocess.TimeoutExpired(["ssh"], 5)
    second, = fetch(["ssh:atlas"], tmp_path, now=1720.0)
    status = remote.status(second, 1720.0, 300)
    assert second.doc["bots"][0]["id"] == "kept" and second.observed == 1000.0
    assert (status["state"], status["text"], status["error"]) == ("stale", "stale · 12 min", "timeout")


def test_a_failure_inside_the_stale_window_keeps_the_data_ok_and_reports_the_error(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0))
    fetch(["ssh:atlas"], tmp_path, now=1000.0)
    ssh.outcomes["atlas"] = done(b"", 255)
    src, = fetch(["ssh:atlas"], tmp_path, now=1040.0)
    status = remote.status(src, 1040.0, 300)
    assert (status["state"], status["text"], status["error"]) == ("ok", "ok · 40 s", "exit 255")


def test_an_invalid_answer_after_a_good_one_keeps_the_good_one(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0, bots=[bot(id="kept")]))
    fetch(["ssh:atlas"], tmp_path, now=1000.0)
    ssh.outcomes["atlas"] = b"garbage"
    src, = fetch(["ssh:atlas"], tmp_path, now=1010.0)
    assert src.doc["bots"][0]["id"] == "kept" and src.error == "not JSON" and src.state == "invalid"


def test_the_threshold_is_the_setting(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0))
    src, = fetch(["ssh:atlas"], tmp_path, now=1000.0)
    assert remote.status(src, 1100.0, 99)["state"] == "stale"
    assert remote.status(src, 1100.0, 100)["state"] == "ok"


def test_an_ssh_document_is_as_old_as_its_generated_stamp_not_its_receipt(ssh, tmp_path):
    """R5-D3: a document generated 12 minutes ago is stale when it arrives, and its bots are never shown as running."""
    ssh.outcomes["atlas"] = raw(document(base=10000.0, age=720, bots=[bot(status="running")]))
    src, = fetch(["ssh:atlas"], tmp_path, now=10000.0)
    status = remote.status(src, 10000.0, 300)
    assert (status["state"], status["age"], status["text"]) == ("stale", 720, "stale · 12 min")
    assert src.state == "ok" and src.observed == 10000.0 - 720


@pytest.mark.parametrize("ahead, state", [(0, "ok"), (120, "ok"), (121, "invalid")])
def test_a_generated_stamp_more_than_120_s_ahead_is_invalid(ssh, tmp_path, ahead, state):
    ssh.outcomes["atlas"] = raw(document(base=10000.0, age=-ahead))
    src, = fetch(["ssh:atlas"], tmp_path, now=10000.0)
    assert src.state == state
    assert (src.error == "generated: in the future") == (state == "invalid")
    if state == "ok":
        assert remote.status(src, 10000.0, 300)["age"] == 0


def test_a_future_document_after_a_good_one_keeps_the_good_one(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0, bots=[bot(id="kept")]))
    fetch(["ssh:atlas"], tmp_path, now=1000.0)
    ssh.outcomes["atlas"] = raw(document(base=1000.0, age=-600, bots=[bot(id="newer")]))
    src, = fetch(["ssh:atlas"], tmp_path, now=1010.0)
    assert src.doc["bots"][0]["id"] == "kept" and src.state == "invalid" and src.observed == 1000.0


def test_the_ssh_child_gets_only_the_allowlisted_environment(ssh, tmp_path, monkeypatch):
    """R5-D8: PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE and SSH_AUTH_SOCK, each only if set; nothing else."""
    for name in remote.SSH_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PIXELHQ_QA_UNRELATED_TOKEN", "synthetic-not-a-credential")
    monkeypatch.setenv("PATH", "/qa/bin")
    monkeypatch.setenv("LC_CTYPE", "C.UTF-8")
    ssh.outcomes["atlas"] = raw(document())
    fetch(["ssh:atlas"], tmp_path)
    assert ssh.calls[0][1]["env"] == {"PATH": "/qa/bin", "LC_CTYPE": "C.UTF-8"}
    assert remote.SSH_ENV == ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SSH_AUTH_SOCK")


def test_a_removed_source_forgets_its_document(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document(base=1000.0))
    fetch(["ssh:atlas"], tmp_path, now=1000.0)
    fetch([], tmp_path, now=1001.0)
    ssh.outcomes["atlas"] = RuntimeError("down")
    src, = fetch(["ssh:atlas"], tmp_path, now=1002.0)
    assert src.doc is None and remote.status(src, 1002.0, 300)["text"] == "unreachable (error)"


def test_the_last_good_document_is_never_written_to_disk(ssh, tmp_path):
    ssh.outcomes["atlas"] = raw(document())
    before = sorted(p for p in tmp_path.rglob("*"))
    fetch(["ssh:atlas"], tmp_path)
    assert sorted(p for p in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("seconds, text", [(0, "0 s"), (59, "59 s"), (60, "1 min"), (719, "11 min"), (3599, "59 min"),
                                           (3600, "1 h"), (86399, "23 h"), (86400, "1 d"), (9 * 86400, "9 d")])
def test_age_text(seconds, text):
    assert remote.age_text(seconds) == text


# ---------------------------------------------------------------- labels
def test_configured_names_come_from_the_destination_and_stay_unique():
    assert remote.source_names(["ssh:ops@Atlas.Example", "ssh:root@atlas.example", "file:atlas.example", "ssh:" + "h" * 40,
                                "ssh:a@.x", "ssh:b@_y"]) == [
        "atlas.example", "atlas.example-2", "atlas.example-3", "h" * 32, "source-5", "source-6"]


def test_two_documents_claiming_one_label_get_distinct_keys(ssh, tmp_path):
    ssh.outcomes.update({"one": raw(document("atlas")), "two": raw(document("atlas"))})
    first, second = fetch(["ssh:one", "ssh:two"], tmp_path)
    assert (first.label, second.label) == ("atlas", "two")


def test_status_text_for_each_state(ssh, tmp_path):
    ssh.outcomes.update({"up": raw(document()), "down": subprocess.TimeoutExpired(["ssh"], 5), "odd": b"{}"})
    texts = [remote.status(src, time.time(), 300)["text"] for src in fetch(["ssh:up", "ssh:down", "ssh:odd"], tmp_path)]
    assert texts[0].startswith("ok · ") and texts[1] == "unreachable (timeout)" and texts[2] == "invalid (schema: unsupported)"
    assert all(len(text) <= 120 for text in texts)


def test_remote_schema_is_what_validates(ssh, tmp_path, monkeypatch):
    seen = []
    real = remote_schema.validate
    monkeypatch.setattr(remote_schema, "validate", lambda doc: seen.append(doc) or real(doc))
    ssh.outcomes["atlas"] = raw(document())
    fetch(["ssh:atlas"], tmp_path)
    assert len(seen) == 1
