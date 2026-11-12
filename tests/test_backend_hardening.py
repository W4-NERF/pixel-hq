"""D17, D19, D21 (backend), D22: atomic loader publication, symlinks, review idempotency, pinned page assets."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from dashboard import plugin_api as api
from pixelhq import reviews, roster

ROOT = Path(__file__).resolve().parents[1]
RID = "0123456789abcdef"
SYMLINK_MESSAGE = "The review ledger is a symlink; set reviews_path to the real file."


def run(script, *args, cwd, env=None, timeout=120):
    environment = {**os.environ, "PYTHONNOUSERSITE": "1", **(env or {})}
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd, env=environment,
                          capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- D17: loader publication

THREAD_RACE = '''
import importlib.util, json, sys, threading
from pathlib import Path
root, runs = Path(sys.argv[1]), int(sys.argv[2])
LOADER, PACKAGE = "pixelhq_plugin_loader", "pixelhq_plugin"
expected = sorted(p.stem for p in (root / "pixelhq").glob("*.py") if not p.stem.startswith("_"))
sys.setswitchinterval(1e-6)  # force thread switches inside the check-then-act windows

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    return importlib.util.module_from_spec(spec), spec

builds = []
real = importlib.util.module_from_spec
def counting(spec):
    builds.append(spec.name)
    return real(spec)
importlib.util.module_from_spec = counting

def clean():
    for name in [n for n in sys.modules if n.startswith("pixelhq_plugin")]:
        del sys.modules[name]
    builds.clear()

good, failures = 0, []
for run in range(runs):
    clean()
    init, init_spec = load(f"init_run{run}", root / "__init__.py")
    init_spec.loader.exec_module(init)
    barrier, out, errors = threading.Barrier(2), {}, []

    def tool_entry():
        try:
            barrier.wait()
            out["init"] = init._package()
        except BaseException as exc:
            errors.append(f"tool: {type(exc).__name__}: {exc}")

    def route_entry():
        try:
            api, api_spec = load(f"api_run{run}", root / "dashboard" / "plugin_api.py")
            barrier.wait()
            api_spec.loader.exec_module(api)
            out["api"], out["api_module"] = api._PACKAGE, api
        except BaseException as exc:
            errors.append(f"routes: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=tool_entry), threading.Thread(target=route_entry)]
    [t.start() for t in threads]; [t.join() for t in threads]
    problems = list(errors)
    if not errors:
        package = out["init"]
        if package is not out["api"]:
            problems.append("two package objects")
        missing = [n for n in expected if not hasattr(package, n)]
        if missing:
            problems.append("missing modules " + ",".join(missing))
        if not getattr(package, "_pixelhq_ready", False):
            problems.append("no ready marker")
        if not (init._loader() is out["api_module"]._loader() is sys.modules[LOADER]):
            problems.append("more than one loader module in use")
        if builds.count(PACKAGE) != 1:
            problems.append(f"package built {builds.count(PACKAGE)} times")
    if problems:
        failures.append({"run": run, "problems": problems})
    else:
        good += 1
print(json.dumps({"runs": runs, "good": good, "modules": len(expected), "failures": failures[:3]}))
'''


def test_two_entry_points_racing_share_one_package_and_one_loader(tmp_path):
    probe = tmp_path / "race.py"
    probe.write_text(THREAD_RACE, encoding="utf-8")
    result = run(probe, ROOT, 50, cwd=tmp_path, env={"HERMES_HOME": str(tmp_path / "home")})
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    print(f"{report['good']}/{report['runs']} same package, {report['modules']} modules")
    assert report["failures"] == []
    assert (report["good"], report["runs"], report["modules"]) == (50, 50, 15)


READY_MARKER = '''
import importlib.util, json, sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("probe_loader", root / "pixelhq_loader.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
first = loader.load()
report = {"ready": first._pixelhq_ready is True, "again": loader.load() is first}
del first._pixelhq_ready                      # an interrupted load leaves a package without the marker
second = loader.load()
report.update(replaced=second is not first, ready_again=second._pixelhq_ready is True,
              modules=all(hasattr(second, n) for n in ("config", "reviews", "page", "collect")),
              one=sum(1 for n in sys.modules if n == "pixelhq_plugin") == 1)
print(json.dumps(report))
'''


def test_a_package_without_the_ready_marker_is_discarded_and_loaded_again(tmp_path):
    probe = tmp_path / "marker.py"
    probe.write_text(READY_MARKER, encoding="utf-8")
    result = run(probe, ROOT, cwd=tmp_path, env={"HERMES_HOME": str(tmp_path / "home")})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ready": True, "again": True, "replaced": True, "ready_again": True,
                                         "modules": True, "one": True}


def test_the_loader_holds_its_lock_for_the_whole_load():
    source = (ROOT / "pixelhq_loader.py").read_text(encoding="utf-8")
    body = source[source.index("def load()"):source.index("def module(")]
    assert body.index("with _LOCK:") < body.index("exec_module") < body.index("setattr(package, READY, True)")
    for entry in (ROOT / "__init__.py", ROOT / "dashboard" / "plugin_api.py"):
        text = entry.read_text(encoding="utf-8")
        assert "sys.modules.setdefault(spec.name, candidate)" in text, entry.name
        assert text.index("exec_module(candidate)") < text.index("sys.modules.setdefault("), entry.name
        assert "sys.modules[spec.name] =" not in text, entry.name


# ---------------------------------------------------------------- D19: symlinks are refused

def _roster_body():
    return {"roster": {
        "rooms": [{"id": "hq", "label": "Headquarters", "main": True, "zones": [{"id": "crew", "label": "Crew"}]}],
        "bots": [{"id": "ops-bot", "cls": "Engineer", "title": "Recruit", "zone": "crew", "color": "#93a1af"}]}}


def _roster_files(home):
    folder = home / "plugin-data" / "pixel-hq"
    folder.mkdir(parents=True)
    return folder / "roster.json", folder / "roster.json.bak"


@pytest.mark.parametrize("body", [_roster_body(), {"reset": True}], ids=["save", "reset"])
def test_a_symlinked_roster_is_neither_read_nor_replaced(tmp_path, body):
    live, backup = _roster_files(tmp_path / "home")
    target = tmp_path / "elsewhere.json"
    target.write_text('{"keep": "me"}\n', encoding="utf-8")
    live.symlink_to(target)
    result = roster.save(body, {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})
    assert result == {"ok": False, "message": "roster.json is not a regular file"}
    assert target.read_text(encoding="utf-8") == '{"keep": "me"}\n'
    assert live.is_symlink() and os.readlink(live) == str(target)
    assert not backup.exists() and not backup.is_symlink()
    assert sorted(p.name for p in live.parent.iterdir()) == ["roster.json"]  # no temporary files left


def test_a_symlinked_backup_is_refused_and_nothing_is_written(tmp_path):
    live, backup = _roster_files(tmp_path / "home")
    target = tmp_path / "victim.bak"
    target.write_text("victim\n", encoding="utf-8")
    live.write_text('{"rooms": [], "bots": []}\n', encoding="utf-8")
    backup.symlink_to(target)
    result = roster.save(_roster_body(), {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})
    assert result == {"ok": False, "message": "roster.json is not a regular file"}
    assert target.read_text(encoding="utf-8") == "victim\n"
    assert live.read_text(encoding="utf-8") == '{"rooms": [], "bots": []}\n'
    assert backup.is_symlink()


@pytest.mark.parametrize("kind", ["dangling", "directory"])
def test_other_non_regular_roster_files_are_refused(tmp_path, kind):
    live, backup = _roster_files(tmp_path / "home")
    if kind == "dangling":
        live.symlink_to(tmp_path / "does-not-exist.json")
    else:
        live.mkdir()
    result = roster.save(_roster_body(), {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})
    assert result == {"ok": False, "message": "roster.json is not a regular file"}
    assert not (tmp_path / "does-not-exist.json").exists() and not backup.exists()


def test_regular_roster_files_still_save_with_a_backup(tmp_path):
    live, backup = _roster_files(tmp_path / "home")
    live.write_text("old\n", encoding="utf-8")
    assert roster.save(_roster_body(), {"hermes_home": str(tmp_path / "home")}, {"ops-bot": {}})["ok"]
    assert backup.read_text(encoding="utf-8") == "old\n" and "ops-bot" in live.read_text(encoding="utf-8")


@pytest.fixture(params=["nofollow", "lstat-only"])
def platform(request, monkeypatch):
    """The same refusal with O_NOFOLLOW (POSIX) and through lstat alone (platforms without the flag)."""
    if request.param == "lstat-only":
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    return request.param


def test_a_symlinked_ledger_is_refused_and_its_target_untouched(tmp_path, platform):
    target = tmp_path / "other.jsonl"
    target.write_text('{"keep": true}\n', encoding="utf-8")
    ledger = tmp_path / "reviews.jsonl"
    ledger.symlink_to(target)
    result = reviews.append({"agent": "ops-bot", "verdict": "pass", "rid": RID}, {"reviews_path": str(ledger)},
                            {"ops-bot"})
    assert result == {"ok": False, "message": SYMLINK_MESSAGE}
    assert target.read_bytes() == b'{"keep": true}\n'


def test_a_dangling_ledger_symlink_does_not_create_its_target(tmp_path, platform):
    ledger = tmp_path / "reviews.jsonl"
    ledger.symlink_to(tmp_path / "created-by-mistake.jsonl")
    result = reviews.append({"agent": "ops-bot", "verdict": "pass"}, {"reviews_path": str(ledger)}, {"ops-bot"})
    assert result == {"ok": False, "message": SYMLINK_MESSAGE}
    assert not (tmp_path / "created-by-mistake.jsonl").exists()


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
def test_o_nofollow_alone_stops_a_link_swapped_in_after_the_lstat(tmp_path, monkeypatch):
    target = tmp_path / "other.jsonl"
    target.write_text("keep\n", encoding="utf-8")
    ledger = tmp_path / "reviews.jsonl"
    ledger.symlink_to(target)
    monkeypatch.setattr(reviews, "_refuse_symlink", lambda path: None)
    result = reviews.append({"agent": "ops-bot", "verdict": "pass"}, {"reviews_path": str(ledger)}, {"ops-bot"})
    assert result == {"ok": False, "message": SYMLINK_MESSAGE}
    assert target.read_text(encoding="utf-8") == "keep\n"


def test_the_tool_path_reports_the_symlink_message(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    ledger.symlink_to(tmp_path / "other.jsonl")
    result = reviews.append_tool({"agent": "helper", "verdict": "pass"}, {"reviews_path": str(ledger)}, "ops-bot")
    assert result == {"ok": False, "message": SYMLINK_MESSAGE}


def test_a_regular_ledger_still_works_without_o_nofollow(tmp_path, platform):
    ledger = tmp_path / "reviews.jsonl"
    assert reviews.append({"agent": "ops-bot", "verdict": "pass"}, {"reviews_path": str(ledger)}, {"ops-bot"})["ok"]
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


# ---------------------------------------------------------------- D21: review idempotency

def _post(ledger, **extra):
    return reviews.append({"agent": "ops-bot", "verdict": "pass", "ref": "Sample", **extra},
                          {"reviews_path": str(ledger)}, {"ops-bot"})


def test_a_repeated_rid_is_recorded_once(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    assert _post(ledger, rid=RID) == {"ok": True, "message": "Review saved."}
    before = ledger.read_bytes()
    assert json.loads(before)["rid"] == RID
    assert _post(ledger, rid=RID) == {"ok": True, "message": "Review already recorded."}
    assert ledger.read_bytes() == before
    assert _post(ledger, rid="fedcba9876543210")["message"] == "Review saved."
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_reviews_without_a_rid_are_never_deduplicated(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    assert [_post(ledger)["message"] for _ in range(3)] == ["Review saved."] * 3
    assert all("rid" not in json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("rid", ["", "0123456789abcde", "0" * 33, "0123456789ABCDEF", "0123456789abcdeg",
                                 RID + "\n", " " + RID, 123, None, ["a"] * 16, True, {"rid": RID}])
def test_an_invalid_rid_is_rejected_without_writing(tmp_path, rid):
    ledger = tmp_path / "reviews.jsonl"
    result = _post(ledger, rid=rid)
    assert result == {"ok": False, "message": "Invalid rid: use 16–32 lowercase hex characters."}
    assert not ledger.exists()
    ledger.write_text("existing\n", encoding="utf-8")
    assert _post(ledger, rid=rid)["ok"] is False and ledger.read_text(encoding="utf-8") == "existing\n"


@pytest.mark.parametrize("rid", ["0" * 16, "f" * 32, "0123456789abcdef0123456789abcdef"])
def test_the_rid_length_limits_are_inclusive(tmp_path, rid):
    assert _post(tmp_path / "reviews.jsonl", rid=rid)["message"] == "Review saved."


def test_the_tool_path_sends_and_stores_no_rid(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    cfg = {"reviews_path": str(ledger)}
    args = {"agent": "helper", "verdict": "pass", "rid": RID}
    assert reviews.append_tool(args, cfg, "ops-bot")["message"] == "Review saved."
    assert reviews.append_tool(args, cfg, "ops-bot")["message"] == "Review saved."
    assert all("rid" not in json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines())


def _filler(count):
    return "".join(json.dumps({"agent": "ops-bot", "verdict": "pass", "ref": f"Filler {i}"}) + "\n"
                   for i in range(count))


def test_the_lookup_covers_the_last_64_kib_only(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    assert _post(ledger, rid=RID)["message"] == "Review saved."
    first = ledger.read_text(encoding="utf-8")
    ledger.write_text(first + _filler(900), encoding="utf-8")  # ~ 55 KiB: still inside the window
    assert 40_000 < len(ledger.read_bytes()) - len(first) < reviews.RID_WINDOW
    assert _post(ledger, rid=RID)["message"] == "Review already recorded."
    ledger.write_text(first + _filler(2000), encoding="utf-8")  # ~ 120 KiB: the record left the window
    assert _post(ledger, rid=RID)["message"] == "Review saved."


def test_a_record_cut_by_the_window_boundary_is_not_matched(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    record = (json.dumps({"agent": "ops-bot", "verdict": "pass", "rid": RID, "ref": ""}) + "\n").encode()
    pad = b'{"pad": "' + b"x" * (reviews.RID_WINDOW - 20) + b'"}\n'
    ledger.write_bytes(record + pad)
    assert len(pad) < reviews.RID_WINDOW  # the window starts inside the record that holds the rid
    assert _post(ledger, rid=RID)["message"] == "Review saved."


def test_the_lookup_copes_with_a_missing_final_newline_and_broken_lines(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    ledger.write_text('not json\n[1]\n{"agent": "ops-bot", "verdict": "pass", "rid": "' + RID + '"}',
                      encoding="utf-8")
    before = ledger.read_bytes()
    assert _post(ledger, rid=RID)["message"] == "Review already recorded."
    assert ledger.read_bytes() == before
    assert _post(ledger, rid="fedcba9876543210")["message"] == "Review saved."


def test_a_rid_quoted_inside_another_records_text_does_not_count(tmp_path):
    ledger = tmp_path / "reviews.jsonl"
    assert _post(ledger, ref=f'"rid": "{RID}"')["ok"]
    assert _post(ledger, rid=RID)["message"] == "Review saved."


def test_parallel_retries_of_one_draft_write_one_line(tmp_path):
    if reviews.fcntl is None:
        pytest.skip("the lock needs flock")
    ledger = tmp_path / "reviews.jsonl"
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _post(ledger, rid=RID), range(32)))
    assert sorted(r["message"] for r in results).count("Review saved.") == 1
    assert all(r["ok"] for r in results) and len(ledger.read_text(encoding="utf-8").splitlines()) == 1


@pytest.fixture
def app(fleet, monkeypatch):
    monkeypatch.setattr(api._module("config"), "_DIRS", [fleet.root / "plugin-data" / "pixel-hq"])
    monkeypatch.setattr(api, "_cache", {"t": 0.0, "data": None})
    monkeypatch.setattr(api, "_lock", asyncio.Lock())
    app = FastAPI()
    app.include_router(api.router)
    return app


def test_review_route_answers_a_repeated_rid_without_writing_again(app, fleet):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = {"agent": "ops-bot", "verdict": "pass", "dims": {"safety": 5}, "ref": "Sample", "rid": RID}
            first = await client.post("/review", json=body)
            assert first.status_code == 200 and first.json() == {"ok": True, "message": "Review saved."}
            before = fleet.reviews_path.read_bytes()
            second = await client.post("/review", json=body)
            assert second.status_code == 200
            assert second.json() == {"ok": True, "message": "Review already recorded."}
            assert fleet.reviews_path.read_bytes() == before
            bad = await client.post("/review", json={**body, "rid": "NOT-HEX"})
            assert bad.json() == {"ok": False, "message": "Invalid rid: use 16–32 lowercase hex characters."}
            assert fleet.reviews_path.read_bytes() == before
            fresh = (await client.get("/snapshot")).json()
            assert next(b for b in fresh["bots"] if b["id"] == "ops-bot")["xp"] == 10  # counted once
    asyncio.run(scenario())


def test_review_route_reports_a_symlinked_ledger(app, fleet, tmp_path):
    target = tmp_path / "other.jsonl"
    target.write_text("keep\n", encoding="utf-8")
    fleet.reviews_path.parent.mkdir(parents=True, exist_ok=True)
    fleet.reviews_path.symlink_to(target)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return (await client.post("/review", json={"agent": "ops-bot", "verdict": "pass"})).json()
    assert asyncio.run(scenario()) == {"ok": False, "message": SYMLINK_MESSAGE}
    assert target.read_text(encoding="utf-8") == "keep\n"


# ---------------------------------------------------------------- D22: the page belongs to the loaded version

PIN_PROBE = '''
import json, sys
from pathlib import Path
copy = Path(sys.argv[1])
sys.path.insert(0, str(copy))
from pixelhq import page
assert Path(page.__file__).resolve().is_relative_to(copy.resolve()), page.__file__
before, data_before = page.page_html(), page.page_html({"demo": True})
faces_before = page.font_faces()
ui = copy / "pixelhq" / "ui"
(ui / "js" / "00-core.js").write_text("/* replaced after import */ throw new Error('new UI code');\\n", encoding="utf-8")
(ui / "style.css").write_text("/* replaced */ body{display:none}\\n", encoding="utf-8")
(ui / "index.html").write_text("<!doctype html><title>replaced</title>\\n", encoding="utf-8")
for font in (copy / "pixelhq" / "fonts").glob("*.woff2"):
    font.write_bytes(b"replaced")
print(json.dumps({"same": page.page_html() == before, "same_data": page.page_html({"demo": True}) == data_before,
                  "same_fonts": page.font_faces() == faces_before, "has_old_js": "new UI code" not in before,
                  "fonts_embedded": "data:font/woff2;base64," in before}))
'''


@pytest.fixture
def installed(tmp_path):
    copy = tmp_path / "installed"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", ".git", ".qa", "dist", "var", "docs",
                                                              "tests", "tools", "desktop"))
    return copy


def test_page_html_serves_the_copy_read_at_import(installed, tmp_path):
    probe = tmp_path / "pin.py"
    probe.write_text(PIN_PROBE, encoding="utf-8")
    result = run(probe, installed, cwd=tmp_path, env={"HERMES_HOME": str(tmp_path / "home")})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"same": True, "same_data": True, "same_fonts": True,
                                         "has_old_js": True, "fonts_embedded": True}


ROUTE_PIN = '''
import asyncio, importlib.util, json, sys
from pathlib import Path
copy = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("api_copy", copy / "dashboard" / "plugin_api.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
before = asyncio.run(api.page())["html"]
(copy / "pixelhq" / "ui" / "js" / "00-core.js").write_text("throw new Error('new UI code');\\n", encoding="utf-8")
after = asyncio.run(api.page())["html"]
print(json.dumps({"same": before == after, "old_script": "new UI code" not in after, "size": len(after) > 10000}))
'''


def test_the_page_route_keeps_serving_the_loaded_ui(installed, tmp_path):
    probe = tmp_path / "route.py"
    probe.write_text(ROUTE_PIN, encoding="utf-8")
    result = run(probe, installed, cwd=tmp_path, env={"HERMES_HOME": str(tmp_path / "home")})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"same": True, "old_script": True, "size": True}


def test_a_fresh_render_process_reads_the_files_on_disk(installed, tmp_path):
    marker = "/* edited on disk before the render process started */"
    core = "00-core.js"
    (installed / "pixelhq" / "ui" / "js" / core).write_text(
        marker + "\n" + (ROOT / "pixelhq" / "ui" / "js" / core).read_text(encoding="utf-8"), encoding="utf-8")
    result = run(installed / "pixelhq" / "render.py", "--demo", cwd=tmp_path,
                 env={"PYTHONPATH": "", "HERMES_HOME": str(tmp_path / "home")})
    assert result.returncode == 0, result.stderr
    html = (installed / "dist" / "pixel-hq.html").read_text(encoding="utf-8")
    assert marker in html and html.count('"demo": true') == 1


def test_a_relative_ledger_symlink_is_not_resolved_away_by_the_config(tmp_path):
    """Otherwise the writer would only ever see the link's target and could not refuse the link (D19)."""
    from pixelhq.config import ledger_path

    folder = tmp_path / "plugin-data" / "pixel-hq"
    folder.mkdir(parents=True)
    (folder / "linked.jsonl").symlink_to(tmp_path / "elsewhere.jsonl")
    cfg = {"hermes_home": str(tmp_path)}
    assert ledger_path(cfg | {"reviews_path": "linked.jsonl"}) == str(folder.resolve() / "linked.jsonl")
    assert ledger_path(cfg | {"reviews_path": "plain.jsonl"}) == str(folder.resolve() / "plain.jsonl")
    assert ledger_path(cfg | {"reviews_path": "sub/../plain.jsonl"}) == str(folder.resolve() / "plain.jsonl")
