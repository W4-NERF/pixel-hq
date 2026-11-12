"""D12–D13: one consistent code version per backend process, scripts that still run, stale-backend notice."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pixelhq import config
from pixelhq.demo import snapshot as demo_snapshot
from pixelhq.page import page_html

ROOT = Path(__file__).resolve().parents[1]
GENERIC = "config common profiles scoring dbutil collect live reviews roster actions page demo blockers".split()


def run(script, *args, cwd, env=None, timeout=60):
    environment = {**os.environ, "PYTHONNOUSERSITE": "1", **(env or {})}
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd, env=environment,
                          capture_output=True, text=True, timeout=timeout)


LOAD_TWICE = '''
import importlib.util, json, sys
from pathlib import Path
root = Path(sys.argv[1])

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

names_before, path_before = set(sys.modules), list(sys.path)
api_one = load("api_one", root / "dashboard" / "plugin_api.py")
init_one = load("init_one", root / "__init__.py")
api_two = load("api_two", root / "dashboard" / "plugin_api.py")
init_two = load("init_two", root / "__init__.py")
package = api_one._PACKAGE
own = {"api_one", "init_one", "api_two", "init_two", "pixelhq_plugin_loader"}
foreign = sorted(name for name in set(sys.modules) - names_before
                 if name not in own and not name.startswith("pixelhq_plugin")
                 and str(getattr(sys.modules[name], "__file__", "") or "").startswith(str(root)))
print(json.dumps({
    "generic": [n for n in sys.argv[2:] if n in sys.modules and n not in names_before],
    "path_unchanged": sys.path == path_before,
    "foreign_repo_modules": foreign,
    "one_package": api_one._PACKAGE is api_two._PACKAGE is init_one._package() is init_two._package(),
    "same_modules": all(api_one._module(n) is api_two._module(n) is getattr(package, n) for n in sys.argv[2:]),
    "package_modules": sorted(n for n in sys.modules if n.startswith("pixelhq_plugin.")),
}))
'''


def test_loading_both_entry_points_twice_keeps_names_and_sys_path_clean(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(LOAD_TWICE, encoding="utf-8")
    result = run(probe, ROOT, *GENERIC, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["generic"] == []
    assert report["path_unchanged"] is True
    assert report["foreign_repo_modules"] == []
    assert report["one_package"] is True and report["same_modules"] is True
    assert {f"pixelhq_plugin.{name}" for name in GENERIC} <= set(report["package_modules"])


UPDATE_UNDER_RUNNING_BACKEND = '''
import asyncio, importlib.util, json, sys
from pathlib import Path
copy, mode = Path(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location("api_copy", copy / "dashboard" / "plugin_api.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

def update_files_on_disk():
    for path in (copy / "pixelhq").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if mode == "raise":
            text += "\\nraise RuntimeError('re-executed after the update')\\n"
        else:
            text = text.replace("reviews_path", "reviews_file")
        path.write_text(text, encoding="utf-8")
    manifest = copy / "plugin.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("version: 1.2.0", "version: 9.9.9"), encoding="utf-8")

async def main():
    first = await api.snapshot()
    update_files_on_disk()
    api._cache["data"] = None
    second = await api.snapshot()
    return {
        "first_cfg": [first["cfg"]["version"], first["cfg"]["diskVersion"]],
        "second_cfg": [second["cfg"]["version"], second["cfg"]["diskVersion"]],
        "bots": [sorted(b["id"] for b in first["bots"]), sorted(b["id"] for b in second["bots"])],
        "live_bots": sorted((await api.live())["bots"]),
        "page": "<script>" in (await api.page())["html"],
        "review": (await api.review({"agent": "ops-bot", "verdict": "pass"}))["ok"],
        "roster": (await api.roster({"roster": {}}))["ok"],
        "action": (await api.blocker_action({}))["ok"],
    }

print(json.dumps(asyncio.run(main())))
'''


@pytest.mark.parametrize("mode", ["raise", "rename"])
def test_files_updated_under_a_running_backend_keep_serving_the_loaded_version(fleet, tmp_path, mode):
    keep = shutil.ignore_patterns("__pycache__", ".git", ".qa", "dist", "var", "docs", "tests", "tools", "desktop")
    copy = tmp_path / "installed"
    shutil.copytree(ROOT, copy, ignore=keep)
    probe = tmp_path / "probe.py"
    probe.write_text(UPDATE_UNDER_RUNNING_BACKEND, encoding="utf-8")
    result = run(probe, copy, mode, cwd=tmp_path, env={"HERMES_HOME": str(fleet.root)})
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    expected = ["default", "ops-bot", "remote-bot"]
    assert report["bots"] == [expected, expected]
    # D13: the loaded version stays, the on-disk version follows the manifest.
    loaded = config.disk_version()
    assert report["first_cfg"] == [loaded, loaded]
    assert report["second_cfg"] == [loaded, "9.9.9"]
    assert report["live_bots"] == expected and report["page"] is True
    assert report["review"] is True and report["roster"] is False and report["action"] is False


@pytest.mark.parametrize("script, args", [("render.py", ["--demo"]), ("demo.py", []), ("blockers.py", []),
                                          ("collect.py", []), ("live.py", [])])
def test_scripts_run_directly_from_another_directory(fleet, tmp_path, script, args):
    result = run(ROOT / "pixelhq" / script, *args, cwd=tmp_path,
                 env={"PYTHONPATH": "", "HERMES_HOME": str(fleet.root)})
    assert result.returncode == 0, result.stderr
    if script == "render.py":
        out = Path(result.stdout.strip())
        assert out == ROOT / "dist" / "pixel-hq.html"
        assert out.read_text(encoding="utf-8").count('"demo": true') == 1
    else:
        assert isinstance(json.loads(result.stdout), dict)


def test_sys_path_is_only_touched_inside_the_main_guard():
    """The script bootstrap exists only under ``__main__``: importing a module never touches sys.path."""
    for path in sorted((ROOT / "pixelhq").glob("*.py")) + [ROOT / "dashboard" / "plugin_api.py", ROOT / "__init__.py"]:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            if re.search(r"sys\.path\.(insert|append)", line):
                assert lines[number - 1].startswith('if __name__ == "__main__"'), f"{path.name}:{number + 1}"


def test_manifest_version_and_loaded_version_agree_on_disk():
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    assert re.search(r"^version: 1\.2\.0$", manifest, re.M)
    assert "provides_middleware" not in manifest
    assert config.disk_version() == config.LOADED_VERSION == "1.2.0"


def test_disk_version_is_read_on_every_call_and_loaded_version_is_not(tmp_path, monkeypatch):
    (tmp_path / "pixelhq").mkdir()
    manifest = tmp_path / "plugin.yaml"
    manifest.write_text('name: sample\nversion: "2.0.1"  # note\n', encoding="utf-8")
    monkeypatch.setattr(config, "HERE", tmp_path / "pixelhq")
    monkeypatch.setattr(config, "LOADED_VERSION", config.disk_version())
    roster = {"rooms": [], "bots": []}
    assert config.public(config.DEFAULTS, roster)["version"] == "2.0.1"
    manifest.write_text("name: sample\nversion: 2.1.0\n", encoding="utf-8")
    shown = config.public(config.DEFAULTS, roster)
    assert (shown["version"], shown["diskVersion"]) == ("2.0.1", "2.1.0")
    manifest.unlink()
    assert config.public(config.DEFAULTS, roster)["diskVersion"] == ""


NOTICE = ("Pixel HQ {disk} is installed but {loaded} is still running — restart the Hermes gateway "
          "(`hermes gateway restart`) to finish the update.")


@pytest.mark.parametrize("version, disk, shown", [
    ("1.2.0", "1.3.0", True), ("1.3.0", "1.2.0", True), ("1.2.0", "1.2.0", False),
    ("1.2.0", "", False), ("", "1.2.0", False), (None, None, False), (None, "1.2.0", False)])
def test_footer_shows_the_stale_backend_notice_iff_the_versions_differ(tmp_path, version, disk, shown):
    script = re.search(r"<script>(.*?)</script>", page_html(), re.S).group(1)
    prelude = (Path(__file__).parent / "ui_dom.cjs").read_text(encoding="utf-8")
    probe = f"""
DATA.cfg.version = {json.dumps(version)}; DATA.cfg.diskVersion = {json.dumps(disk)};
if (DATA.cfg.version === null) delete DATA.cfg.version;
if (DATA.cfg.diskVersion === null) delete DATA.cfg.diskVersion;
hud();
const footer = elements.get('foot').textContent;
const notice = {json.dumps(NOTICE.format(disk=disk, loaded=version))};
assert.equal(footer.includes('is installed but'), {json.dumps(shown)});
if ({json.dumps(shown)}) assert.ok(footer.startsWith(notice), footer.slice(0, 200));
assert.ok(footer.includes('XP: pass'));
console.log('stale notice probe: ok');
"""
    path = tmp_path / "stale-ui.js"
    path.write_text(prelude + script + "\nDATA = " + json.dumps(demo_snapshot()) + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stale notice probe: ok" in result.stdout


def run_page_probe(tmp_path, probe, marker):
    script = re.search(r"<script>(.*?)</script>", page_html(), re.S).group(1)
    prelude = (Path(__file__).parent / "ui_dom.cjs").read_text(encoding="utf-8")
    path = tmp_path / "stale-ui.js"
    path.write_text(prelude + script + "\nDATA = " + json.dumps(demo_snapshot()) + ";\n" + probe, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout


@pytest.mark.parametrize("version, disk, shown", [
    ("1.2.0", "1.3.0", True), ("1.3.0", "1.2.0", True), ("1.2.0", "1.2.0", False),
    ("1.2.0", "", False), ("", "1.2.0", False), (None, None, False), (None, "1.2.0", False)])
def test_banner_is_shown_iff_the_versions_differ_and_the_footer_line_stays(tmp_path, version, disk, shown):
    run_page_probe(tmp_path, f"""
DATA.cfg.version = {json.dumps(version)}; DATA.cfg.diskVersion = {json.dumps(disk)};
if (DATA.cfg.version === null) delete DATA.cfg.version;
if (DATA.cfg.diskVersion === null) delete DATA.cfg.diskVersion;
hud();
const banner = elements.get('stale-banner'), text = elements.get('stale-text').textContent;
const notice = {json.dumps(NOTICE.format(disk=disk, loaded=version))};
assert.equal(banner.style.display, {json.dumps("" if shown else "none")});
assert.equal(text, {json.dumps(NOTICE.format(disk=disk, loaded=version) if shown else "")});
assert.equal(elements.get('foot').textContent.startsWith(notice + ' · '), {json.dumps(shown)});
console.log('banner probe: ok');
""", "banner probe: ok")


def test_dismiss_hides_the_banner_for_the_page_load_only_the_footer_line_stays(tmp_path):
    run_page_probe(tmp_path, f"""
DATA.cfg.version = '1.2.0'; DATA.cfg.diskVersion = '1.3.0';
hud();
const banner = elements.get('stale-banner');
assert.equal(banner.style.display, '');
const dismiss = document.getElementById('stale-dismiss');
assert.equal(typeof dismiss.onclick, 'function');
dismiss.onclick();
assert.equal(banner.style.display, 'none');
// later renders, a new snapshot message and the live data do not bring it back
hud(); renderAll();
assert.equal(banner.style.display, 'none');
listeners.get('message')({{source: window.parent, data: {{pixelhq: JSON.parse(JSON.stringify(DATA))}}}});
assert.equal(banner.style.display, 'none');
assert.ok(elements.get('foot').textContent.startsWith({json.dumps(NOTICE.format(disk="1.3.0", loaded="1.2.0") + " · ")}));
console.log('dismiss probe: ok');
""", "dismiss probe: ok")


def test_banner_comes_back_on_a_new_page_load_and_goes_away_when_the_versions_agree(tmp_path):
    run_page_probe(tmp_path, """
DATA.cfg.version = '1.2.0'; DATA.cfg.diskVersion = '1.3.0';
hud();
const banner = elements.get('stale-banner');
assert.equal(banner.style.display, '');
DATA.cfg.diskVersion = '1.2.0';
hud();
assert.equal(banner.style.display, 'none', 'shown iff the versions differ, also on a later snapshot');
DATA.cfg.diskVersion = '1.4.0';
hud();
assert.equal(banner.style.display, '');
assert.ok(elements.get('stale-text').textContent.includes('1.4.0 is installed but 1.2.0 is still running'));
console.log('banner update probe: ok');
""", "banner update probe: ok")


def test_banner_markup_is_static_and_sandbox_safe():
    html = (ROOT / "pixelhq" / "ui" / "index.html").read_text(encoding="utf-8")
    banner = re.search(r'<div class="banner" id="stale-banner".*?</div>', html).group(0)
    assert 'id="stale-text"' in banner and 'id="stale-dismiss"' in banner and ">Dismiss<" in banner
    assert 'type="button"' in banner and "<form" not in banner
    assert html.index('id="stale-banner"') < html.index('<header class="hdr">'), "the banner is at the top of the page"


def test_restart_hint_names_the_gateway_not_the_desktop_app():
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    hint = re.search(r"const restartHint = .*?\n  : t\n", source, re.S).group(0)
    assert "restart the Hermes gateway (`hermes gateway restart`)" in hint
    assert "desktop app" not in hint
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "After updating Pixel HQ, restart the Hermes gateway (`hermes gateway restart`)" in readme
