"""Update notice (R4-04, spec round-4 §5): header button, info panel, footer line, 6-h cadence.

The page script runs in the plain-Node DOM harness (`tests/ui_dom.cjs`) with a fake clock (`hostClock.now`) and the host simulated:
`messages` collects what the frame posts, `send(...)` plays a message from the parent. Nothing talks to a gateway or the network;
all versions and hashes are invented.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from pixelhq import page
from pixelhq.demo import snapshot

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3600 * 1000

PRE = r"""
let now = 1000000; hostClock.now = () => now;
const send = (data) => listeners.get('message')({source: window.parent, data});
const asks = () => messages.filter((m) => m.pixelhqUpdateInfo).map((m) => m.pixelhqUpdateInfo);
const el = (id) => document.getElementById('update-' + id);
const foot = () => document.getElementById('update-foot').textContent;
const SHA1 = 'a'.repeat(40), SHA2 = 'b'.repeat(40);
const result = (over = {}) => ({rid: asks().at(-1).rid, state: 'available', installed: {version: '1.2.0', sha: SHA1},
  available: {version: '1.3.0', sha: SHA2}, canNavigate: false, ...over});
const answer = (over) => send({pixelhqUpdateInfoResult: result(over)});
const load = () => { send({pixelhq: DATA}); };
const shown = (id) => el(id).style.display === '';
const hidden = (id) => el(id).style.display === 'none';
"""


def run_ui(tmp_path, probe, *, iframe=True, search=""):
    script = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8") + page.bundle_js()
    script += "\nDATA = " + json.dumps(snapshot()) + ";\n" + PRE + probe + "\nconsole.log('update ui: ok');\n"
    path = tmp_path / "update-ui.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ACTIONS": search, "IFRAME": "1" if iframe else "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# ---------------------------------------------------------------- static markup


def test_markup_has_a_keyboard_reachable_button_a_hidden_panel_and_a_footer_line():
    html = (ROOT / "pixelhq/ui/index.html").read_text(encoding="utf-8")
    button = re.search(r'<button[^>]*id="update-btn"[^>]*>(.*?)</button>', html)
    assert button and button.group(1) == "Update available"
    assert 'type="button"' in button.group(0) and 'display:none' in button.group(0) and 'tabindex="-1"' not in button.group(0)
    assert 'aria-expanded="false"' in button.group(0) and 'aria-controls="update-panel"' in button.group(0)
    panel = re.search(r'<div class="upd" id="update-panel"[^>]*>', html).group(0)
    assert "display:none" in panel and 'tabindex="-1"' in panel
    for part in ("Update in Hermes (Capabilities → Plugins) or run <code>hermes plugins update pixel-hq</code>", "Then restart the gateway"):
        assert part in html
    for name in ("update-open", "update-close"):
        tag = re.search(r'<button[^>]*id="%s"[^>]*>' % name, html).group(0)
        assert 'type="button"' in tag and 'tabindex="-1"' not in tag
    assert 'id="update-open" style="display:none"' in html, "Open Plugins is hidden until the bridge reports navigate"
    assert 'id="update-foot"' in html and "<form" not in html


# ---------------------------------------------------------------- asking: load, cadence, standalone


def test_the_page_asks_once_at_load_with_a_request_id_and_nothing_else(tmp_path):
    run_ui(tmp_path, r"""
assert.equal(asks().length, 0, 'nothing before the first snapshot');
load(); load(); send({pixelhqTheme: {mode: 'light'}}); renderAll();
assert.equal(asks().length, 1);
const req = asks()[0];
assert.match(req.rid, /^[0-9a-f]{16,32}$/);
assert.deepEqual(Object.keys(req), ['rid']);
""")


def test_cadence_is_at_most_one_question_per_six_hours_on_a_fake_clock(tmp_path):
    run_ui(tmp_path, r"""
load();
assert.equal(asks().length, 1);
answer({state: 'current', available: {version: '1.2.0', sha: SHA1}});
now += 6 * 3600 * 1000 - 1; load(); renderAll();
assert.equal(asks().length, 1, 'one millisecond short of six hours');
now += 1; load();
assert.equal(asks().length, 2, 'exactly six hours later');
assert.notEqual(asks()[1].rid, asks()[0].rid);
answer({state: 'current'});
for (let i = 0; i < 30; i++) { now += 10 * 60 * 1000; load(); }
assert.equal(asks().length, 2, 'a further 5 h of snapshots ask nothing');
now += 2 * 3600 * 1000; load();
assert.equal(asks().length, 3);
""")


def test_no_second_question_while_one_is_open_and_a_clock_that_moved_back_asks_again(tmp_path):
    run_ui(tmp_path, r"""
load();
now += 7 * 3600 * 1000; load(); load();
assert.equal(asks().length, 1, 'the first question is still open');
answer({state: 'current'});
now -= 30 * 3600 * 1000; load();
assert.equal(asks().length, 2, 'a clock that moved back does not block asking forever');
""")


def test_standalone_page_asks_nothing_and_shows_nothing(tmp_path):
    run_ui(tmp_path, r"""
load(); renderAll(); now += 8 * 3600 * 1000; renderAll();
assert.equal(asks().length, 0);
assert.equal(messages.filter((m) => m.pixelhqOpenPlugins).length, 0);
// even an answer that nobody asked for changes nothing
send({pixelhqUpdateInfoResult: {rid: '0'.repeat(24), state: 'available', installed: {version: '1.0.0'}, available: {version: '2.0.0'}}});
assert.ok(!shown('btn'), 'no button');
assert.equal(foot(), '');
""", iframe=False)
    run_ui(tmp_path, r"""
load(); renderAll();
assert.equal(asks().length, 0, 'the ?actions=1 demo mode has no host either');
assert.equal(foot(), '');
""", iframe=False, search="?actions=1")


# ---------------------------------------------------------------- the button and the panel


def test_available_shows_the_button_and_the_panel_with_both_versions(tmp_path):
    run_ui(tmp_path, r"""
load();
assert.ok(!shown('btn'), 'no button before the answer');
answer();
assert.ok(shown('btn'));
assert.equal(el('btn').attrs['aria-expanded'], undefined);
assert.equal(foot(), '', 'the button is the notice; the footer stays empty');
assert.notEqual(el('panel').style.display, '', 'the panel is closed until the button is used');
el('btn').onclick();
assert.ok(shown('panel'));
assert.equal(el('btn').attrs['aria-expanded'], 'true');
assert.equal(document.activeElement, el('panel'), 'focus moves into the panel');
assert.equal(el('installed').textContent, '1.2.0 (aaaaaaa)');
assert.equal(el('latest').textContent, '1.3.0 (bbbbbbb)');
el('btn').onclick();
assert.ok(hidden('panel'));
assert.equal(el('btn').attrs['aria-expanded'], 'false');
assert.equal(document.activeElement, el('btn'), 'focus goes back to the button');
""")


def test_versions_without_sha_or_without_anything_are_shown_plainly(tmp_path):
    run_ui(tmp_path, r"""
load();
answer({installed: {version: '1.2.0', sha: null}, available: {version: null, sha: SHA2}});
assert.equal(el('installed').textContent, '1.2.0');
assert.equal(el('latest').textContent, '(bbbbbbb)');
now += 7 * 3600 * 1000; load();
answer({installed: {version: null, sha: null}, available: undefined});
assert.equal(el('installed').textContent, '–');
assert.equal(el('latest').textContent, '–');
assert.ok(shown('btn'), 'an update without versions is still reported');
""")


def test_open_plugins_only_when_the_bridge_says_navigate_exists(tmp_path):
    run_ui(tmp_path, r"""
load();
answer({canNavigate: false});
el('btn').onclick();
assert.ok(hidden('open'), 'no Open Plugins without host.navigate');
now += 7 * 3600 * 1000; load();
answer({canNavigate: true});
assert.ok(shown('open'));
for (const odd of ['true', 1, {}, null, undefined]) {
  now += 7 * 3600 * 1000; load();
  answer({canNavigate: odd});
  assert.ok(hidden('open'), 'only the boolean true counts: ' + JSON.stringify(odd));
}
now += 7 * 3600 * 1000; load();
answer({canNavigate: true});
assert.equal(messages.filter((m) => m.pixelhqOpenPlugins).length, 0, 'nothing is opened by itself');
el('open').onclick();
const opens = messages.filter((m) => m.pixelhqOpenPlugins);
assert.equal(opens.length, 1);
assert.deepEqual(opens[0], {pixelhqOpenPlugins: true}, 'the frame never names a route');
assert.ok(hidden('panel'), 'the panel closes');
""")


def test_escape_closes_the_panel_and_only_then(tmp_path):
    run_ui(tmp_path, r"""
load(); answer();
const other = new Element('button'); other.focus();
pointer.key('Escape');
assert.equal(document.activeElement, other, 'Esc with a closed panel touches nothing');
el('btn').onclick();
pointer.key('Enter');
assert.ok(shown('panel'), 'other keys do nothing');
pointer.key('Escape');
assert.ok(hidden('panel'));
assert.equal(el('btn').attrs['aria-expanded'], 'false');
assert.equal(document.activeElement, el('btn'));
el('btn').onclick(); el('close').onclick();
assert.ok(hidden('panel'), 'Close works too');
""")


def test_the_panel_closes_and_the_button_goes_when_the_update_is_gone(tmp_path):
    run_ui(tmp_path, r"""
load(); answer(); el('btn').onclick();
assert.ok(shown('panel'));
now += 7 * 3600 * 1000; load();
answer({state: 'current', available: {version: '1.3.0', sha: SHA2}});
assert.ok(hidden('btn') && hidden('panel'));
assert.equal(foot(), 'Update check: up to date (catalog 1.3.0)');
""")


def test_a_refresh_does_not_touch_an_open_panel(tmp_path):
    run_ui(tmp_path, r"""
load(); answer(); el('btn').onclick();
const panel = el('panel'), installed = el('installed');
load(); renderAll(); send({pixelhqTheme: {mode: 'dark'}});
assert.equal(document.activeElement, panel, 'snapshots and theme changes keep the focus');
assert.ok(shown('panel'));
now += 7 * 3600 * 1000; load();
answer({available: {version: '1.4.0', sha: SHA2}});
assert.equal(document.activeElement, panel, 'a new answer updates the text in place');
assert.equal(el('latest').textContent, '1.4.0 (bbbbbbb)');
assert.equal(installed.children.length + el('latest').children.length, 0);
""")


# ---------------------------------------------------------------- the footer line in every other state


def test_footer_line_for_every_state_except_available(tmp_path):
    run_ui(tmp_path, r"""
const cases = [
  [{state: 'current', available: {version: '1.3.0', sha: SHA2}}, 'Update check: up to date (catalog 1.3.0)'],
  [{state: 'current', available: undefined}, 'Update check: up to date'],
  [{state: 'unavailable', message: 'Update check is not available for this installation'},
    'Update check: not available for this installation'],
  [{state: 'unsupported', message: 'x'}, 'Update check: not available (this Hermes version cannot list plugins)'],
  [{state: 'error', message: 'gateway offline'}, 'Update check: failed (gateway offline)'],
  [{state: 'something-else', message: 'odd'}, 'Update check: failed (odd)'],
  [{state: 'error'}, 'Update check: failed ()'],
];
load(); assert.equal(foot(), '', 'quiet until the first answer');
for (const [over, text] of cases) {
  answer(over);
  assert.equal(foot(), text);
  assert.ok(!shown('btn'), 'no button in ' + over.state);
  now += 7 * 3600 * 1000; load();
}
""")


def test_errors_are_a_footer_line_only_and_a_known_update_survives_a_failed_recheck(tmp_path):
    run_ui(tmp_path, r"""
load(); answer(); assert.ok(shown('btn'));
now += 7 * 3600 * 1000; load();
answer({state: 'error', message: 'gateway offline'});
assert.ok(shown('btn'), 'a failed re-check does not hide an update that is known');
assert.equal(foot(), '');
now += 7 * 3600 * 1000; load();
timers.length = 0;
now += 25000; load();
timers.splice(0).forEach((fn) => fn());
assert.ok(shown('btn'), 'nor does a timeout');
assert.equal(foot(), '');
""")


def test_timeout_shows_a_footer_line_and_a_late_answer_replaces_it(tmp_path):
    run_ui(tmp_path, r"""
load();
assert.equal(foot(), '');
now += 20000; timers.splice(0).forEach((fn) => fn());
assert.equal(foot(), 'Update check: failed (no answer from the host (timeout))');
assert.ok(!shown('btn'));
answer({state: 'available'});
assert.ok(shown('btn'), 'the late answer is used');
assert.equal(foot(), '');
answer({state: 'current'});
assert.ok(shown('btn'), 'an answer is taken once; a repeat is dropped');
""")


def test_unknown_and_stale_answers_are_dropped(tmp_path):
    run_ui(tmp_path, r"""
send({pixelhqUpdateInfoResult: {rid: 'f'.repeat(24), state: 'available'}});
assert.ok(!shown('btn'), 'no question was asked yet');
load();
send({pixelhqUpdateInfoResult: {rid: 'f'.repeat(24), state: 'available'}});
assert.ok(!shown('btn'), 'wrong request id');
for (const junk of [null, 'text', 5, [], {}, {rid: 7}, {state: 'available'}]) send({pixelhqUpdateInfoResult: junk});
assert.ok(!shown('btn'));
assert.equal(foot(), '');
answer({state: 'current'});
assert.equal(foot(), 'Update check: up to date (catalog 1.3.0)');
""")


# ---------------------------------------------------------------- escaping


def test_hostile_values_stay_text_and_never_become_markup(tmp_path):
    run_ui(tmp_path, r"""
load();
const evil = '<img src=x onerror=alert(1)>';
answer({installed: {version: evil, sha: evil}, available: {version: '1.3.0"><b>', sha: SHA2 + '<'}});
assert.ok(shown('btn'));
for (const id of ['installed', 'latest']) {
  assert.ok(!el(id).textContent.includes('<'), id + ': ' + el(id).textContent);
  assert.equal(el(id).children.length, 0);
}
assert.equal(el('installed').textContent, '–');
assert.equal(el('latest').textContent, '–');
""")
    run_ui(tmp_path, r"""
load();
const text = '<b>boom</b>' + 'z'.repeat(300);
answer({state: 'error', message: text});
const line = foot();
assert.ok(line.startsWith('Update check: failed (<b>boom</b>z'), 'shown as literal text');
assert.equal(line, 'Update check: failed (' + text.slice(0, 120) + ')', 'clipped to 120 characters');
assert.equal(document.getElementById('update-foot').children.length, 0, 'the footer holds text, not elements');
""")
