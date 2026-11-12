"""Round 3 fix R3-F2: the unsaved-layout bar keeps one footprint in all states, the desk select shows its label.

The plain-Node DOM harness has no layout engine, so these tests check the markup contract that the fixed height relies on
(one `.layout-bar` element per place, the same class in every state, the clean line, removal on leaving edit mode) and the
stylesheet rules (fixed height, no wrapping, the select rule that beat the font size). The pixels are verified by hand in
a browser. Invented names only.
"""
import re
from pathlib import Path

from tests.test_floor_edit import run_floor

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "pixelhq" / "ui" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "pixelhq" / "ui" / "index.html").read_text(encoding="utf-8")

STATES = """
const bars = [officeBar, rosterBar];
const kind = bar => q('[data-layout-save]', bar) ? (bar.innerHTML.includes('Saving roster') ? 'busy' : 'dirty')
  : bar.innerHTML.includes('layout-clean') ? 'clean' : bar.innerHTML.includes('layout-result') ? 'result' : 'empty';
const seen = [];
const check = (want) => {
  for (const bar of bars) {
    assert.ok(bar.classList.contains('layout-bar'), 'the bar element keeps the fixed-height class');
    assert.ok(bar.innerHTML !== '', 'the bar is not empty in ' + want);
    seen.push(kind(bar));
  }
  assert.equal(kind(officeBar), want, officeBar.innerHTML); assert.equal(kind(rosterBar), want, rosterBar.innerHTML);
};
"""


def test_both_bars_keep_the_same_element_and_class_in_clean_dirty_busy_and_result_states(tmp_path):
    run_floor(tmp_path, STATES + """
assert.equal(officeBar.innerHTML, '', 'outside edit mode the floor shows no bar');
assert.ok(rosterBar.innerHTML.includes('No unsaved changes'), 'the Roster tab always has its bar');
toggle();
check('clean');
assert.ok(officeBar.innerHTML.includes('No unsaved changes') && rosterBar.innerHTML.includes('No unsaved changes'));
assert.ok(officeBar.innerHTML.includes('class="layout-clean"'));
dragTo('sysadmin', free('lab'));
check('dirty');
saveFromBar();
check('busy');
send({pixelhqRosterResult: {ok: false, message: 'Roster refused: sample reason.'}});
assert.ok(officeBar.innerHTML.includes('layout-result bad')); assert.ok(rosterBar.innerHTML.includes('layout-result bad'));
for (const bar of bars) { assert.ok(bar.classList.contains('layout-bar')); assert.ok(bar.innerHTML !== ''); }
dragTo('sysadmin', free('ops'));
check('clean');
dragTo('sysadmin', free('lab'));
q('[data-layout-save]', officeBar).onclick();
send({pixelhqRosterResult: {ok: true, message: 'Roster saved.'}});
for (const bar of bars) {
  assert.ok(bar.classList.contains('layout-bar')); assert.ok(bar.innerHTML.includes('layout-result ok'));
  assert.ok(!bar.innerHTML.includes('Unsaved') && !bar.innerHTML.includes('No unsaved changes'), 'one line: the result');
}
assert.deepEqual([...new Set(seen)].sort(), ['busy', 'clean', 'dirty']);
// the elements themselves are never replaced: one bar per place for the whole session
assert.equal(document.getElementById('office-bar'), officeBar); assert.equal(document.getElementById('roster-bar'), rosterBar);
""")


def test_the_roster_tab_bar_is_there_from_the_start_and_through_the_first_keystroke(tmp_path):
    run_floor(tmp_path, """
const bar = rosterBar;
tab('roster');
const root = document.getElementById('roster-editor');
assert.ok(bar.classList.contains('layout-bar'));
assert.ok(bar.innerHTML.includes('class="layout-clean"') && bar.innerHTML.includes('No unsaved changes'));
const title = q('[data-roster-field="title"]', root.querySelectorAll('[data-roster-bot]')[0]);
title.focus(); title.value = title.value + 'X'; title.oninput();
assert.ok(bar.classList.contains('layout-bar') && bar.innerHTML.includes('Unsaved layout changes'));
assert.equal(document.activeElement, title, 'the focused field was not re-rendered');
title.value = title.value.slice(0, -1); title.oninput();
assert.ok(bar.classList.contains('layout-bar') && bar.innerHTML.includes('No unsaved changes'));
assert.equal(document.activeElement, title);
""")


def test_leaving_edit_mode_removes_the_clean_floor_bar_and_keeps_a_pending_one(tmp_path):
    run_floor(tmp_path, """
toggle();
assert.ok(officeBar.innerHTML.includes('No unsaved changes'));
toggle();
assert.equal(officeBar.innerHTML, '', 'leaving edit mode removes the clean floor bar');
assert.ok(rosterBar.innerHTML.includes('No unsaved changes'), 'the Roster tab keeps its bar');
toggle(); dragTo('sysadmin', free('lab')); toggle();
assert.ok(officeBar.innerHTML.includes('Unsaved layout changes'), 'unsaved changes stay visible (round-3 section 3)');
toggle();
assert.ok(q('[data-layout-save]', officeBar));
""")


def test_the_standalone_page_without_actions_has_no_bars(tmp_path):
    run_floor(tmp_path, """
toggle();
assert.equal(officeBar.innerHTML, ''); assert.equal(rosterBar.innerHTML, '');
""", iframe=False, actions="")


def rule(selector):
    found = re.findall(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS, flags=re.M)
    assert found, selector
    return ";".join(found)


def test_the_bar_has_one_fixed_height_and_cannot_wrap_or_grow():
    body = rule(".layout-bar")
    assert re.search(r"(?<![-\w])height:\s*\d+px", body)
    assert "flex-wrap:nowrap" in body and "overflow:hidden" in body and "flex-wrap:wrap" not in body
    assert not re.search(r"min-height|max-height|padding:\s*[1-9]\d*px\s+\d", body)
    assert 'class="layout-bar" id="office-bar"' in INDEX and 'class="layout-bar" id="roster-bar"' in INDEX
    assert re.search(r"\.layout-bar:empty\s*\{display:none\}", CSS)
    assert "color:var(--mut2)" in rule(".layout-clean")


def test_the_desk_select_rule_is_not_overridden_by_the_floor_wide_font_rule():
    # `#floor select{font:inherit}` (specificity 1,0,1) beat `.desk select{font-size:9px}` and the label was cut off.
    wide = rule("#floor input,#floor select")
    assert "font:inherit" in wide
    desk = rule("#floor .desk select")
    assert re.search(r"font-size:\s*9px", desk) and "width:100%" in desk
    assert ".desk select{" not in CSS.replace("#floor .desk select{", "")
    # 8 characters at 9px in a 0.6 em monospace face need about 44 px; the desk is 92 px wide with the select at 100 %
    assert re.search(r"\.desk\{width:92px", CSS)
