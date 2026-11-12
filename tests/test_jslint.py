"""R3-01: the UI source is split into ordered files under pixelhq/ui/js/ and checked by tools/jslint.py."""
import re
import subprocess
import sys
from pathlib import Path

from pixelhq import page
from tests.test_review_ui import run_ui

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "pixelhq" / "ui" / "js"

# Top-level `function` declarations and top-level `const name = (...) =>` helpers of the single-file pixelhq/ui/app.js,
# taken from `git show HEAD:pixelhq/ui/app.js` before the split (HEAD = the Round 3 spec commit).
# R3-02 replaced three roster functions (rosterZonesHtml, rosterAddsHtml, bindRosterZones) by the rooms-and-departments editor
# in 72-roster-groups.js (rosterGroupsHtml, bindRosterGroups, ...); they are no longer in this list.
OLD_FUNCTIONS = (
    "appearanceMode applyAppearance submitToHost liveOf shortStep liveStatus spriteVariant sprite bubble ago clock hm "
    "bars evk logHtml hostTrips disarm armedButton scheduleFlush flushDeferred renderDirect renderUnlessFocused "
    "roundTrip fillRandom newRid reviewBody reviewHtml refreshReview bindReview bindReviews onReviewResult jumpBody "
    "jumpHtml chatHtml refreshJump bindJump bindJumps onJumpResult detail showDetail select roomsHtml renderBanner "
    "office tps reactorHtml zoneFilters board hud rosterFromSnapshot rosterInput rosterSelect rosterBotHtml "
    "rosterChanged bindRosterRows rosterProblem rosterTextTest rosterTextMessage "
    "rosterTextProblem addRosterBot addRosterZone bindRosterAdds submitRoster onRosterResult "
    "bindRosterSubmit renderRoster drawRoster tab pushRes actionsHtml bindActions onActionResult blk blockList "
    "sessHtml taskHtml liveTab liveActive liveRender renderAll setStand"
).split()
OLD_ARROWS = (
    "CFG staleNotice validMode palette esc safeColor quarantineZones fmtN fmt1 hpTxt isField holdsField relatedBox "
    "renderRunning cancelDeferred reviewKey refreshReviewRows jumpKey refreshJumpRows rosterBusy rosterResult "
    "rosterPick rosterClone validBotId validGroupId renderRosterPeriodic triageBusy knownActions triageLabel dur kt"
).split()


def test_the_single_file_is_replaced_by_ordered_numbered_files():
    assert not (ROOT / "pixelhq" / "ui" / "app.js").exists()
    names = [p.name for p in sorted(JS_DIR.iterdir())]
    assert names, "no UI script files"
    assert all(re.fullmatch(r"\d\d-[a-z0-9]+(?:-[a-z0-9]+)*\.js", name) for name in names), names
    assert names == sorted(names)
    assert len({name[:2] for name in names}) == len(names), "every numeric prefix is used once"
    assert names[0].startswith("00-") and names[-1].startswith("90-")


def test_the_bundle_is_the_files_joined_in_file_name_order_with_one_data_slot():
    files = sorted(JS_DIR.glob("*.js"), key=lambda p: p.name)
    texts = [p.read_text(encoding="utf-8") for p in files]
    assert page.bundle_js() == "\n".join(texts)
    assert all(text.endswith("\n") and not text.startswith("\n") for text in texts)
    assert page.bundle_js().count("/*PIXELHQ_DATA*/null") == 1
    assert page.bundle_js() in page.page_html()


def test_the_bundle_defines_every_top_level_function_of_the_old_app_js():
    bundle = page.bundle_js()
    missing = [name for name in OLD_FUNCTIONS if not re.search(rf"^function {name}\(", bundle, re.M)]
    missing += [name for name in OLD_ARROWS if not re.search(rf"^const {name} = ", bundle, re.M)]
    assert missing == []
    assert len(OLD_FUNCTIONS) == 84 - 3 and len(OLD_ARROWS) == 31  # 84 before R3-02 replaced three


def test_the_bundle_defines_those_names_at_run_time(tmp_path):
    names = OLD_FUNCTIONS + OLD_ARROWS
    probe = "for (const name of %s) assert.equal(eval('typeof ' + name), 'function', name);" % names
    assert "ui review behavior: ok" in run_ui(tmp_path, probe)


def run_jslint(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "jslint.py"), *args], capture_output=True, text=True,
                          timeout=60)


def make_tree(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def body(lines):
    return "".join(f"  step({n});\n" for n in range(lines))


def test_repository_sources_pass_the_gate():
    result = run_jslint()
    assert result.returncode == 0, result.stdout + result.stderr
    summary = result.stdout.strip().splitlines()[-1]
    assert re.fullmatch(r"jslint: ok: \d+ files, longest line \d+ \(\S+:\d+\), longest function \d+ lines \(\S+:\d+ \S+\)",
                        summary), summary
    count = int(re.search(r": (\d+) files", summary).group(1))
    assert count == len(list(JS_DIR.glob("*.js"))) + 1, "every ui/js file and desktop/plugin.js"


def test_a_long_line_is_reported_with_file_and_line_unless_it_ends_with_the_table_mark(tmp_path):
    long_row = "const ROW = ['" + "x" * 150 + "']"
    root = make_tree(tmp_path, {
        "pixelhq/ui/js/00-a.js": "const ok = 1;\n" + long_row + ";\n",
        "pixelhq/ui/js/10-b.js": long_row + "; /* table */\n",
        "pixelhq/ui/js/20-c.js": "const edge = '" + "y" * 124 + "';\n",
    })
    assert len(long_row) + 1 > 140 and len("const edge = '" + "y" * 124 + "';") == 140
    result = run_jslint(str(root))
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines[0].startswith("pixelhq/ui/js/00-a.js:2: line has ")
    assert not any("10-b.js" in line or "20-c.js" in line for line in lines[:-1])
    assert "jslint: FAILED" in lines[-1]


def test_the_table_mark_must_end_the_line(tmp_path):
    long_row = "const ROW = ['" + "x" * 150 + "'];"
    root = make_tree(tmp_path, {"pixelhq/ui/js/00-a.js": long_row + " /* table */ // note\n"})
    assert run_jslint(str(root)).returncode == 1


def test_a_function_over_80_lines_is_reported_at_its_first_line(tmp_path):
    over, edge = body(79), body(78)  # head + body + closing brace = 81 and 80 lines
    root = make_tree(tmp_path, {
        "pixelhq/ui/js/00-a.js": "const x = 1;\nfunction tooLong() {\n" + over + "}\n",
        "pixelhq/ui/js/10-b.js": "function atLimit() {\n" + edge + "}\n",
        "pixelhq/ui/js/20-c.js": "const run = async (a) => {\n" + over + "};\n",
        "pixelhq/ui/js/30-d.js": "const obj = {\n  method(a, b) {\n" + over + "  },\n};\n",
        "pixelhq/ui/js/40-e.js": "list.forEach(function (item) {\n" + over + "});\n",
        "desktop/plugin.js": "export default {\n  register(ctx) {\n" + over + "  }\n}\n",
    })
    result = run_jslint(str(root))
    assert result.returncode == 1
    problems = result.stdout.splitlines()[:-1]
    assert [p.split(": ")[0] for p in problems] == [
        "pixelhq/ui/js/00-a.js:2", "pixelhq/ui/js/20-c.js:1", "pixelhq/ui/js/30-d.js:2", "pixelhq/ui/js/40-e.js:1",
        "desktop/plugin.js:2"]
    assert "function tooLong has 81 lines" in problems[0] and "10-b" not in result.stdout


def test_nested_functions_count_on_their_own_and_blocks_are_not_functions(tmp_path):
    inner = "function inner() {\n" + body(80) + "}\n"
    root = make_tree(tmp_path, {
        "pixelhq/ui/js/00-a.js": "function outer() {\n" + inner + "}\n"
                                 "if (a) {\n" + body(100) + "}\nfor (const x of y) {\n" + body(100) + "}\n",
    })
    result = run_jslint(str(root))
    problems = result.stdout.splitlines()[:-1]
    assert [p.split(": ")[0] for p in problems] == ["pixelhq/ui/js/00-a.js:1", "pixelhq/ui/js/00-a.js:2"]


def test_braces_in_strings_templates_regexes_and_comments_do_not_confuse_the_scanner(tmp_path):
    tricky = (
        "function fine() {\n"
        "  const a = '}{ // not a comment';\n"
        '  const b = "}";\n'
        "  const c = `${ {x: 1}.x } } {`;\n"
        "  const d = /[}{/]+\\/}/g.test(a) ? 1 : 2 / 3;\n"
        "  // } closing brace in a comment\n"
        "  /* { opening brace in a comment */\n"
        "  return a + b + c + d;\n"
        "}\n"
    )
    root = make_tree(tmp_path, {"pixelhq/ui/js/00-a.js": tricky + "function after() {\n" + body(79) + "}\n"})
    result = run_jslint(str(root))
    assert result.returncode == 1
    assert [p.split(": ")[0] for p in result.stdout.splitlines()[:-1]] == ["pixelhq/ui/js/00-a.js:10"]
    assert "function after has 81 lines" in result.stdout
