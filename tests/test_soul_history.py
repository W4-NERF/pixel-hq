"""SOUL history store (round-4 §4): keys, atomic 0600 writes, limits, retention, idempotency, refusals."""
import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pixelhq import soul_history as sh

START = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")


@pytest.fixture
def cfg(tmp_path):
    return {"hermes_home": str(tmp_path / "home")}


def rid(n: int = 1) -> str:
    return f"{n:08x}" + "0" * 24


def at(seconds: int) -> datetime:
    return START + timedelta(seconds=seconds)


def body(text="You are a careful reviewer.", n=1, bot="ops-bot", source="local"):
    return {"bot": bot, "sourceKey": source, "text": text, "rid": rid(n)}


def store(cfg, source="local", bot="ops-bot") -> Path:
    return Path(cfg["hermes_home"]) / "plugin-data" / "pixel-hq" / "soul-history" / source / bot


def files(cfg, **kw):
    return sorted(p.name for p in store(cfg, **kw).iterdir())


def refused(call, status=400):
    with pytest.raises(sh.HistoryError) as caught:
        call()
    assert caught.value.status == status
    return caught.value.message


# ---------------------------------------------------------------- key derivation and validation

@pytest.mark.parametrize("value, key", [
    ("local", "local"), ("Ops-Bot", "ops-bot"), ("a", "a"), ("0abc", "0abc"), ("conn.1_x-y", "conn.1_x-y"),
    ("A" * 64, "a" * 64), ("9" * 64, "9" * 64)])
def test_key_part_accepts_the_fixed_pattern_after_lower_casing(value, key):
    assert sh.key_part(value, "bot") == key


@pytest.mark.parametrize("value", [
    "", ".", "..", ".hidden", "-lead", "_lead", "a/b", "a\\b", "../x", "..\\x", "/abs", "a b", "a\nb", "a\x00b", "ok\n",
    "a:b", "a*b", "~", "a" * 65, "9" * 65])
def test_key_part_refuses_traversal_syntax_odd_characters_and_length_65(value):
    assert refused(lambda: sh.key_part(value, "bot")).startswith("bot:")


@pytest.mark.parametrize("value", [
    "caf\u00e9", "\u212a", "\u0130stanbul", "\uff41bc", "\u0430bc", "bot\u202e", "\u00df", "\U0001f916", "a\u0301"])
def test_key_part_refuses_unicode_even_where_lower_casing_would_make_it_ascii(value):
    # U+212A (Kelvin sign) lower-cases to ASCII "k"; it must not slip through.
    assert refused(lambda: sh.key_part(value, "sourceKey")).startswith("sourceKey:")


@pytest.mark.parametrize("value", [None, 1, 1.5, True, [], {}, b"local"])
def test_key_part_refuses_non_strings(value):
    refused(lambda: sh.key_part(value, "bot"))


def test_length_64_is_stored_and_length_65_is_refused_without_touching_disk(cfg):
    assert sh.save(body(bot="b" * 64, source="s" * 64), cfg, at(0))["ok"] is True
    assert len(files(cfg, source="s" * 64, bot="b" * 64)) == 1
    before = sorted(Path(cfg["hermes_home"]).rglob("*"))
    refused(lambda: sh.save(body(bot="b" * 65), cfg, at(1)))
    refused(lambda: sh.save(body(source="s" * 65), cfg, at(1)))
    assert sorted(Path(cfg["hermes_home"]).rglob("*")) == before


def test_upper_and_lower_case_names_share_one_history(cfg):
    sh.save(body(bot="Ops-Bot", source="LOCAL", n=1), cfg, at(0))
    sh.save(body(bot="ops-bot", source="local", n=2), cfg, at(1))
    assert len(files(cfg)) == 2 and len(sh.list_versions("OPS-BOT", "Local", cfg)) == 2


@pytest.mark.parametrize("bad", [
    {"bot": "../escape", "sourceKey": "local"}, {"bot": "ops-bot", "sourceKey": "../escape"},
    {"bot": "ops-bot", "sourceKey": "local/../../x"}, {"bot": "..", "sourceKey": "local"},
    {"bot": "ops-bot", "sourceKey": "/etc"}])
def test_path_traversal_in_bot_or_source_is_refused_and_nothing_is_created(cfg, tmp_path, bad):
    refused(lambda: sh.save({**body(), **bad}, cfg, at(0)))
    assert not (tmp_path / "home").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("missing", ["bot", "sourceKey", "text"])
def test_a_missing_field_is_refused(cfg, missing):
    refused(lambda: sh.save({k: v for k, v in body().items() if k != missing}, cfg, at(0)))
    assert not Path(cfg["hermes_home"]).exists()


def test_body_keys_that_look_like_paths_are_ignored(cfg, tmp_path):
    extra = {**body(), "path": str(tmp_path / "elsewhere"), "hermes_home": str(tmp_path / "other"), "dir": "../x"}
    assert sh.save(extra, cfg, at(0))["ok"]
    assert len(files(cfg)) == 1
    assert not (tmp_path / "elsewhere").exists() and not (tmp_path / "other").exists()


@pytest.mark.parametrize("value", [None, 7, "short", "G" * 16, "A" * 16, "a" * 15, "a" * 33, "a" * 16 + "\n", ["a" * 16]])
def test_rid_must_be_16_to_32_lowercase_hex(cfg, value):
    refused(lambda: sh.save({**body(), "rid": value}, cfg, at(0)))
    assert not Path(cfg["hermes_home"]).exists()


@pytest.mark.parametrize("value", [None, [], "text", 3])
def test_body_must_be_an_object(cfg, value):
    assert refused(lambda: sh.save(value, cfg, at(0))) == "body: expected an object."


# ---------------------------------------------------------------- atomic write and modes

@POSIX_ONLY
def test_file_is_0600_and_every_directory_level_is_0700(cfg):
    old = os.umask(0)  # a permissive umask must not widen anything
    try:
        sh.save(body(), cfg, at(0))
    finally:
        os.umask(old)
    leaf = store(cfg)
    for directory in (leaf, leaf.parent, leaf.parent.parent):
        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700, directory.name
    (name,) = files(cfg)
    assert stat.S_IMODE(os.stat(leaf / name).st_mode) == 0o600


@POSIX_ONLY
def test_existing_looser_directories_are_tightened_on_write(cfg):
    leaf = store(cfg)
    leaf.mkdir(parents=True)
    for directory in (leaf, leaf.parent, leaf.parent.parent):
        os.chmod(directory, 0o755)
    sh.save(body(), cfg, at(0))
    assert {stat.S_IMODE(os.stat(d).st_mode) for d in (leaf, leaf.parent, leaf.parent.parent)} == {0o700}


def test_successful_write_leaves_no_temporary_files(cfg):
    for n in range(4):
        sh.save(body(n=n + 1), cfg, at(n))
    assert all(sh.FILE_RE.fullmatch(name) for name in files(cfg)) and len(files(cfg)) == 4
    assert not [p for p in Path(cfg["hermes_home"]).rglob("*") if p.name.endswith(".tmp") or p.name.startswith(".")]


def test_failed_replace_leaves_neither_target_nor_temporary_file_and_keeps_old_versions(cfg, monkeypatch):
    sh.save(body("first", 1), cfg, at(0))
    before = files(cfg)

    def broken(*args, **kwargs):
        raise OSError("disk full at /private/place")
    monkeypatch.setattr(os, "replace", broken)
    message = refused(lambda: sh.save(body("second", 2), cfg, at(1)), 500)
    assert "/private" not in message and "disk full" not in message
    assert files(cfg) == before


def test_file_name_is_utc_timestamp_and_the_full_rid(cfg):
    sh.save({**body(), "rid": "0123456789abcdef"}, cfg, at(65))
    assert files(cfg) == ["20261112T100105Z-0123456789abcdef.md"]


def test_the_previous_soul_is_stored_verbatim_as_utf8(cfg):
    text = "  \tLeading space kept \u00e9\u4e2d\U0001f916  \n\n## Section\n  trailing spaces  \n\n"
    sh.save(body(text), cfg, at(0))
    (name,) = files(cfg)
    assert (store(cfg) / name).read_bytes() == text.encode("utf-8")


# ---------------------------------------------------------------- text rules and size limit

def test_crlf_and_lone_cr_are_normalised_to_newline(cfg):
    sh.save(body("one\r\ntwo\rthree\nfour\r\n\r\nfive", 1), cfg, at(0))
    (name,) = files(cfg)
    assert (store(cfg) / name).read_bytes() == b"one\ntwo\nthree\nfour\n\nfive"


@pytest.mark.parametrize("code", [c for c in range(0x20) if chr(c) not in "\t\n\r"])
def test_nul_and_other_c0_controls_are_refused(cfg, code):
    assert refused(lambda: sh.save(body(f"before{chr(code)}after"), cfg, at(0))).startswith("text:")
    assert not Path(cfg["hermes_home"]).exists()


def test_tab_newline_and_normalised_returns_are_the_only_controls_allowed(cfg):
    assert sh.save(body("a\tb\nc\r\nd\re"), cfg, at(0))["ok"]


@pytest.mark.parametrize("text", [None, 5, b"bytes", ["x"], "lone\ud800surrogate"])
def test_text_must_be_valid_unicode_string(cfg, text):
    refused(lambda: sh.save(body(text), cfg, at(0)))


def test_size_limit_boundary_is_65536_bytes(cfg):
    assert sh.save(body("a" * 65536, 1), cfg, at(0))["ok"]
    assert "64 KiB" in refused(lambda: sh.save(body("a" * 65537, 2), cfg, at(1)))
    assert len(files(cfg)) == 1


def test_size_limit_counts_utf8_bytes_not_characters(cfg):
    assert sh.save(body("\u00e9" * 32768, 1), cfg, at(0))["ok"]          # 65536 bytes
    refused(lambda: sh.save(body("\u00e9" * 32768 + "a", 2), cfg, at(1)))  # 65537 bytes


def test_size_limit_applies_after_line_ending_normalisation(cfg):
    assert sh.save(body("\r\n" * 32768, 1), cfg, at(0))["ok"]             # 65536 raw -> 32768 stored
    assert sh.save(body("a\r\n" * 21845, 2), cfg, at(1))["ok"]            # 65535 raw -> 43690 stored
    refused(lambda: sh.save(body("\n" * 65537, 3), cfg, at(2)))


def test_an_empty_soul_can_be_backed_up(cfg):
    sh.save(body("", 1), cfg, at(0))
    assert sh.list_versions("ops-bot", "local", cfg)[0]["bytes"] == 0
    assert sh.list_versions("ops-bot", "local", cfg)[0]["firstLine"] == ""


# ---------------------------------------------------------------- retention

def test_twelve_writes_keep_the_ten_newest_and_delete_the_oldest(cfg):
    for n in range(12):
        sh.save(body(f"version {n}", n + 1), cfg, at(n))
    names = files(cfg)
    assert len(names) == 10
    assert not any(name.startswith("20261112T10000" + d) for d in "01" for name in names)  # seconds 00 and 01 gone
    assert names[0].startswith("20261112T100002Z") and names[-1].startswith("20261112T100011Z")


def test_retention_is_per_bot_and_per_source(cfg):
    for n in range(11):
        sh.save(body(n=n + 1), cfg, at(n))
    sh.save(body(n=50, bot="other-bot"), cfg, at(0))
    sh.save(body(n=51, source="conn-1"), cfg, at(0))
    assert (len(files(cfg)), len(files(cfg, bot="other-bot")), len(files(cfg, source="conn-1"))) == (10, 1, 1)


def test_retention_never_removes_the_file_just_written_even_with_an_old_clock(cfg):
    for n in range(10):
        sh.save(body(n=n + 1), cfg, at(100 + n))
    sh.save(body("clock went back", 99), cfg, at(0))
    names = files(cfg)
    assert len(names) == 10 and "20261112T100000Z-00000063000000000000000000000000.md" in names


def test_retention_leaves_foreign_names_and_links_alone(cfg, tmp_path):
    leaf = store(cfg)
    leaf.mkdir(parents=True)
    (leaf / "notes.txt").write_text("keep", encoding="utf-8")
    (leaf / "19990101T000000Z-aaaaaaaa.md.bak").write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    os.symlink(outside, leaf / "19990101T000000Z-bbbbbbbb.md")
    for n in range(11):
        sh.save(body(n=n + 1), cfg, at(n))
    assert {"notes.txt", "19990101T000000Z-aaaaaaaa.md.bak", "19990101T000000Z-bbbbbbbb.md"} <= set(files(cfg))
    assert outside.read_text(encoding="utf-8") == "outside"
    assert len([n for n in files(cfg) if n.startswith("2026")]) == 10


# ---------------------------------------------------------------- idempotent request id

def test_same_rid_twice_writes_one_file_and_keeps_the_first_text(cfg):
    assert sh.save(body("first", 7), cfg, at(0)) == {"ok": True, "message": "SOUL version saved."}
    assert sh.save(body("retry", 7), cfg, at(30)) == {"ok": True, "message": "SOUL version already saved."}
    (name,) = files(cfg)
    assert name.startswith("20261112T100000Z") and (store(cfg) / name).read_text(encoding="utf-8") == "first"


def test_two_rids_with_the_same_eight_characters_are_two_saves(cfg):
    first = {**body("previous A"), "rid": "12345678aaaaaaaa"}
    second = {**body("previous B"), "rid": "12345678bbbbbbbb"}
    assert sh.save(first, cfg, at(0)) == {"ok": True, "message": "SOUL version saved."}
    assert sh.save(second, cfg, at(1)) == {"ok": True, "message": "SOUL version saved."}
    assert sorted(files(cfg)) == ["20261112T100000Z-12345678aaaaaaaa.md", "20261112T100001Z-12345678bbbbbbbb.md"]
    rows = sh.list_versions("ops-bot", "local", cfg)
    assert [r["firstLine"] for r in rows] == ["previous B", "previous A"]
    assert sh.item("ops-bot", "local", rows[0]["id"], cfg) == {"text": "previous B"}


def test_the_same_full_rid_twice_is_one_file_with_the_first_text(cfg):
    one = {**body("first"), "rid": "12345678aaaaaaaa"}
    assert sh.save(one, cfg, at(0))["message"] == "SOUL version saved."
    assert sh.save({**one, "text": "retry"}, cfg, at(9))["message"] == "SOUL version already saved."
    assert files(cfg) == ["20261112T100000Z-12345678aaaaaaaa.md"]


def test_same_rid_for_another_bot_is_a_separate_save(cfg):
    sh.save(body(n=7), cfg, at(0))
    sh.save(body(n=7, bot="other-bot"), cfg, at(0))
    assert (len(files(cfg)), len(files(cfg, bot="other-bot"))) == (1, 1)


def test_concurrent_retries_with_one_rid_leave_one_file(cfg):
    results = []

    def run():
        results.append(sh.save(body("same", 5), cfg))
    threads = [threading.Thread(target=run) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 8 and all(r["ok"] for r in results) and len(files(cfg)) == 1


# ---------------------------------------------------------------- symlink and non-regular refusals

@pytest.mark.parametrize("level", ["plugin-data", "pixel-hq"])
def test_the_user_managed_levels_above_the_store_may_be_links(cfg, tmp_path, level):
    """R4-D4: like the directory of roster.json, plugin-data/ and plugin-data/pixel-hq/ may live on another disk."""
    elsewhere = tmp_path / "other-disk"
    elsewhere.mkdir()
    home = Path(cfg["hermes_home"])
    if level == "plugin-data":
        home.mkdir()
        os.symlink(elsewhere, home / "plugin-data")
    else:
        (home / "plugin-data").mkdir(parents=True)
        os.symlink(elsewhere, home / "plugin-data" / "pixel-hq")
    assert sh.save(body("kept"), cfg, at(0))["ok"] is True
    (name,) = files(cfg)
    assert sh.item("ops-bot", "local", name, cfg) == {"text": "kept"}
    assert [r["firstLine"] for r in sh.list_versions("ops-bot", "local", cfg)] == ["kept"]
    assert [p.name for p in elsewhere.rglob("*.md")] == [name]


@pytest.mark.parametrize("level", ["root", "source", "bot"])
def test_a_symlinked_directory_is_refused_for_write_list_and_item(cfg, tmp_path, level):
    target = tmp_path / "elsewhere"
    target.mkdir()
    leaf = store(cfg)
    link = {"root": leaf.parent.parent, "source": leaf.parent, "bot": leaf}[level]
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)
    if level != "bot":
        (target / "ops-bot" if level == "source" else target / "local" / "ops-bot").mkdir(parents=True)
    assert "not a regular directory" in refused(lambda: sh.save(body(), cfg, at(0)), 409)
    refused(lambda: sh.list_versions("ops-bot", "local", cfg), 409)
    refused(lambda: sh.item("ops-bot", "local", "20261112T100000Z-00000001000000000000000000000000.md", cfg), 409)
    assert not [p for p in target.rglob("*") if p.is_file()]


def test_a_regular_file_where_a_directory_belongs_is_refused(cfg):
    root = store(cfg).parent.parent
    root.parent.mkdir(parents=True)
    root.write_text("not a directory", encoding="utf-8")
    refused(lambda: sh.save(body(), cfg, at(0)), 409)


@pytest.mark.parametrize("kind", ["dangling", "outside", "directory"])
def test_an_irregular_entry_under_the_request_id_is_refused_and_untouched(cfg, tmp_path, kind):
    leaf = store(cfg)
    leaf.mkdir(parents=True)
    name = leaf / "20261112T100000Z-00000001000000000000000000000000.md"
    outside = tmp_path / "outside.md"
    if kind == "dangling":
        os.symlink(tmp_path / "missing.md", name)
    elif kind == "outside":
        outside.write_text("do not touch", encoding="utf-8")
        os.symlink(outside, name)
    else:
        name.mkdir()
    assert "not a regular file" in refused(lambda: sh.save(body("x", 1), cfg, at(0)), 409)
    assert name.is_symlink() or name.is_dir()
    assert not outside.exists() or outside.read_text(encoding="utf-8") == "do not touch"


def test_the_exact_target_name_as_a_link_is_refused_even_under_another_request_id(cfg, tmp_path):
    leaf = store(cfg)
    leaf.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("do not touch", encoding="utf-8")
    os.symlink(outside, leaf / "20261112T100000Z-00000002000000000000000000000000.md")
    refused(lambda: sh.save(body("x", 2), cfg, at(0)), 409)
    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_links_and_directories_are_neither_listed_nor_readable(cfg, tmp_path):
    sh.save(body("real", 1), cfg, at(0))
    leaf = store(cfg)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, leaf / "20261112T100001Z-00000002000000000000000000000000.md")
    (leaf / "20261112T100002Z-00000003000000000000000000000000.md").mkdir()
    assert [row["id"] for row in sh.list_versions("ops-bot", "local", cfg)] == ["20261112T100000Z-00000001000000000000000000000000.md"]
    refused(lambda: sh.item("ops-bot", "local", "20261112T100001Z-00000002000000000000000000000000.md", cfg), 404)
    refused(lambda: sh.item("ops-bot", "local", "20261112T100002Z-00000003000000000000000000000000.md", cfg), 404)


# ---------------------------------------------------------------- list and item

def test_list_is_newest_first_with_id_saved_at_bytes_and_first_line(cfg):
    sh.save(body("alpha\nmore", 1), cfg, at(0))
    sh.save(body("\n\n   beta \u00e9\nmore", 2), cfg, at(61))
    sh.save(body("gamma", 3), cfg, at(3600))
    rows = sh.list_versions("ops-bot", "local", cfg)
    assert [r["firstLine"] for r in rows] == ["gamma", "beta \u00e9", "alpha"]
    assert rows[0] == {"id": "20261112T110000Z-00000003000000000000000000000000.md", "savedAt": "2026-11-12T11:00:00Z",
                       "bytes": 5, "firstLine": "gamma"}
    assert rows[1]["savedAt"] == "2026-11-12T10:01:01Z" and rows[1]["bytes"] == len("\n\n   beta \u00e9\nmore".encode())
    assert set(rows[2]) == {"id", "savedAt", "bytes", "firstLine"}


@pytest.mark.parametrize("length", [79, 80, 81, 500])
def test_first_line_is_at_most_80_characters(cfg, length):
    sh.save(body("x" * length + "\nsecond line", 1), cfg, at(0))
    line = sh.list_versions("ops-bot", "local", cfg)[0]["firstLine"]
    assert len(line) == min(length, 80) and (length <= 80 or line.endswith("\u2026"))


def test_unknown_bot_or_source_has_an_empty_history_and_creates_nothing(cfg, tmp_path):
    assert sh.list_versions("ghost-bot", "local", cfg) == []
    assert sh.list_versions("ops-bot", "conn-9", cfg) == []
    assert not (tmp_path / "home").exists()


def test_list_and_item_round_trip_returns_exactly_what_was_saved(cfg):
    texts = ["# Soul one\nLine \u00e9\n", "tab\there\n\nend", "x" * 65536]
    for n, text in enumerate(texts):
        sh.save(body(text, n + 1), cfg, at(n))
    rows = sh.list_versions("ops-bot", "local", cfg)
    assert [sh.item("ops-bot", "local", row["id"], cfg)["text"] for row in rows] == texts[::-1]
    assert [row["bytes"] for row in rows] == [65536, len(texts[1]), len(texts[0].encode())]


def test_histories_are_separate_per_bot_and_per_source(cfg):
    sh.save(body("local text", 1), cfg, at(0))
    sh.save(body("remote text", 2, source="conn-1"), cfg, at(1))
    (local,) = sh.list_versions("ops-bot", "local", cfg)
    (remote,) = sh.list_versions("ops-bot", "conn-1", cfg)
    assert sh.item("ops-bot", "conn-1", remote["id"], cfg) == {"text": "remote text"}
    refused(lambda: sh.item("ops-bot", "conn-1", local["id"], cfg), 404)
    refused(lambda: sh.item("other-bot", "local", local["id"], cfg), 404)


def test_an_oversized_or_foreign_file_in_the_directory_is_not_listed(cfg):
    sh.save(body("fine", 1), cfg, at(0))
    leaf = store(cfg)
    (leaf / "20261112T100001Z-00000002000000000000000000000000.md").write_bytes(b"x" * (sh.MAX_BYTES + 1))
    (leaf / "20261313T100001Z-00000003000000000000000000000000.md").write_bytes(b"impossible date")
    (leaf / "README.md").write_bytes(b"foreign")
    assert [r["id"] for r in sh.list_versions("ops-bot", "local", cfg)] == ["20261112T100000Z-00000001000000000000000000000000.md"]
    refused(lambda: sh.item("ops-bot", "local", "20261112T100001Z-00000002000000000000000000000000.md", cfg), 404)


# ---------------------------------------------------------------- item ids

def test_a_well_formed_but_unlisted_id_is_404(cfg):
    sh.save(body("x", 1), cfg, at(0))
    assert refused(lambda: sh.item("ops-bot", "local", "20261112T100000Z-0000ffff000000000000000000000000.md", cfg), 404) == "No such version."
    refused(lambda: sh.item("ops-bot", "conn-1", "20261112T100000Z-00000001000000000000000000000000.md", cfg), 404)


@pytest.mark.parametrize("crafted", [
    "", "..", "../20261112T100000Z-00000001000000000000000000000000.md", "20261112T100000Z-00000001000000000000000000000000.md/", "/20261112T100000Z-00000001000000000000000000000000.md",
    "local/ops-bot/20261112T100000Z-00000001000000000000000000000000.md", "..\\20261112T100000Z-00000001000000000000000000000000.md", "20261112T100000Z-00000001",
    "20261112T100000Z-00000001.MD", "20261112t100000z-00000001.md", "20261112T100000Z-0000000G.md",
    "20261112T100000Z-00000001000000000000000000000000.md\n", "20261112T100000Z-00000001000000000000000000000000.md\x00", " 20261112T100000Z-00000001000000000000000000000000.md",
    "20261112T100000Z-00000001000000000000000000000000.md/../../x", "*.md", "20261112T100000Z-0000001.md", "20261112T100000Z-" + "0" * 33 + ".md", ".soul-abc.tmp", None, 5])
def test_a_crafted_id_is_400_even_when_the_real_file_exists(cfg, crafted):
    sh.save(body("x", 1), cfg, at(0))
    assert refused(lambda: sh.item("ops-bot", "local", crafted, cfg)).startswith("id:")


def test_messages_never_contain_paths_or_request_values(cfg, tmp_path):
    calls = (lambda: sh.save(body(bot="../secret-bot"), cfg, at(0)),
             lambda: sh.item("ops-bot", "local", "../secret-id", cfg),
             lambda: sh.item("ops-bot", "local", "20261112T100000Z-00000001000000000000000000000000.md", cfg))
    messages = []
    for call in calls:
        with pytest.raises(sh.HistoryError) as caught:
            call()
        messages.append(caught.value.message)
    assert len(messages) == 3
    assert not [m for m in messages if "secret" in m or str(tmp_path) in m or "/" in m]
