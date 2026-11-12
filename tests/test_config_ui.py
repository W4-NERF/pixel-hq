"""Config section of the character card (R4-03): states, facts, SOUL editor, diff preview, save results, history and restore.

The page script runs in the plain-Node DOM harness (`tests/ui_dom.cjs`) with the host simulated: `messages` collects what the frame posts,
`send(...)` plays a message from the parent. Nothing talks to a gateway, a profile or the network; every name and text is invented.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from pixelhq import page
from pixelhq.demo import snapshot

ROOT = Path(__file__).resolve().parents[1]

PRE = r"""
const bot = DATA.bots[0];
sel = bot.id;
const root = () => elements.get('detail');
const cfg = () => root().querySelector('[data-cfg]');
const box = (name) => cfg().querySelector('[data-cfg-' + name + ']');
const send = (data) => listeners.get('message')({source: window.parent, data});
const sent = (key) => messages.filter((m) => m[key]).map((m) => m[key]);
const lastRid = (key) => sent(key).at(-1).rid;
const HASH = 'a'.repeat(64), HASH2 = 'b'.repeat(64);
const SOUL = 'Line one\nLine two\nLine three\n';
const profile = (over = {}) => ({name: bot.id, description: 'A sample profile', soul: SOUL, soulHash: HASH,
  model: {provider: 'sample-provider', default: 'sample-model'},
  skills: [{name: 'alpha', enabled: true}, {name: 'beta', enabled: false}],
  toolsets: [{name: 'files', enabled: true}, {name: 'web', enabled: false}], toolsets_pinned: true,
  mcp_servers: [{name: 'docs', transport: 'stdio', enabled: true}], ...over});
const toggle = () => cfg().querySelector('[data-cfg-toggle]').onclick();
const answer = (over, state = 'ready', extra = {}) =>
  send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state, data: profile(over), ...extra}});
const open = (over) => { detail(bot); toggle(); answer(over); };
const ITEMS = [
  {id: '20261110T080000Z-89abcdef.md', savedAt: '2026-11-10T08:00:00Z', bytes: 21, firstLine: 'Oldest soul'},
  {id: '20261112T010203Z-0123abcd.md', savedAt: '2026-11-12T01:02:03Z', bytes: 40, firstLine: 'Newest soul'}];
const answerHistory = (items = ITEMS, state = 'ready', message) =>
  send({pixelhqSoulHistoryResult: {rid: lastRid('pixelhqSoulHistory'), state, items, message}});
const slotTexts = (el) => el.querySelectorAll('[data-slot]').map((s) => s.textContent);
const kindOf = (r) => r.classList.contains('add') ? '+' : r.classList.contains('del') ? '-' : r.classList.contains('skip') ? '~' : ' ';
const rowKinds = () => box('soul').querySelectorAll('.dl').map(kindOf).join('');
const editor = () => box('soul').querySelector('[data-cfg-text]');
const press = (name) => box('soul').querySelector('[data-cfg-' + name + ']').onclick();
const startEditing = (text) => {
  press('edit');
  const ta = editor();
  if (text !== undefined) { ta.value = text; ta.oninput(); }
  return ta;
};
const confirmTwice = () => { press('confirm'); press('confirm'); };
const saved = (rid, over = {}) => send({pixelhqSoulSaveResult: {rid, state: 'saved', message: 'SOUL saved.', soulHash: HASH2, ...over}});
const state = () => confStates.get('local/' + bot.id);
const restoreBtn = (id) => box('history').querySelectorAll('[data-cfg-version]').find((r) => r.dataset.cfgVersion === id)
  .querySelector('[data-cfg-restore]');
"""


def run_ui(tmp_path, probe, *, iframe=True, data=None):
    script = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8") + page.bundle_js()
    script += "\nDATA = " + json.dumps(data if data is not None else snapshot()) + ";\n" + PRE + probe
    script += "\nconsole.log('config ui: ok');\n"
    path = tmp_path / "config-ui.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ACTIONS": "", "IFRAME": "1" if iframe else "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# ---------------------------------------------------------------- MUST 1: section, states, facts, reload


def test_section_is_collapsed_and_nothing_loads_until_it_is_opened(tmp_path):
    run_ui(tmp_path, r"""
detail(bot);
assert.ok(cfg(), 'the card has a Config section');
assert.equal(cfg().querySelector('[data-cfg-toggle]').attrs['aria-expanded'], 'false');
assert.ok(cfg().querySelector('[data-cfg-toggle]').innerHTML === '' && cfg().innerHTML.includes('CONFIG'));
assert.equal(box('status'), null);
assert.equal(box('soul'), null);
// periodic redraws of the card load nothing either
detail(bot); send({pixelhq: DATA}); send({pixelhqTheme: {mode: 'light'}});
const config = messages.filter((m) => Object.keys(m).some((k) => /^pixelhq(Profile|Soul)/.test(k)));
assert.equal(config.length, 0, JSON.stringify(config));
assert.equal(confStates.get('local/' + bot.id).load, 'idle');
""")


def test_opening_loads_once_shows_loading_then_the_read_only_facts(tmp_path):
    run_ui(tmp_path, r"""
detail(bot); toggle();
assert.equal(sent('pixelhqProfile').length, 1);
const req = sent('pixelhqProfile')[0];
assert.match(req.rid, /^[0-9a-f]{16,32}$/);
assert.deepEqual({bot: req.bot, remote: req.remote, keys: Object.keys(req).sort()}, {bot: bot.id, remote: false, keys: ['bot', 'remote', 'rid']});
assert.equal(cfg().querySelector('[data-cfg-toggle]').attrs['aria-expanded'], 'true');
assert.equal(box('status').dataset.state, 'loading');
assert.ok(box('status').innerHTML.includes('Loading configuration'));
assert.equal(box('facts').innerHTML, '');
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, true, 'no second request while one is open');
answer();
assert.equal(box('status').dataset.state, 'ready');
const facts = box('facts').innerHTML;
for (const part of ['sample-provider / sample-model', 'A sample profile', '1 of 2 enabled', 'disabled: beta', 'files', 'pinned: yes',
  'docs (stdio, enabled)', 'Change model, skills and toolsets in Hermes (Bot Mode → Edit)'])
  assert.ok(facts.includes(part), part + ' missing in ' + facts);
assert.ok(!facts.includes('web'), 'a disabled toolset is not listed');
// no edit of the facts: they are text, not fields
assert.equal(box('facts').querySelectorAll('input').length + box('facts').querySelectorAll('textarea').length, 0);
// loaded once: closing, opening and redrawing the card ask nothing more
toggle(); toggle(); detail(bot); send({pixelhq: DATA});
assert.equal(sent('pixelhqProfile').length, 1);
assert.ok(box('facts').innerHTML.includes('sample-provider / sample-model'));
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, false);
""")


def test_pinned_no_and_empty_lists_are_stated(tmp_path):
    run_ui(tmp_path, r"""
detail(bot); toggle();
answer({toolsets_pinned: false, skills: [], toolsets: [], mcp_servers: [], description: '', model: {}});
const facts = box('facts').innerHTML;
assert.ok(facts.includes('0 of 0 enabled') && facts.includes('pinned: no') && facts.includes('none'));
assert.ok(facts.includes('–'), 'missing model and description show a dash');
""")


@pytest.mark.parametrize("status, message, shown", [
    ("unreachable", None, "Not reachable from this Desktop"),
    ("ambiguous", None, "More than one Desktop connection offers this bot; nothing was called"),
    ("unsupported", None, "This Hermes version has no profile editor API"),
    ("error", None, "The profile could not be read"),
    ("unreachable", "Custom <b>text</b>", "Custom &lt;b&gt;text&lt;/b&gt;"),
])
def test_failure_states_show_a_message_and_offer_reload(tmp_path, status, message, shown):
    run_ui(tmp_path, r"""
detail(bot); toggle();
send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: STATUS, message: MESSAGE}});
assert.equal(box('status').dataset.state, STATUS);
assert.ok(box('status').innerHTML.includes(SHOWN), box('status').innerHTML);
assert.ok(!box('status').innerHTML.includes('<b>'));
assert.equal(box('facts').innerHTML, '');
assert.equal(box('soul').innerHTML, '');
assert.equal(box('history').innerHTML, '');
assert.equal(sent('pixelhqSoulHistory').length, 0, 'no history without a profile');
const reload = box('status').querySelector('[data-cfg-reload]');
assert.equal(reload.disabled, false);
reload.onclick();
assert.equal(sent('pixelhqProfile').length, 2, 'Reload asks again');
assert.equal(box('status').dataset.state, 'loading');
answer();
assert.equal(box('status').dataset.state, 'ready');
assert.ok(box('facts').innerHTML.includes('sample-provider'));
""".replace("STATUS", json.dumps(status)).replace("MESSAGE", json.dumps(message)).replace("SHOWN", json.dumps(shown)))


def test_error_message_is_clipped_to_200_characters_and_escaped(tmp_path):
    run_ui(tmp_path, r"""
detail(bot); toggle();
const text = '<b>x</b>' + 'y'.repeat(300);
send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: 'error', message: text}});
const html = box('status').innerHTML;
assert.ok(html.includes('&lt;b&gt;x&lt;/b&gt;' + 'y'.repeat(192) + '<'), 'exactly 200 characters of the message');
assert.ok(!html.includes('y'.repeat(193)));
assert.ok(!html.includes('<b>'));
assert.ok(html.includes('res bad'));
""")


def test_long_lists_collapse_after_twelve_entries_with_a_more_button(tmp_path):
    run_ui(tmp_path, r"""
detail(bot); toggle();
const names = Array.from({length: 15}, (_, i) => 'tool' + String(i + 1).padStart(2, '0'));
answer({toolsets: names.map((name) => ({name, enabled: true})),
  mcp_servers: Array.from({length: 12}, (_, i) => ({name: 'srv' + i, transport: 'http', enabled: i % 2 === 0}))});
let facts = box('facts').innerHTML;
assert.ok(facts.includes('tool12') && !facts.includes('tool13'));
const more = box('facts').querySelectorAll('[data-cfg-more]');
assert.deepEqual(more.map((b) => b.dataset.cfgMore), ['toolsets'], 'twelve entries are not collapsed');
assert.ok(facts.includes('+3 more'));
more[0].onclick();
facts = box('facts').innerHTML;
assert.ok(facts.includes('tool13') && facts.includes('tool15') && facts.includes('show fewer'));
box('facts').querySelector('[data-cfg-more]').onclick();
assert.ok(!box('facts').innerHTML.includes('tool13'));
// the expansion survives a redraw of the card
box('facts').querySelector('[data-cfg-more]').onclick();
detail(bot);
assert.ok(box('facts').innerHTML.includes('tool15'));
""")
    run_ui(tmp_path, r"""
detail(bot); toggle();
answer({skills: Array.from({length: 14}, (_, i) => ({name: 'skill' + i, enabled: false})),
  mcp_servers: Array.from({length: 13}, (_, i) => ({name: 'srv' + i, transport: 'stdio', enabled: true}))});
const facts = box('facts').innerHTML;
assert.ok(facts.includes('0 of 14 enabled') && facts.includes('disabled: skill0'));
assert.ok(!facts.includes('skill12') && facts.includes('skill11') && facts.includes('+2 more'));
assert.ok(facts.includes('srv11') && !facts.includes('srv12') && facts.includes('+1 more'));
assert.deepEqual(box('facts').querySelectorAll('[data-cfg-more]').map((b) => b.dataset.cfgMore), ['skills', 'mcp']);
""")


def test_reload_asks_again_and_a_snapshot_never_does(tmp_path):
    run_ui(tmp_path, r"""
open(); answerHistory();
assert.equal(sent('pixelhqProfile').length, 1);
for (let i = 0; i < 3; i++) { send({pixelhq: DATA}); send({pixelhqLive: {generated: 1, bots: {}}}); }
assert.equal(sent('pixelhqProfile').length, 1, 'cached until Reload');
box('status').querySelector('[data-cfg-reload]').onclick();
assert.equal(sent('pixelhqProfile').length, 2);
assert.notEqual(sent('pixelhqProfile')[1].rid, sent('pixelhqProfile')[0].rid);
box('status').querySelector('[data-cfg-reload]').onclick();
assert.equal(sent('pixelhqProfile').length, 2, 'a disabled Reload sends nothing while loading');
answer({description: 'Changed on the host'});
assert.ok(box('facts').innerHTML.includes('Changed on the host'));
assert.equal(sent('pixelhqSoulHistory').length, 2, 'the history is read again with the profile');
""")


def test_timeout_shows_an_error_and_a_late_answer_replaces_it(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
detail(bot); toggle();
const rid = lastRid('pixelhqProfile');
assert.equal(box('status').dataset.state, 'loading');
now += 21000; timers.splice(0).forEach((fn) => fn());
assert.equal(box('status').dataset.state, 'error');
assert.ok(box('status').innerHTML.includes('no answer from the host (timeout)'));
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, false, 'the control is recoverable');
// a spoofed message and an answer for another request do nothing
listeners.get('message')({source: {}, data: {pixelhqProfileResult: {rid, state: 'ready', data: profile()}}});
send({pixelhqProfileResult: {rid: 'f'.repeat(16), state: 'ready', data: profile()}});
assert.equal(box('status').dataset.state, 'error');
send({pixelhqProfileResult: {rid, state: 'ready', data: profile()}});
assert.equal(box('status').dataset.state, 'ready');
assert.ok(box('facts').innerHTML.includes('sample-provider'));
send({pixelhqProfileResult: {rid, state: 'error', message: 'duplicate'}});
assert.equal(box('status').dataset.state, 'ready', 'an answer is taken once');
""")


def test_remote_bot_is_requested_as_remote_and_keeps_its_own_state(tmp_path):
    run_ui(tmp_path, r"""
bot.remote = true;
detail(bot); toggle();
assert.equal(sent('pixelhqProfile')[0].remote, true);
assert.equal(cfg().dataset.cfg, 'remote/' + bot.id);
answer();
assert.equal(sent('pixelhqSoulHistory')[0].remote, true);
press('edit'); editor().value = 'changed'; editor().oninput(); press('preview'); confirmTwice();
assert.equal(sent('pixelhqSoulSave')[0].remote, true);
assert.equal(confStates.has('local/' + bot.id), false);
""")


def test_unusable_answers_are_an_error_not_a_crash(tmp_path):
    run_ui(tmp_path, r"""
detail(bot); toggle();
for (const data of [null, 'text', [], {soul: 5, soulHash: HASH}, {soul: 'x', soulHash: 'nothex'}, {soul: 'x'}]) {
  send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: 'ready', data}});
  assert.equal(box('status').dataset.state, 'error', JSON.stringify(data));
  assert.ok(box('status').innerHTML.includes('Unexpected profile answer'));
  assert.equal(box('soul').innerHTML, '');
  box('status').querySelector('[data-cfg-reload]').onclick();
}
send({pixelhqProfileResult: 'text'}); send({pixelhqProfileResult: {state: 'ready'}}); send({pixelhqSoulSaveResult: 5});
send({pixelhqSoulHistoryResult: {rid: 7}}); send({pixelhqSoulHistoryItemResult: []});
const odd = {name: 5, description: {}, soul: 'ok', soulHash: HASH, model: 'x', skills: 'x', toolsets: [1, null, {name: 'files'}],
  toolsets_pinned: 'yes', mcp_servers: [{name: ['a'], enabled: false}]};
send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: 'ready', data: odd}});
assert.equal(box('status').dataset.state, 'ready');
assert.ok(box('facts').innerHTML.includes('pinned: no'));
""")


def test_standalone_demo_shows_read_only_data_with_editing_and_history_disabled(tmp_path):
    run_ui(tmp_path, r"""
const demo = DATA.demoProfiles[bot.id];
assert.ok(demo && demo.soul && DATA.demo === true);
detail(bot); toggle();
assert.equal(messages.length, 0, 'the standalone page talks to nobody');
assert.equal(box('status').dataset.state, 'demo');
assert.ok(box('status').innerHTML.includes('synthetic demo data, read-only'));
assert.equal(box('status').querySelector('[data-cfg-reload]'), null);
assert.ok(box('facts').innerHTML.includes(demo.model.default));
assert.ok(box('facts').innerHTML.includes('Change model, skills and toolsets in Hermes'));
const ta = editor();
assert.equal(ta.readOnly, true);
assert.equal(ta.value, demo.soul);
const edit = box('soul').querySelector('[data-cfg-edit]');
assert.equal(edit.disabled, true);
edit.onclick(); startEdit(state());
assert.equal(state().draft, null, 'no draft without a host');
assert.equal(editor().readOnly, true);
assert.ok(box('history').innerHTML.includes('disabled on the standalone page'));
assert.equal(box('history').querySelectorAll('[data-cfg-restore]').length, 0);
sendSave(state()); loadHistory(state()); previewVersion(state(), 'x');
assert.equal(messages.length, 0);
// 15 skills in the leader's demo profile: the collapse shows in the demo too
assert.ok(box('facts').querySelector('[data-cfg-more]'));
""", iframe=False)


def test_every_demo_profile_is_synthetic_and_valid(tmp_path):
    run_ui(tmp_path, r"""
const ids = DATA.bots.map((b) => b.id);
assert.deepEqual(Object.keys(DATA.demoProfiles).sort(), ids.slice().sort());
for (const id of ids) {
  const p = cleanProfile({...DATA.demoProfiles[id], soulHash: HASH});
  assert.ok(p, id);
  assert.equal(soulProblem(p.soul), '');
  assert.ok(p.skills.length >= 4 && p.model.default && p.mcp.length >= 1);
}
assert.ok(DATA.bots.some((b) => lostMessaging(DATA.demoProfiles[b.id].soul, 'x')), 'one demo SOUL has the messaging section');
assert.ok(DATA.bots.some((b) => !lostMessaging(DATA.demoProfiles[b.id].soul, 'x')));
""", iframe=False)


def test_standalone_page_with_real_data_has_no_demo_profile_and_says_so(tmp_path):
    data = snapshot()
    data.pop("demoProfiles")
    data["demo"] = False
    run_ui(tmp_path, r"""
detail(bot); toggle();
assert.equal(box('status').dataset.state, 'nohost');
assert.ok(box('status').innerHTML.includes('only available inside Hermes Desktop'));
assert.equal(box('facts').innerHTML, '');
assert.equal(box('soul').innerHTML, '');
assert.equal(messages.length, 0);
""", iframe=False, data=data)


# ---------------------------------------------------------------- MUST 2: SOUL editor, preview, save


def test_edit_preview_confirm_save_flow_and_the_new_soul_after_saved(tmp_path):
    run_ui(tmp_path, r"""
open(); answerHistory();
let ta = editor();
assert.equal(ta.readOnly, true);
assert.equal(ta.value, SOUL);
assert.equal(ta.attrs.spellcheck, 'false');
assert.ok(box('soul').innerHTML.includes('3 lines'));
press('edit');
ta = editor();
assert.equal(ta.readOnly, false);
assert.equal(ta.value, SOUL);
assert.equal(document.activeElement, ta, 'the editor takes the focus');
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, true, 'unchanged text cannot be previewed');
assert.ok(box('soul').innerHTML.includes('Preview changes') && box('soul').innerHTML.includes('Cancel'));
ta.value = 'Line one\nLINE TWO\nLine three\n'; ta.oninput();
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, false);
press('preview');
assert.equal(editor(), null, 'the preview replaces the editor');
assert.equal(rowKinds(), ' -+ ');
assert.deepEqual(slotTexts(box('soul')), ['Line one', 'Line two', 'LINE TWO', 'Line three']);
assert.ok(box('soul').innerHTML.includes('+1 −1'));
assert.equal(sent('pixelhqSoulSave').length, 0, 'previewing writes nothing');
const confirm = box('soul').querySelector('[data-cfg-confirm]');
confirm.onclick();
assert.equal(sent('pixelhqSoulSave').length, 0, 'the first click only arms');
assert.equal(confirm.textContent, 'Click again to save');
assert.ok(confirm.classList.contains('armed'));
confirm.onclick();
assert.equal(sent('pixelhqSoulSave').length, 1);
const body = sent('pixelhqSoulSave')[0];
assert.match(body.rid, /^[0-9a-f]{16,32}$/);
assert.deepEqual({...body, rid: 'x'}, {rid: 'x', bot: bot.id, remote: false, baseHash: HASH, soul: 'Line one\nLINE TWO\nLine three\n'});
assert.ok(box('soul').innerHTML.includes('Saving …'));
saved(body.rid);
assert.equal(state().draft, null);
assert.equal(editor().readOnly, true);
assert.equal(editor().value, 'Line one\nLINE TWO\nLine three\n', 'the panel shows the new SOUL');
assert.ok(box('soul').innerHTML.includes('res ok') && box('soul').innerHTML.includes('SOUL saved.'));
assert.equal(state().data.soulHash, HASH2);
assert.equal(sent('pixelhqSoulHistory').length, 2, 'the history is read again after a save');
assert.equal(sent('pixelhqProfile').length, 1, 'no extra describe after saved');
// the next edit starts from the saved text and its hash
press('edit');
assert.equal(editor().value, 'Line one\nLINE TWO\nLine three\n');
assert.equal(state().draft.baseHash, HASH2);
assert.ok(!box('soul').innerHTML.includes('SOUL saved.'), 'the old result line is gone');
""")


def test_back_to_editing_keeps_the_draft_and_cancel_drops_it(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('first draft\nsecond');
press('preview');
assert.ok(box('soul').querySelector('[data-cfg-back]') && box('soul').querySelector('[data-cfg-confirm]'));
press('back');
assert.equal(editor().value, 'first draft\nsecond');
assert.equal(document.activeElement, editor());
editor().value = 'first draft\nsecond\nthird'; editor().oninput();
press('preview');
assert.equal(slotTexts(box('soul')).at(-1), 'third');
press('cancel');
assert.equal(state().draft, null);
assert.equal(editor().value, SOUL, 'cancel shows the loaded SOUL again');
assert.equal(editor().readOnly, true);
press('edit');
assert.equal(editor().value, SOUL, 'a new edit starts from the loaded text');
press('cancel');
assert.equal(sent('pixelhqSoulSave').length, 0);
// cancel in the middle of editing
startEditing('typed'); press('cancel');
assert.equal(state().draft, null);
""")


def test_unchanged_text_has_no_save_in_any_form(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = startEditing();
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, true);
assert.ok(box('soul').querySelector('[data-cfg-hint]').textContent.includes('No changes yet'));
press('preview'); assert.equal(state().draft.mode, 'edit', 'a click on the disabled button does nothing');
ta.value = SOUL + 'x'; ta.oninput();
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, false);
assert.equal(box('soul').querySelector('[data-cfg-hint]').textContent, '');
ta.value = SOUL; ta.oninput();
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, true, 'typing the change away disables Preview again');
// line endings alone are not a change
ta.value = SOUL.replace(/\n/g, '\r\n'); ta.oninput();
assert.equal(box('soul').querySelector('[data-cfg-preview]').disabled, true);
sendSave(state());
assert.equal(sent('pixelhqSoulSave').length, 0);
state().draft.mode = 'preview'; sendSave(state());
assert.equal(sent('pixelhqSoulSave').length, 0, 'even a forced preview of identical text is never sent');
""")


def test_inline_limits_block_the_preview(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = startEditing();
const problem = () => box('soul').querySelector('[data-cfg-problem]').textContent;
const previewOff = () => box('soul').querySelector('[data-cfg-preview]').disabled;
ta.value = 'a\u0000b'; ta.oninput();
assert.equal(problem(), 'The SOUL contains control characters other than tab and line breaks');
assert.equal(previewOff(), true);
press('preview'); assert.equal(state().draft.mode, 'edit');
ta.value = 'x'.repeat(65537); ta.oninput();
assert.equal(problem(), 'The SOUL is longer than 64 KiB');
assert.equal(previewOff(), true);
ta.value = 'x'.repeat(65536); ta.oninput();
assert.equal(problem(), ''); assert.equal(previewOff(), false);
assert.ok(box('soul').querySelector('[data-cfg-count]').textContent.includes('65536 bytes'));
ta.value = 'tab\there\r\nnew line'; ta.oninput();
assert.equal(problem(), ''); assert.equal(previewOff(), false);
press('preview');
state().draft.text = 'a\u0001'; // forced: the preview still refuses to send
press('back');
""")


def test_messaging_section_warning_in_the_preview_only_when_it_was_removed(tmp_path):
    run_ui(tmp_path, r"""
const H = '## Messaging other agents';
const WITH = 'Intro\n\n' + H + '\n\nAsk politely.\n';
detail(bot); toggle(); answer({soul: WITH});
startEditing('Intro\n');
press('preview');
const warning = box('soul').querySelector('[data-cfg-warning]');
assert.ok(warning, 'removing the section warns');
assert.ok(box('soul').innerHTML.includes('The Bot Mode messaging section was removed'));
assert.equal(box('soul').querySelector('[data-cfg-confirm]').disabled, false, 'saving stays possible');
press('back');
editor().value = WITH + 'More\n'; editor().oninput();
press('preview');
assert.equal(box('soul').querySelector('[data-cfg-warning]'), null, 'keeping the section does not warn');
press('cancel');
// a SOUL without the section: adding or leaving it out never warns
answer({soul: 'Plain\n'});
box('status').querySelector('[data-cfg-reload]').onclick(); answer({soul: 'Plain\n'});
startEditing('Other\n'); press('preview');
assert.equal(box('soul').querySelector('[data-cfg-warning]'), null);
press('back'); editor().value = 'Plain\n' + H + '\n'; editor().oninput(); press('preview');
assert.equal(box('soul').querySelector('[data-cfg-warning]'), null);
""")


@pytest.mark.parametrize("outcome, css, text, keeps_draft", [
    ("saved", "res ok", "SOUL saved.", False),
    ("unverified", "res warn", "Saved, but the read-back differs", False),
    ("conflict", "res warn", "The SOUL changed since you opened it. Reload to see the current version.", True),
    ("failed", "res bad", "Backup of the current SOUL failed, nothing was written: disk full", True),
    ("error", "res bad", "The SOUL is longer than 64 KiB", True),
    ("unsupported", "res bad", "This Hermes version has no profile editor API", True),
])
def test_every_save_state_gets_its_result_line(tmp_path, outcome, css, text, keeps_draft):
    run_ui(tmp_path, r"""
open();
startEditing('new text'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
send({pixelhqSoulSaveResult: {rid, state: OUTCOME, message: TEXT, soulHash: HASH2}});
const line = box('soul').querySelector('[data-cfg-result]');
assert.equal(line.dataset.cfgResult, OUTCOME);
assert.ok(line.attrs.class.includes(CSS), line.attrs.class);
assert.ok(box('soul').innerHTML.includes(TEXT), box('soul').innerHTML);
assert.equal(!!state().draft, KEEPS);
if (KEEPS) {
  assert.equal(state().draft.mode, 'preview');
  assert.equal(box('soul').querySelector('[data-cfg-confirm]').disabled, false, 'recoverable: the buttons work again');
  assert.equal(box('soul').querySelector('[data-cfg-cancel]').disabled, false);
}
const reloadOff = (KEEPS && OUTCOME !== 'conflict') || OUTCOME === 'unverified';
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, reloadOff,
  'Reload is closed under a draft (except after a conflict) and while the profile is read again');
if (OUTCOME === 'unverified') {
  assert.equal(sent('pixelhqProfile').length, 2, 'an unverified save reads the profile again');
  assert.equal(state().data.soul, SOUL, 'until then the old text is not shown as saved');
}
if (OUTCOME === 'saved') assert.equal(state().data.soul, 'new text');
""".replace("OUTCOME", json.dumps(outcome)).replace("CSS", json.dumps(css)).replace("TEXT", json.dumps(text))
           .replace("KEEPS", json.dumps(keeps_draft)))


def test_a_save_result_without_message_uses_the_state_text(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('new text'); press('preview'); confirmTwice();
send({pixelhqSoulSaveResult: {rid: lastRid('pixelhqSoulSave'), state: 'failed'}});
assert.ok(box('soul').innerHTML.includes('The SOUL was not written.'));
confirmTwice();
send({pixelhqSoulSaveResult: {rid: lastRid('pixelhqSoulSave'), state: 'surprise', message: 'odd'}});
assert.equal(box('soul').querySelector('[data-cfg-result]').dataset.cfgResult, 'error', 'unknown states are errors');
""")


def test_pending_save_locks_the_buttons_and_sends_once(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('new text'); press('preview'); confirmTwice();
const soul = () => box('soul');
for (const name of ['confirm', 'back', 'cancel']) assert.equal(soul().querySelector('[data-cfg-' + name + ']').disabled, true, name);
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, true);
confirmTwice(); press('cancel'); press('back');
assert.equal(sent('pixelhqSoulSave').length, 1, 'no second request while one is open');
assert.equal(state().draft.mode, 'preview', 'cancel and back are ignored while saving');
// the card is redrawn while saving: the pending line stays
detail(bot);
assert.ok(box('soul').innerHTML.includes('Saving …'));
""")


def test_save_timeout_is_recoverable_keeps_the_request_id_and_a_late_answer_wins(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
startEditing('new text'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
now += 74000;
assert.ok(box('soul').innerHTML.includes('Saving …'), 'the save may take longer than 20 s');
now += 2000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('soul').innerHTML.includes('no answer from the host (timeout)'));
assert.equal(box('soul').querySelector('[data-cfg-result]').dataset.cfgResult, 'timeout');
assert.equal(box('soul').querySelector('[data-cfg-confirm]').disabled, false);
// retry: the same request id (the backup is idempotent per id)
confirmTwice();
assert.equal(sent('pixelhqSoulSave').length, 2);
assert.equal(lastRid('pixelhqSoulSave'), rid);
now += 76000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('soul').innerHTML.includes('timeout'));
// the late answer of the first try replaces the timeout line and finishes the save
saved(rid);
assert.ok(box('soul').innerHTML.includes('SOUL saved.') && !box('soul').innerHTML.includes('timeout'));
assert.equal(state().draft, null);
assert.equal(editor().value, 'new text');
""")


def test_late_saved_answer_does_not_replace_what_is_typed_meanwhile(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
startEditing('first change'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
now += 76000; timers.splice(0).forEach((fn) => fn());
press('back');
const ta = editor();
ta.value = 'first change, then more'; ta.oninput();
saved(rid);
assert.equal(editor(), ta, 'the textarea under the cursor is not replaced');
assert.equal(ta.value, 'first change, then more');
assert.equal(state().draft.text, 'first change, then more');
assert.equal(state().draft.base, 'first change', 'the draft is now compared with the saved text');
assert.equal(state().draft.baseHash, HASH2);
assert.equal(state().data.soul, 'first change');
press('preview');
assert.deepEqual(slotTexts(box('soul')), ['first change', 'first change, then more']);
""")


def test_conflict_reload_keeps_the_text_and_compares_with_the_current_version(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('Line one\nmine\nLine three\n'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
send({pixelhqSoulSaveResult: {rid, state: 'conflict', message: 'The SOUL changed since you opened it. Reload to see the current version.'}});
assert.equal(state().draft.rid, null, 'a conflict ends this request id');
const reload = box('status').querySelector('[data-cfg-reload]');
assert.equal(reload.disabled, false);
reload.onclick();
assert.equal(sent('pixelhqProfile').length, 2);
assert.equal(state().draft.text, 'Line one\nmine\nLine three\n', 'the text is not lost by the reload');
// the host version has changed meanwhile
answer({soul: 'Line one\nLine two, changed elsewhere\nLine three\n', soulHash: HASH2});
assert.equal(state().draft.mode, 'edit');
assert.equal(state().draft.baseHash, HASH2);
assert.equal(editor().value, 'Line one\nmine\nLine three\n');
assert.ok(box('soul').innerHTML.includes('Current version loaded — your draft is kept'));
assert.ok(!box('soul').innerHTML.includes('The SOUL changed since you opened it'), 'the conflict line is replaced');
press('preview');
assert.deepEqual(slotTexts(box('soul')), ['Line one', 'Line two, changed elsewhere', 'mine', 'Line three']);
confirmTwice();
const second = sent('pixelhqSoulSave')[1];
assert.equal(second.baseHash, HASH2);
assert.notEqual(second.rid, rid, 'a new request id after a conflict');
// Reload stays closed for a draft without a conflict
saved(second.rid);
startEditing('x');
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, true);
""")


def test_failed_save_gets_a_new_request_id_for_the_retry(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('new text'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
send({pixelhqSoulSaveResult: {rid, state: 'failed', message: 'Backup of the current SOUL failed, nothing was written: disk full'}});
// the bridge keeps the final answer of a request id, so a retry after a final answer is a new request
assert.equal(state().draft.rid, null);
confirmTwice();
assert.equal(sent('pixelhqSoulSave').length, 2);
assert.notEqual(lastRid('pixelhqSoulSave'), rid);
assert.equal(sent('pixelhqSoulSave')[1].baseHash, HASH);
""")


def test_a_timeout_is_not_final_for_a_save_a_late_saved_answer_is_applied(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
startEditing('new text'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
now += 76000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('soul').innerHTML.includes('timeout'));
saved(rid);
assert.equal(state().data.soul, 'new text');
assert.equal(state().data.soulHash, HASH2);
assert.equal(state().draft, null);
assert.ok(box('soul').innerHTML.includes('SOUL saved.'));
assert.ok(!box('status').innerHTML.includes('data-cfg-late'), 'applied, not a note');
// the bridge repeats a final answer on a retry after completion: the second copy changes nothing
saved(rid, {soulHash: 'c'.repeat(64)});
assert.equal(state().data.soulHash, HASH2);
""")


def test_retry_after_timeout_is_the_same_save_and_its_one_final_answer_is_applied(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
startEditing('new text'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
now += 76000; timers.splice(0).forEach((fn) => fn());
confirmTwice();
assert.deepEqual(sent('pixelhqSoulSave').map((m) => m.rid), [rid, rid], 'the retry is the same save');
saved(rid);
assert.equal(state().data.soul, 'new text');
assert.equal(state().draft, null);
startEditing('other text'); press('preview'); confirmTwice();
assert.notEqual(lastRid('pixelhqSoulSave'), rid, 'a later save is another request');
""")


def test_a_late_answer_for_a_save_the_panel_moved_on_from_is_a_note_only(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
startEditing('first text'); press('preview'); confirmTwice();
const first = lastRid('pixelhqSoulSave');
now += 76000; timers.splice(0).forEach((fn) => fn());
press('back');
const ta = editor(); ta.value = 'second text'; ta.oninput();
press('preview'); confirmTwice();
const second = lastRid('pixelhqSoulSave');
assert.notEqual(second, first, 'another text is another request id');
saved(first);
assert.equal(state().data.soul, SOUL, 'the SOUL on screen is not touched by the old save');
assert.equal(state().draft.text, 'second text');
assert.equal(state().draft.rid, second);
assert.ok(box('soul').innerHTML.includes('Saving …'), 'the second save is still running');
const late = box('status').querySelector('[data-cfg-late]') && box('status').innerHTML;
assert.ok(late && late.includes('An earlier save finished'), 'shown as a note');
saved(second, {soulHash: 'c'.repeat(64)});
assert.equal(state().data.soul, 'second text');
assert.equal(state().draft, null);
// a cancelled draft: the late answer is a note too
startEditing('third'); press('preview'); confirmTwice();
const third = lastRid('pixelhqSoulSave');
now += 76000; timers.splice(0).forEach((fn) => fn());
press('cancel');
saved(third, {soulHash: 'd'.repeat(64)});
assert.equal(state().data.soul, 'second text');
assert.ok(box('status').querySelector('[data-cfg-late]'));
""")


def test_a_describe_reply_never_replaces_a_focused_editor(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('mine'); press('preview'); confirmTwice();
const rid = lastRid('pixelhqSoulSave');
send({pixelhqSoulSaveResult: {rid, state: 'conflict', message: 'changed'}});
box('status').querySelector('[data-cfg-reload]').onclick();
// the reload is slow; the still enabled Back button lets the operator continue typing
press('back');
const ta = editor(); ta.value = 'mine, still typing'; ta.oninput();
ta.selectionStart = 5; ta.selectionEnd = 8;
assert.equal(document.activeElement, ta);
answer({soul: 'host changed', soulHash: HASH2});
assert.equal(editor(), ta, 'same textarea element');
assert.equal(document.activeElement, ta, 'same focus');
assert.equal([ta.selectionStart, ta.selectionEnd].join(), '5,8', 'same caret');
assert.equal(ta.value, 'mine, still typing');
assert.equal(state().draft.text, 'mine, still typing');
assert.equal(state().draft.base, 'host changed');
assert.equal(state().draft.baseHash, HASH2);
assert.equal(state().data.soul, 'host changed');
assert.ok(box('status').innerHTML.includes('Current version loaded — your draft is kept'));
assert.ok(!box('soul').innerHTML.includes('changed since you opened'), 'the old conflict line is gone');
press('preview');
assert.deepEqual(slotTexts(box('soul')), ['host changed', 'mine, still typing'], 'the next preview diffs against the new base');
""")


def test_a_describe_reply_while_the_textarea_has_focus_but_no_draft_does_not_replace_it(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = editor(); ta.focus();
assert.equal(document.activeElement, ta);
box('status').querySelector('[data-cfg-reload]').onclick();
answer({soul: 'changed on the host', soulHash: HASH2});
assert.equal(editor(), ta, 'a focused field is not rendered under the cursor');
assert.equal(state().data.soul, 'changed on the host', 'the base is current');
ta.blur(); flushZeroTimers();
assert.equal(editor().value, 'changed on the host', 'the deferred render runs when the focus leaves');
""")


def test_the_save_never_runs_in_a_frame_without_host_and_ignores_stale_results(tmp_path):
    run_ui(tmp_path, r"""
open();
startEditing('new text'); press('preview'); confirmTwice();
send({pixelhqSoulSaveResult: {rid: 'e'.repeat(16), state: 'saved', soulHash: HASH2}});
listeners.get('message')({source: {}, data: {pixelhqSoulSaveResult: {rid: lastRid('pixelhqSoulSave'), state: 'saved', soulHash: HASH2}}});
assert.equal(state().data.soul, SOUL, 'only the parent can answer, and only for an open request');
assert.ok(box('soul').innerHTML.includes('Saving …'));
// saved without a usable hash: the profile is read again instead of guessing
send({pixelhqSoulSaveResult: {rid: lastRid('pixelhqSoulSave'), state: 'saved', soulHash: 'short'}});
assert.equal(sent('pixelhqProfile').length, 2);
assert.equal(state().draft, null);
""")


# ---------------------------------------------------------------- MUST 3: history and restore


def test_history_is_listed_newest_first_with_time_and_first_line(tmp_path):
    run_ui(tmp_path, r"""
open();
assert.equal(sent('pixelhqSoulHistory').length, 1);
const req = sent('pixelhqSoulHistory')[0];
assert.deepEqual({bot: req.bot, remote: req.remote, keys: Object.keys(req).sort()}, {bot: bot.id, remote: false, keys: ['bot', 'remote', 'rid']});
assert.ok(box('history').innerHTML.includes('Loading history'));
answerHistory();
const rows = box('history').querySelectorAll('[data-cfg-version]');
assert.deepEqual(rows.map((r) => r.dataset.cfgVersion), [ITEMS[0].id, ITEMS[1].id], 'the backend order is kept, never re-sorted');
assert.deepEqual(slotTexts(box('history')), ['Oldest soul', 'Newest soul']);
assert.ok(box('history').innerHTML.includes(clock(Date.parse(ITEMS[1].savedAt) / 1000)));
assert.ok(box('history').innerHTML.includes('40 B'));
assert.equal(box('history').querySelectorAll('[data-cfg-restore]').length, 2);
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => !b.disabled));
assert.ok(box('history').innerHTML.includes('newest first'));
""")


@pytest.mark.parametrize("items, status, message, shown", [
    ([], "ready", None, "No earlier versions yet."),
    (None, "error", "History <b>unavailable</b>", "History &lt;b&gt;unavailable&lt;/b&gt;"),
    (None, "unsupported", None, "This Hermes version has no profile editor API"),
])
def test_history_empty_and_failure_states(tmp_path, items, status, message, shown):
    run_ui(tmp_path, r"""
open();
answerHistory(ITEMS_VALUE, STATUS, MESSAGE);
assert.ok(box('history').innerHTML.includes(SHOWN), box('history').innerHTML);
assert.ok(!box('history').innerHTML.includes('<b>'));
assert.equal(box('history').querySelectorAll('[data-cfg-restore]').length, 0);
assert.equal(box('status').dataset.state, 'ready', 'a failing history does not hide the SOUL');
assert.ok(editor());
""".replace("ITEMS_VALUE", json.dumps(items)).replace("STATUS", json.dumps(status)).replace("MESSAGE", json.dumps(message))
           .replace("SHOWN", json.dumps(shown)))


def test_history_ignores_entries_that_are_not_version_files(tmp_path):
    run_ui(tmp_path, r"""
open();
answerHistory([ITEMS[0], {id: '../../etc/passwd', savedAt: 'x', bytes: 1, firstLine: 'bad'}, {id: 5}, null, 'text',
  {id: '20261111T000000Z-00000000.md', savedAt: 'not a date', bytes: 'many', firstLine: 'x'.repeat(200)}]);
const rows = box('history').querySelectorAll('[data-cfg-version]');
assert.deepEqual(rows.map((r) => r.dataset.cfgVersion), [ITEMS[0].id, '20261111T000000Z-00000000.md']);
assert.ok(box('history').innerHTML.includes('not a date'));
assert.ok(box('history').innerHTML.includes('0 B'));
assert.equal(slotTexts(box('history'))[1].length, 80);
assert.equal(box('history').querySelectorAll('[data-cfg-restore]')[1].dataset.cfgRestore, '20261111T000000Z-00000000.md');
""")


def test_history_timeout_is_an_error_and_a_late_list_replaces_it(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();
const rid = lastRid('pixelhqSoulHistory');
now += 21000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('history').innerHTML.includes('no answer from the host (timeout)'));
send({pixelhqSoulHistoryResult: {rid, state: 'ready', items: ITEMS}});
assert.equal(box('history').querySelectorAll('[data-cfg-version]').length, 2);
assert.ok(!box('history').innerHTML.includes('timeout'));
""")


def test_restore_preview_shows_the_diff_current_to_chosen_and_confirm_restores(tmp_path):
    run_ui(tmp_path, r"""
open(); answerHistory();
const newest = ITEMS[1].id;
restoreBtn(newest).onclick();
assert.equal(sent('pixelhqSoulHistoryItem').length, 1);
const req = sent('pixelhqSoulHistoryItem')[0];
assert.deepEqual({...req, rid: 'x'}, {rid: 'x', bot: bot.id, remote: false, id: newest});
assert.match(req.rid, /^[0-9a-f]{16,32}$/);
assert.ok(box('history').innerHTML.includes('Loading version'));
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => b.disabled), 'one version at a time');
box('history').querySelector('[data-cfg-restore]').onclick();
assert.equal(sent('pixelhqSoulHistoryItem').length, 1);
send({pixelhqSoulHistoryItemResult: {rid: req.rid, state: 'ready', id: newest, text: 'Line one\nOlder line two\n'}});
assert.equal(state().draft.kind, 'restore');
assert.equal(state().draft.mode, 'preview');
assert.equal(editor(), null, 'a restore has no editor');
assert.equal(rowKinds(), ' --+', 'the diff goes from the current SOUL to the chosen version');
assert.deepEqual(slotTexts(box('soul')), ['Line one', 'Line two', 'Line three', 'Older line two']);
assert.ok(box('soul').innerHTML.includes('RESTORE PREVIEW'));
assert.ok(box('soul').innerHTML.includes(clock(Date.parse(ITEMS[1].savedAt) / 1000)));
assert.equal(box('soul').querySelector('[data-cfg-back]'), null);
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => b.disabled), 'no second preview while one is open');
const confirm = box('soul').querySelector('[data-cfg-confirm]');
assert.equal(confirm.disabled, false);
confirm.onclick();
assert.equal(confirm.textContent, 'Click again to restore');
assert.equal(sent('pixelhqSoulSave').length, 0, 'the first click only arms');
confirm.onclick();
const body = sent('pixelhqSoulSave')[0];
assert.deepEqual({...body, rid: 'x'}, {rid: 'x', bot: bot.id, remote: false, baseHash: HASH, soul: 'Line one\nOlder line two\n'});
assert.ok(box('soul').innerHTML.includes('Restoring …'));
saved(body.rid);
assert.equal(state().draft, null);
assert.equal(editor().value, 'Line one\nOlder line two\n');
assert.equal(sent('pixelhqSoulHistory').length, 2, 'the replaced version appears in the refreshed history');
answerHistory([...ITEMS, {id: '20261112T020000Z-fedcba98.md', savedAt: '2026-11-12T02:00:00Z', bytes: 28, firstLine: 'Line one'}]);
assert.equal(box('history').querySelectorAll('[data-cfg-version]').length, 3);
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => !b.disabled));
""")


def test_restore_cancel_and_identical_version(tmp_path):
    run_ui(tmp_path, r"""
open(); answerHistory();
const ask = (id, text) => {
  restoreBtn(id).onclick();
  send({pixelhqSoulHistoryItemResult: {rid: lastRid('pixelhqSoulHistoryItem'), state: 'ready', id, text}});
};
ask(ITEMS[0].id, SOUL);
assert.ok(box('soul').innerHTML.includes('No changes'));
assert.equal(box('soul').querySelector('[data-cfg-confirm]').disabled, true, 'restoring the current text is a no-op');
press('cancel');
assert.equal(state().draft, null);
assert.equal(editor().value, SOUL);
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => !b.disabled), 'previews are open again');
ask(ITEMS[0].id, 'older');
press('cancel');
assert.equal(sent('pixelhqSoulSave').length, 0);
// a version with control characters can be looked at but not restored
ask(ITEMS[0].id, 'bad\u0000text');
assert.ok(box('soul').innerHTML.includes('control characters'));
assert.equal(box('soul').querySelector('[data-cfg-confirm]').disabled, true);
""")


def test_history_item_failures_are_shown_and_stale_answers_are_dropped(tmp_path):
    run_ui(tmp_path, r"""
open(); answerHistory();
const click = (id) => restoreBtn(id).onclick();
click(ITEMS[0].id);
send({pixelhqSoulHistoryItemResult: {rid: lastRid('pixelhqSoulHistoryItem'), state: 'error', message: 'No such <i>version</i>'}});
assert.ok(box('history').innerHTML.includes('No such &lt;i&gt;version&lt;/i&gt;') && !box('history').innerHTML.includes('<i>'));
assert.equal(state().draft, null);
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => !b.disabled), 'recoverable');
// an answer for another version id, or a text that is not a string, opens nothing
click(ITEMS[0].id);
send({pixelhqSoulHistoryItemResult: {rid: lastRid('pixelhqSoulHistoryItem'), state: 'ready', id: ITEMS[1].id, text: 'x'}});
assert.equal(state().draft, null);
click(ITEMS[0].id);
send({pixelhqSoulHistoryItemResult: {rid: lastRid('pixelhqSoulHistoryItem'), state: 'ready', id: ITEMS[0].id, text: 5}});
assert.equal(state().draft, null);
// an unknown id is never requested
const before = sent('pixelhqSoulHistoryItem').length;
previewVersion(state(), '20250101T000000Z-00000000.md');
assert.equal(sent('pixelhqSoulHistoryItem').length, before);
// an answer that arrives after the user started editing is dropped
click(ITEMS[0].id);
const late = lastRid('pixelhqSoulHistoryItem');
press('edit');
send({pixelhqSoulHistoryItemResult: {rid: late, state: 'ready', id: ITEMS[0].id, text: 'late text'}});
assert.equal(state().draft.kind, 'edit');
assert.equal(editor().value, SOUL);
""")


def test_history_buttons_are_locked_while_a_draft_exists_and_item_timeout_recovers(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open(); answerHistory();
press('edit');
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => b.disabled));
previewVersion(state(), ITEMS[0].id);
assert.equal(sent('pixelhqSoulHistoryItem').length, 0);
press('cancel');
box('history').querySelector('[data-cfg-restore]').onclick();
const rid = lastRid('pixelhqSoulHistoryItem');
now += 21000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('history').innerHTML.includes('no answer from the host (timeout)'));
assert.ok(box('history').querySelectorAll('[data-cfg-restore]').every((b) => !b.disabled));
send({pixelhqSoulHistoryItemResult: {rid, state: 'ready', id: ITEMS[0].id, text: 'older'}});
assert.equal(state().draft.kind, 'restore', 'the late answer opens the preview');
""")


def test_history_requested_for_a_remote_bot_and_a_second_request_is_coalesced(tmp_path):
    run_ui(tmp_path, r"""
bot.remote = true;
open();
assert.equal(sent('pixelhqSoulHistory')[0].remote, true);
loadHistory(confStates.get('remote/' + bot.id));
assert.equal(sent('pixelhqSoulHistory').length, 1, 'one request at a time');
answerHistory();
assert.equal(sent('pixelhqSoulHistory').length, 2, 'the postponed request runs after the first answer');
""")


# ---------------------------------------------------------------- MUST 4: render rules and escaping


def test_textarea_is_not_replaced_while_focused_by_snapshot_live_or_theme_messages(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = startEditing('typed text');
assert.equal(document.activeElement, ta);
const same = (label) => {
  assert.equal(editor(), ta, label);
  assert.equal(ta.value, 'typed text', label);
  assert.equal(state().draft.text, 'typed text', label);
};
send({pixelhq: {...DATA, generated: DATA.generated + 60}}); same('snapshot');
send({pixelhqLive: {generated: 5, bots: {[bot.id]: {active: true, sessions: [], tasks: []}}}}); same('live');
send({pixelhqTheme: {mode: 'light'}}); same('theme');
send({pixelhqTheme: {mode: 'dark'}}); send({pixelhq: DATA}); same('again');
// results of other requests arrive meanwhile
answerHistory(); same('history result');
send({pixelhqProfileResult: {rid: 'd'.repeat(16), state: 'ready', data: profile({soul: 'other'})}}); same('stray describe');
send({pixelhqSoulSaveResult: {rid: 'c'.repeat(16), state: 'saved', soulHash: HASH2}}); same('stray save');
select(bot.id); same('select');
// once the focus leaves, the card is drawn again, around the very same panel
ta.blur(); flushZeroTimers();
same('after blur');
assert.equal(box('soul').querySelector('[data-cfg-text]'), ta);
""")


def test_draft_panel_survives_a_card_redraw_without_focus(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = startEditing('draft in progress');
const panel = cfg();
ta.blur();
const before = root().querySelector('.card');
detail(bot);
assert.notEqual(root().querySelector('.card'), before, 'the card itself is drawn again');
assert.equal(cfg(), panel, 'the panel with a draft is moved into the new card');
assert.equal(editor(), ta);
assert.equal(ta.value, 'draft in progress');
send({pixelhq: DATA}); send({pixelhqTheme: {mode: 'light'}});
assert.equal(editor(), ta);
// a preview is held the same way, with its armed state
press('preview');
const confirm = box('soul').querySelector('[data-cfg-confirm]');
confirm.onclick();
detail(bot);
assert.equal(box('soul').querySelector('[data-cfg-confirm]'), confirm);
assert.equal(confirm.textContent, 'Click again to save');
// another bot's card and back: the draft text is restored from the state
const other = DATA.bots[1];
detail(other);
assert.ok(!root().innerHTML.includes('data-cfg="local/' + bot.id));
assert.equal(cfg().dataset.cfg, 'local/' + other.id);
assert.equal(state().draft.text, 'draft in progress');
detail(bot);
assert.equal(state().draft.mode, 'preview');
assert.ok(box('soul').innerHTML.includes('Confirm save'));
press('back');
assert.equal(editor().value, 'draft in progress');
// cancelling the draft: the next redraw makes a plain panel again
press('cancel');
detail(bot);
assert.equal(editor().readOnly, true);
""")


def test_without_a_draft_the_panel_follows_redraws_and_a_focused_viewer_is_left_alone(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = editor();
ta.focus();
send({pixelhq: DATA}); send({pixelhqTheme: {mode: 'light'}});
assert.equal(editor(), ta, 'a focused (read-only) textarea is not redrawn either');
ta.blur(); flushZeroTimers();
assert.notEqual(editor(), ta, 'it is drawn again once the focus is gone');
assert.equal(editor().value, SOUL);
assert.ok(box('facts').innerHTML.includes('sample-provider'), 'the opened panel keeps its facts');
assert.equal(sent('pixelhqProfile').length, 1);
""")


def test_expiring_requests_do_not_redraw_an_editor_that_has_lost_the_focus(tmp_path):
    run_ui(tmp_path, r"""
let now = 1000; hostClock.now = () => now;
open();                                   // the history request stays unanswered
const ta = startEditing('typed text');
ta.blur(); flushZeroTimers();             // the cursor is elsewhere, the draft still exists
now += 21000; timers.splice(0).forEach((fn) => fn());
assert.ok(box('history').innerHTML.includes('no answer from the host (timeout)'), 'the expiry did redraw the other regions');
assert.equal(editor(), ta, 'the editor is the same element');
assert.equal(ta.value, 'typed text');
refreshConfig(state());
assert.equal(editor(), ta);
// a click on the panel is a user action and may redraw (Back to editing after a preview)
press('preview'); assert.equal(editor(), null);
press('back'); assert.equal(editor().value, 'typed text');
""")


def test_describe_and_history_answers_arriving_during_editing_keep_the_draft(tmp_path):
    run_ui(tmp_path, r"""
open();
const ta = startEditing('typed text');
box('status').querySelector('[data-cfg-reload]'); // disabled while a draft exists
assert.equal(box('status').querySelector('[data-cfg-reload]').disabled, true);
reloadConfig(state());
assert.equal(sent('pixelhqProfile').length, 1, 'no reload under a draft');
answerHistory();
assert.equal(editor(), ta);
loadHistory(state()); answerHistory([]);
assert.equal(editor(), ta);
assert.equal(ta.value, 'typed text');
assert.ok(box('history').innerHTML.includes('No earlier versions yet.'));
// collapsing and opening the section keeps the draft
toggle(); assert.equal(box('soul'), null); toggle();
assert.equal(editor().value, 'typed text');
assert.equal(state().draft.text, 'typed text');
""")


def test_hostile_names_and_texts_are_escaped_everywhere(tmp_path):
    run_ui(tmp_path, r"""
const evil = '<img src=x onerror=alert(1)>';
bot.id = 'sample<&"bot' + "'";
detail(bot);
assert.equal(cfg().dataset.cfg, 'local/' + bot.id);
assert.ok(!root().innerHTML.includes('<img') && !root().innerHTML.includes('sample<&"bot'));
toggle();
send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: 'ready', data: profile({
  name: evil, description: evil + ' & "quoted"', model: {provider: evil, default: '</div>' + evil},
  skills: [{name: evil, enabled: false}, {name: 'ok', enabled: true}], toolsets: [{name: evil + 'ts', enabled: true}],
  mcp_servers: [{name: evil + 'mcp', transport: evil + 'transport', enabled: true}], soul: evil + '\n</textarea>' + evil + '\n'})}});
const facts = box('facts').innerHTML;
assert.ok(!facts.includes('<img'), facts);
for (const part of ['&lt;img src=x onerror=alert(1)&gt;', '&amp; &quot;quoted&quot;', '&lt;/div&gt;'])
  assert.ok(facts.includes(part), part);
// the SOUL goes into the textarea as a value, never as markup
assert.equal(editor().value, evil + '\n</textarea>' + evil + '\n');
assert.ok(!box('soul').innerHTML.includes('<img'));
// the diff puts the lines into slots filled with textContent
startEditing(evil + '\n</textarea>' + evil + '\n<script>x</script>');
press('preview');
assert.ok(!box('soul').innerHTML.includes('<img') && !box('soul').innerHTML.includes('<script>'), box('soul').innerHTML);
assert.deepEqual(slotTexts(box('soul')), [evil, '</textarea>' + evil, '<script>x</script>']);
assert.ok(box('soul').querySelectorAll('[data-slot]').every((s) => s.children.length === 0), 'slots hold text, not elements');
// result lines and history rows
confirmTwice();
send({pixelhqSoulSaveResult: {rid: lastRid('pixelhqSoulSave'), state: 'failed', message: evil}});
assert.ok(box('soul').innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;') && !box('soul').innerHTML.includes('<img'));
answerHistory([{...ITEMS[0], firstLine: evil, savedAt: evil}]);
assert.ok(!box('history').innerHTML.includes('<img'));
assert.deepEqual(slotTexts(box('history')), [evil]);
assert.ok(box('history').innerHTML.includes('&lt;img'), 'a bad time string is shown escaped');
// the id of a hostile bot is posted as data, not interpreted
assert.equal(sent('pixelhqProfile')[0].bot, bot.id);
""")


def test_hostile_text_in_a_restored_version_and_in_status_messages(tmp_path):
    run_ui(tmp_path, r"""
const evil = '<script>alert(1)</script>';
open(); answerHistory();
box('history').querySelector('[data-cfg-restore]').onclick();
send({pixelhqSoulHistoryItemResult: {rid: lastRid('pixelhqSoulHistoryItem'), state: 'ready', id: ITEMS[0].id, text: evil + '\r\n' + evil}});
assert.ok(!box('soul').innerHTML.includes('<script>'));
assert.deepEqual(slotTexts(box('soul')).filter((s) => s.includes('script')), [evil, evil]);
assert.ok(!box('soul').innerHTML.includes('\r'));
press('cancel');
box('status').querySelector('[data-cfg-reload]').onclick();
send({pixelhqProfileResult: {rid: lastRid('pixelhqProfile'), state: 'ambiguous', message: evil}});
assert.ok(!box('status').innerHTML.includes('<script>') && box('status').innerHTML.includes('&lt;script&gt;'));
""")


def test_demo_snapshot_has_synthetic_describe_answers_only(tmp_path):
    data = snapshot()
    text = json.dumps(data["demoProfiles"])
    assert set(data["demoProfiles"]) == {b["id"] for b in data["bots"]}
    assert text.count("synthetic demo profile") == len(data["bots"])
    for banned in ("/home/", "@", "http://", "https://"):
        assert banned not in text
    leader = data["demoProfiles"][next(b["id"] for b in data["bots"] if b.get("leader"))]
    assert len(leader["skills"]) > 12 and sum(not s["enabled"] for s in leader["skills"]) > 12, "the demo shows the '+N more' collapse"
    assert any("## Messaging other agents" in p["soul"] for p in data["demoProfiles"].values())
    assert json.dumps(data).count('"demo": true') == 1
