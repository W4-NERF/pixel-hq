"""Pure SOUL helpers of the Config section (R4-03, `pixelhq/ui/js/37-soul-diff.js`): line diff, validation, messaging warning.

The page script runs in the plain-Node DOM harness; the functions under test never touch the DOM.
"""
import os
import subprocess
from pathlib import Path

from pixelhq import page

ROOT = Path(__file__).resolve().parents[1]


def run_js(tmp_path, probe):
    script = (ROOT / "tests" / "ui_dom.cjs").read_text(encoding="utf-8") + page.bundle_js()
    script += "\n" + probe + "\nconsole.log('soul diff: ok');\n"
    path = tmp_path / "soul-diff.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ACTIONS": "", "IFRAME": "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


PRE = """
const kinds = (diff) => diff.rows.map((r) => r.t === '~' ? '~' + r.n : r.t + r.s);
const lines = (n, prefix = 'L') => Array.from({length: n}, (_, i) => prefix + (i + 1));
"""


def test_insert_delete_and_replace(tmp_path):
    run_js(tmp_path, PRE + """
let d = soulDiff('a\\nc', 'a\\nb\\nc');
assert.deepEqual(kinds(d), [' a', '+b', ' c']);
assert.deepEqual([d.added, d.removed, d.identical], [1, 0, false]);
d = soulDiff('a\\nb\\nc', 'a\\nc');
assert.deepEqual(kinds(d), [' a', '-b', ' c']);
assert.deepEqual([d.added, d.removed], [0, 1]);
d = soulDiff('a\\nb\\nc', 'a\\nX\\nc');
assert.deepEqual(kinds(d), [' a', '-b', '+X', ' c'], 'a replaced line is shown as removed, then added');
assert.deepEqual([d.added, d.removed], [1, 1]);
d = soulDiff('a\\nb\\nc\\nd', 'a\\nX\\nY\\nd');
assert.deepEqual(kinds(d), [' a', '-b', '-c', '+X', '+Y', ' d']);
d = soulDiff('one\\ntwo', 'zero\\none\\ntwo\\nthree');
assert.deepEqual(kinds(d), ['+zero', ' one', ' two', '+three']);
""")


def test_empty_and_identical_texts(tmp_path):
    run_js(tmp_path, PRE + """
let d = soulDiff('', 'a\\nb');
assert.deepEqual(kinds(d), ['+a', '+b']);
assert.deepEqual([d.added, d.removed, d.identical], [2, 0, false]);
d = soulDiff('a\\nb', '');
assert.deepEqual(kinds(d), ['-a', '-b']);
assert.deepEqual([d.added, d.removed], [0, 2]);
d = soulDiff('', '');
assert.deepEqual([d.identical, d.rows.length, d.added, d.removed, d.truncated], [true, 0, 0, 0, 0]);
d = soulDiff('same\\ntext\\n', 'same\\ntext\\n');
assert.equal(d.identical, true);
assert.ok(diffHtml(d, (s) => s).includes('No changes'));
// only the final line break differs: the line list is the same, the note says what changed
d = soulDiff('a', 'a\\n');
assert.deepEqual(kinds(d), ['!final line break added']);
assert.deepEqual([d.identical, d.added, d.removed], [false, 0, 0]);
assert.ok(diffHtml(d, (s) => s).includes('final line break added'));
assert.deepEqual(kinds(soulDiff('a\\n', 'a')), ['!final line break removed']);
assert.deepEqual(kinds(soulDiff('a\\nb', 'a\\nc\\n')), [' a', '-b', '+c', '!final line break added']);
assert.equal(soulDiff('a\\n', '').rows.some((r) => r.t === '!'), false, 'a missing text has no line break to compare');
assert.deepEqual(kinds(soulDiff('a\\n', 'a\\n\\n')), [' a', '+']);
d = soulDiff(null, undefined);
assert.equal(d.identical, true);
// a final line break does not start another line
assert.deepEqual(soulLines('a\\nb\\n'), ['a', 'b']);
assert.deepEqual(soulLines('\\n'), ['']);
assert.deepEqual(soulLines(''), []);
assert.equal(soulLineCount('a\\nb\\n'), 2);
assert.equal(soulLineCount('a\\nb'), 2);
assert.equal(soulLineCount('a\\n\\n'), 2);
""")


def test_crlf_and_lone_cr_are_line_breaks_like_lf(tmp_path):
    run_js(tmp_path, PRE + """
assert.equal(soulDiff('a\\r\\nb\\r\\n', 'a\\nb\\n').identical, true);
assert.equal(soulDiff('a\\rb\\r', 'a\\nb\\n').identical, true);
assert.equal(sameSoul('a\\r\\nb', 'a\\nb'), true);
const d = soulDiff('a\\r\\nb\\r\\nc', 'a\\nX\\r\\nc');
assert.deepEqual(kinds(d), [' a', '-b', '+X', ' c']);
assert.ok(d.rows.every((r) => r.t === '~' || !r.s.includes('\\r')), 'no carriage return survives in a row');
assert.deepEqual(soulLines('a\\r\\nb'), ['a', 'b']);
""")


def test_unchanged_context_is_collapsed_to_three_lines_around_changes(tmp_path):
    run_js(tmp_path, PRE + """
const old = lines(20).join('\\n');
let d = soulDiff(old, lines(20).map((l) => l === 'L10' ? 'X' : l).join('\\n'));
assert.deepEqual(kinds(d), ['~6', ' L7', ' L8', ' L9', '-L10', '+X', ' L11', ' L12', ' L13', '~7']);
// change at the start and at the end: a marker on one side only
d = soulDiff(old, ['X', ...lines(20).slice(1)].join('\\n'));
assert.deepEqual(kinds(d), ['-L1', '+X', ' L2', ' L3', ' L4', '~16']);
d = soulDiff(old, [...lines(19), 'X'].join('\\n'));
assert.deepEqual(kinds(d), ['~16', ' L17', ' L18', ' L19', '-L20', '+X']);
// two changes with a gap of six unchanged lines share their context: no marker between them
const two = lines(20).map((l) => l === 'L5' || l === 'L12' ? l + '!' : l).join('\\n');
d = soulDiff(old, two);
assert.ok(!kinds(d).slice(1, -1).some((k) => k[0] === '~'), kinds(d).join('|'));
// a gap of seven lines collapses to a marker of one line
const seven = lines(20).map((l) => l === 'L5' || l === 'L13' ? l + '!' : l).join('\\n');
assert.ok(kinds(soulDiff(old, seven)).includes('~1'));
const html = diffHtml(soulDiff(old, two.replace('L5!', 'L5')), (s) => s);
assert.ok(html.includes('… 1 unchanged line</div>') || html.includes('unchanged lines</div>'));
""")


def test_cap_of_400_lines_with_truncation_note(tmp_path):
    run_js(tmp_path, PRE + """
let d = soulDiff('', lines(500).join('\\n'));
assert.equal(d.rows.length, 400);
assert.deepEqual([d.added, d.removed, d.truncated], [500, 0, 100]);
let html = diffHtml(d, (s) => s);
assert.ok(html.includes('data-diff-truncated'));
assert.ok(html.includes('diff truncated: 100 more changed lines not shown'));
assert.equal((html.match(/class="dl add"/g) || []).length, 400);
// exactly 400 changed lines: nothing is cut off
d = soulDiff('', lines(400).join('\\n'));
assert.deepEqual([d.rows.length, d.truncated], [400, 0]);
assert.ok(!diffHtml(d, (s) => s).includes('truncated'));
// collapse markers do not count against the cap
const old = lines(1000).join('\\n');
d = soulDiff(old, lines(1000).map((l, i) => i % 50 === 0 ? l + '!' : l).join('\\n'));
assert.equal(d.rows.filter((r) => r.t !== '~').length <= 400, true);
assert.equal(d.added, 20);
assert.equal(d.truncated > 0 || d.rows.some((r) => r.t === '~'), true);
// every row beyond the cap is a changed line or context: the count of hidden changed lines is exact
d = soulDiff(lines(300).join('\\n'), lines(300).map((l) => l + 'x').join('\\n'));
assert.deepEqual([d.added, d.removed, d.truncated], [300, 300, 200]);
assert.equal(d.rows.length, 400);
""")


def test_huge_inputs_fall_back_to_a_replaced_block_without_hanging(tmp_path):
    run_js(tmp_path, PRE + """
const a = lines(1500, 'old').join('\\n'), b = lines(1500, 'new').join('\\n');
const started = Date.now();
const d = soulDiff(a, b);
assert.ok(Date.now() - started < 3000, 'no quadratic blow-up');
assert.equal(d.coarse, true);
assert.deepEqual([d.added, d.removed], [1500, 1500]);
assert.equal(d.rows.length, 400);
// common head and tail are still matched before the fallback
const e = soulDiff('head\\n' + a + '\\ntail', 'head\\n' + b + '\\ntail');
assert.equal(e.rows[0].t, ' ');
assert.equal(e.coarse, true);
// a small change in a big text is not coarse
assert.equal(soulDiff(a, a.replace('old750', 'x')).coarse, false);
""")


def test_edit_script_is_a_minimal_valid_transformation(tmp_path):
    run_js(tmp_path, """
let seed = 12345;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
const lcs = (a, b) => {
  const t = Array.from({length: a.length + 1}, () => new Array(b.length + 1).fill(0));
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    t[i][j] = a[i - 1] === b[j - 1] ? t[i - 1][j - 1] + 1 : Math.max(t[i - 1][j], t[i][j - 1]);
  return t[a.length][b.length];
};
for (let round = 0; round < 300; round++) {
  const a = Array.from({length: rnd(9)}, () => 'abc'[rnd(3)]);
  const b = Array.from({length: rnd(9)}, () => 'abc'[rnd(3)]);
  const {ops} = lcsOps(a, b);
  assert.deepEqual(ops.filter((o) => o.t !== '+').map((o) => o.s), a, 'old side ' + a + ' / ' + b);
  assert.deepEqual(ops.filter((o) => o.t !== '-').map((o) => o.s), b, 'new side ' + a + ' / ' + b);
  assert.equal(ops.filter((o) => o.t === ' ').length, lcs(a, b), 'minimal edit ' + a + ' / ' + b);
  const d = soulDiff(a.join('\\n'), b.join('\\n'));
  assert.equal(d.added, b.length - lcs(a, b) + (a.length === 0 && b.length === 0 ? 0 : 0));
}
""")


def test_diff_html_puts_text_into_slots_never_into_markup(tmp_path):
    run_js(tmp_path, """
const slots = textSlots();
const d = soulDiff('keep\\nold <b>line</b>', 'keep\\nnew <img src=x onerror=alert(1)>');
const html = diffHtml(d, slots.put);
assert.ok(!html.includes('<b>') && !html.includes('<img') && !html.includes('onerror'), html);
const host = document.getElementById('hostile');
host.innerHTML = html; slots.fill(host);
assert.deepEqual(host.querySelectorAll('[data-slot]').map((s) => s.textContent),
  ['keep', 'old <b>line</b>', 'new <img src=x onerror=alert(1)>']);
assert.equal(host.querySelectorAll('.add').length, 1);
assert.equal(host.querySelectorAll('.del').length, 1);
assert.equal(host.querySelector('.diff').attrs.role, 'region');
""")


def test_soul_problem_matches_the_bridge_limits(tmp_path):
    run_js(tmp_path, """
assert.equal(soulProblem(''), '');
assert.equal(soulProblem('plain\\ttext\\nwith\\r\\nbreaks'), '');
for (const bad of ['a\\u0000b', 'a\\u0007b', 'a\\u001bb', 'a\\u000bb', 'a\\u000cb'])
  assert.equal(soulProblem(bad), 'The SOUL contains control characters other than tab and line breaks', JSON.stringify(bad));
assert.equal(soulProblem('lone \\ud800 surrogate'), 'The SOUL is not valid Unicode text');
assert.equal(soulProblem('x'.repeat(65536)), '');
assert.equal(soulProblem('x'.repeat(65537)), 'The SOUL is longer than 64 KiB');
// bytes, not characters: 3-byte characters
assert.equal(soulProblem('\\u20ac'.repeat(21845)), '');
assert.equal(soulProblem('\\u20ac'.repeat(21846)), 'The SOUL is longer than 64 KiB');
// CRLF counts as one byte per break, like the normalised text the bridge writes
assert.equal(soulProblem('a\\r\\n'.repeat(21845)), '');
assert.equal(soulBytes('a\\r\\nb'), 3);
""")


def test_messaging_section_warning_rule(tmp_path):
    run_js(tmp_path, """
const H = '## Messaging other agents';
const base = 'Intro\\n\\n' + H + '\\n\\nAsk politely.\\n';
assert.equal(lostMessaging(base, 'Intro\\n'), true);
assert.equal(lostMessaging(base, base + 'More\\n'), false);
assert.equal(lostMessaging('Intro\\n', 'Intro\\n' + H + '\\n'), false, 'adding the section is not a loss');
assert.equal(lostMessaging('Intro\\n', 'Other\\n'), false);
assert.equal(lostMessaging(base, 'Intro\\n\\n### Messaging other agents\\n'), true, 'another heading level is not the section');
assert.equal(lostMessaging(base, 'Intro ' + H + '\\n'), true, 'the heading must start a line');
assert.equal(lostMessaging(base.replace(/\\n/g, '\\r\\n'), 'Intro\\r\\n'), true);
assert.equal(lostMessaging(base, base.replace(/\\n/g, '\\r\\n')), false);
assert.equal(lostMessaging(H + '   \\nx', H + '\\t\\ny\\n'), false, 'trailing blanks after the heading are allowed');
assert.equal(lostMessaging(H + '\\nx', H + ' now\\ny\\n'), true, 'other words after the heading make it a different heading');
""")
