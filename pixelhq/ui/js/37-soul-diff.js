/* ---- SOUL text helpers of the Config section (round 4 §2): pure functions, no DOM, no host. ----
   Line endings are compared and shown as "\n" (the bridge normalises them the same way before it writes). */
const DIFF_CONTEXT = 3;
const DIFF_MAX_LINES = 400;
const DIFF_MAX_CELLS = 2000000;
const SOUL_MAX_BYTES = 64 * 1024;
const SOUL_CONTROL = /[\u0000-\u0008\u000b-\u001f]/;
const SOUL_LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
const MESSAGING_HEADING = /^## Messaging other agents[ \t]*$/m;

const eolNormal = (text) => String(text ?? '').replace(/\r\n?/g, '\n');
const sameSoul = (a, b) => eolNormal(a) === eolNormal(b);
/* The lines of a text; the line break that ends the last line does not start another (empty) line. */
const soulLines = (text) => (eolNormal(text) === '' ? [] : eolNormal(text).replace(/\n$/, '').split('\n'));
const soulLineCount = (text) => soulLines(text).length;
/* Whether the final line break was added or removed is the one difference the line list cannot show. */
function lineBreakNote(oldText, newText) {
  const a = eolNormal(oldText);
  const b = eolNormal(newText);
  if (!a || !b || a.endsWith('\n') === b.endsWith('\n')) {
    return null;
  }
  return { t: '!', s: b.endsWith('\n') ? 'final line break added' : 'final line break removed' };
}

function soulBytes(text) {
  const t = eolNormal(text);
  return typeof TextEncoder === 'function' ? new TextEncoder().encode(t).length : unescape(encodeURIComponent(t)).length;
}

/* '' when the text may be saved, else the message shown inline (same rules as the bridge: 64 KiB after the line-ending
   normalisation, no control characters except tab and line feed, no lone surrogates). */
function soulProblem(text) {
  const t = eolNormal(text);
  if (SOUL_CONTROL.test(t)) {
    return 'The SOUL contains control characters other than tab and line breaks';
  }
  if (SOUL_LONE_SURROGATE.test(t)) {
    return 'The SOUL is not valid Unicode text';
  }
  return t.length > SOUL_MAX_BYTES || soulBytes(t) > SOUL_MAX_BYTES ? 'The SOUL is longer than 64 KiB' : '';
}

/* The Bot Mode messaging section: warn when the loaded text has the heading and the new text lost it. */
const lostMessaging = (base, draft) => MESSAGING_HEADING.test(eolNormal(base)) && !MESSAGING_HEADING.test(eolNormal(draft));

/* Edit script for the lines between the common head and tail: longest common subsequence; deletions come before the
   insertions of the same block. Bigger inputs than DIFF_MAX_CELLS fall back to "all old lines removed, all new added". */
function lcsOps(a, b) {
  const n = a.length;
  const m = b.length;
  if (!n || !m || n * m > DIFF_MAX_CELLS) {
    return { coarse: n * m > DIFF_MAX_CELLS, ops: a.map((s) => ({ t: '-', s })).concat(b.map((s) => ({ t: '+', s }))) };
  }
  const w = m + 1;
  const dp = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = a[i] === b[j] ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
    }
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ t: ' ', s: a[i++] });
      j++;
    } else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) {
      ops.push({ t: '-', s: a[i++] });
    } else {
      ops.push({ t: '+', s: b[j++] });
    }
  }
  while (i < n) {
    ops.push({ t: '-', s: a[i++] });
  }
  while (j < m) {
    ops.push({ t: '+', s: b[j++] });
  }
  return { coarse: false, ops };
}

/* Unchanged lines further than DIFF_CONTEXT from a change become one {t:'~', n} marker. */
function collapseContext(ops) {
  const near = new Uint8Array(ops.length);
  ops.forEach((op, k) => {
    if (op.t !== ' ') {
      for (let x = Math.max(0, k - DIFF_CONTEXT); x <= Math.min(ops.length - 1, k + DIFF_CONTEXT); x++) {
        near[x] = 1;
      }
    }
  });
  const rows = [];
  ops.forEach((op, k) => {
    if (near[k]) {
      rows.push(op);
    } else if (rows.length && rows[rows.length - 1].t === '~') {
      rows[rows.length - 1].n++;
    } else {
      rows.push({ t: '~', n: 1 });
    }
  });
  return rows;
}

/* At most DIFF_MAX_LINES lines (markers do not count); `truncated` is the number of changed lines that are not shown. */
function capRows(rows) {
  const out = [];
  let shown = 0;
  for (let k = 0; k < rows.length; k++) {
    if (rows[k].t === '~') {
      out.push(rows[k]);
    } else if (shown < DIFF_MAX_LINES) {
      out.push(rows[k]);
      shown++;
    } else {
      return { rows: out, truncated: rows.slice(k).filter((r) => r.t === '+' || r.t === '-').length };
    }
  }
  return { rows: out, truncated: 0 };
}

/* Line diff old -> new: {identical, added, removed, rows, truncated, coarse}; rows are {t:' '|'+'|'-', s} and {t:'~', n}. */
function soulDiff(oldText, newText) {
  const a = soulLines(oldText);
  const b = soulLines(newText);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) {
    head++;
  }
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) {
    tail++;
  }
  const mid = lcsOps(a.slice(head, a.length - tail), b.slice(head, b.length - tail));
  const same = (s) => ({ t: ' ', s });
  const ops = a.slice(0, head).map(same).concat(mid.ops, a.slice(a.length - tail).map(same));
  const added = ops.filter((op) => op.t === '+').length;
  const removed = ops.filter((op) => op.t === '-').length;
  const note = lineBreakNote(oldText, newText);
  if (!added && !removed) {
    return note
      ? { identical: false, added, removed, rows: [note], truncated: 0, coarse: false }
      : { identical: true, added, removed, rows: [], truncated: 0, coarse: false };
  }
  const capped = capRows(collapseContext(ops));
  const rows = note ? capped.rows.concat(note) : capped.rows;
  return { identical: false, added, removed, rows, truncated: capped.truncated, coarse: mid.coarse };
}

/* The text of every line goes through `put` (a slot filled with textContent later), never through innerHTML. */
function diffHtml(diff, put) {
  if (diff.identical) {
    return '<div class="diff"><div class="dl skip">No changes</div></div>';
  }
  const mark = { '+': ['add', '+'], '-': ['del', '-'], ' ': ['', '\u00a0'] };
  const rows = diff.rows.map((r) => {
    if (r.t === '!') {
      return '<div class="dl skip" data-diff-linebreak>' + esc(r.s) + '</div>';
    }
    if (r.t === '~') {
      return '<div class="dl skip">… ' + Number(r.n) + ' unchanged line' + (r.n === 1 ? '' : 's') + '</div>';
    }
    return '<div class="dl ' + mark[r.t][0] + '"><span class="dm">' + mark[r.t][1] + '</span>' + put(r.s) + '</div>';
  });
  if (diff.truncated) {
    rows.push('<div class="dl skip" data-diff-truncated>diff truncated: ' + Number(diff.truncated) + ' more changed lines not shown</div>');
  }
  return '<div class="diff" tabindex="0" role="region" aria-label="SOUL changes">' + rows.join('') + '</div>';
}
