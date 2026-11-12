/* ---- blocked cards ---- */
const CAT = {
  you: ['Waiting for you', 'needs your decision, answer, approval or sign-off'],
  technical: ['Technically stuck', 'worker gave up, timed out or lacks a capability'],
  stale: ['Stale', 'older than the stale threshold, no clear reason'],
  unknown: ['No reason', 'blocked without a recorded reason'],
  upstream: ['Waiting upstream', 'resolves once its parent cards are done']
};
let bcat = 'all';
let bboard = 'all';
let bstale = false;
let bopen = new Set();
const ALAB = { answer: 'Answer & unblock', retry: 'Retry', comment: 'Comment', archive: 'Archive' };
const CONFIRM = new Set(['answer', 'retry', 'archive']);
const drafts = {};
const lastRes = [];
const actionTrips = hostTrips(TRIP_MS.action, () => {
  pushRes(false, TIMEOUT_TEXT);
  blk();
});
const triageTrips = hostTrips(TRIP_MS.other, () => {
  pushRes(false, TIMEOUT_TEXT);
  blk();
});
const triageBusy = () => triageTrips.busy('triage');
let triageSel = [];

function pushRes(ok, text) {
  lastRes.unshift({ ok, text, t: hm() });
  lastRes.length = Math.min(lastRes.length, 5);
}

const knownActions = (b) =>
  (Array.isArray(b.actions) ? b.actions : []).filter((x) => typeof x === 'string' && Object.hasOwn(ALAB, x));

function actionsHtml(b, key) {
  if (!EMBED) {
    return '<div class="lab">ACTIONS</div><div class="mut">available inside the Hermes desktop app only</div>';
  }
  const acts = knownActions(b);
  let h = '<div class="lab">ACTIONS</div>';
  if (acts.includes('answer') || acts.includes('comment')) {
    h += '<textarea class="ta" data-ta="' + esc(key) + '" rows="3" placeholder="' +
      (acts.includes('answer') ? 'answer / decision for the bot …' : 'comment …') + '"></textarea>';
  }
  h += '<div class="acts">' +
    acts.map((x) =>
      '<button data-act="' + esc(x) + '" data-key="' + esc(key) + '"' + (actionTrips.busy(key) ? ' disabled' : '') +
        '>' + esc(ALAB[x]) + '</button>'
    ).join('') +
    '</div>';
  if (b.remote && (acts.includes('answer') || acts.includes('retry'))) {
    h += '<div class="mut" style="font-size:10px">This bot runs on a remote host – ' +
      'the local dispatcher will not start it after unblocking.</div>';
  }
  if (actionTrips.busy(key)) {
    h += '<div class="res">running …</div>';
  }
  const r = actionTrips.result(key);
  if (r) {
    h += '<div class="res ' + (r.ok ? 'ok' : 'bad') + '">' + esc(r.message || r.error) + '</div>';
  }
  return h;
}

function bindActions() {
  document.querySelectorAll('[data-ta]').forEach((t) => {
    t.value = drafts[t.dataset.ta] || '';
    t.oninput = () => {
      drafts[t.dataset.ta] = t.value;
    };
  });
  document.querySelectorAll('[data-act]').forEach((btn) =>
    (btn.onclick = () => {
      const key = btn.dataset.key;
      const act = btn.dataset.act;
      if (actionTrips.busy(key) || !Object.hasOwn(ALAB, act)) {
        return;
      }
      const i = key.indexOf('/');
      const board = key.slice(0, i);
      const id = key.slice(i + 1);
      const text = (drafts[key] || '').trim();
      if ((act === 'answer' || act === 'comment') && text.length < 3) {
        actionTrips.put(key, { ok: false, error: 'Please enter some text first (at least 3 characters).' });
        blk();
        return;
      }
      const send = () =>
        roundTrip(
          actionTrips,
          key,
          undefined,
          { pixelhqAction: { board, id, action: act, text } },
          (r) => onActionResult({ ...r, board, id }),
          blk
        );
      if (CONFIRM.has(act)) {
        armedButton(btn, () => ALAB[act], 'Confirm: ' + ALAB[act] + '?', send);
      } else {
        send();
      }
    })
  );
}

function onActionResult(r) {
  const key = (r.board || '') + '/' + (r.id || '');
  if (!actionTrips.finish(key, r)) {
    actionTrips.put(key, r);
  }
  if (r.ok) {
    delete drafts[key];
  }
  pushRes(!!r.ok, r.message || r.error || '?');
  blk();
}

function blk() {
  const all = DATA.blockers || [];
  document.getElementById('blktab').textContent = 'Blocked (' + all.length + ')';
  const cnt = (k) => all.filter((b) => k === 'all' || b.cat === k).length;
  document.getElementById('bcats').innerHTML = ['all', ...Object.keys(CAT)].map((k) =>
    '<button class="chip' + (bcat === k ? ' on' : '') + '" data-bc="' + k + '" title="' +
      (k === 'all' ? '' : esc(CAT[k][1])) + '">' + (k === 'all' ? 'All' : esc(CAT[k][0])) + '<span class="n">' +
      cnt(k) + '</span></button>'
  ).join('');
  const boards = [...new Set(all.map((b) => b.board))].sort();
  document.getElementById('bboards').innerHTML = ['all', ...boards].map((k) =>
    '<button class="' + (bboard === k ? 'on' : '') + '" data-bb="' + esc(k) + '">' + (k === 'all' ? 'all' : esc(k)) +
      ' <span class="mut">' + all.filter((b) => k === 'all' || b.board === k).length + '</span></button>'
  ).join('');
  const sb = document.getElementById('bstale');
  sb.classList.toggle('on', bstale);
  sb.textContent = 'older than ' + CFG().staleDays + ' d only';
  const rows = all.filter((b) =>
    (bcat === 'all' || b.cat === bcat) && (bboard === 'all' || b.board === bboard) && (!bstale || b.stale)
  );
  triageSel = rows.filter((b) => b.cat !== 'upstream').map((b) => b.board + '/' + b.id);
  const tb = document.getElementById('btriage');
  tb.style.display = EMBED ? '' : 'none';
  tb.disabled = !triageSel.length || triageBusy();
  if (tb.dataset.armed !== '1') {
    tb.textContent = triageLabel();
  }
  tb.title = 'Opens a new chat with ' + CFG().orchestrator +
    ' that reviews the cards in the current selection (without "waiting upstream") ' +
    'and proposes one decision package. Nothing is changed without your go.';
  renderUnlessFocused(document.getElementById('blist'), blockList);
  document.querySelectorAll('[data-bc]').forEach((x) =>
    (x.onclick = () => {
      bcat = x.dataset.bc;
      blk();
    })
  );
  document.querySelectorAll('[data-bb]').forEach((x) =>
    (x.onclick = () => {
      bboard = x.dataset.bb;
      blk();
    })
  );
  document.getElementById('bres').innerHTML = lastRes.map((x) =>
    '<div class="res ' + (x.ok ? 'ok' : 'bad') + '"><span class="mut">' + x.t + '</span> ' + esc(x.text) + '</div>'
  ).join('');
}

const triageLabel = () =>
  triageBusy() ? 'Starting triage …' : 'Triage run → ' + CFG().orchestrator + ' (' + triageSel.length + ' cards)';

/* The card list holds the answer/comment text areas, so it is the part that waits for the focus to leave (D8). */
function blockList() {
  const rows = DATA.blockers || [];
  const shown = rows.filter((b) =>
    (bcat === 'all' || b.cat === bcat) && (bboard === 'all' || b.board === bboard) && (!bstale || b.stale)
  );
  document.getElementById('blist').innerHTML = shown.map((b) => {
    const bot = DATA.bots.find((x) => x.id === b.assignee) || { id: b.assignee, color: palette().fallback, zone: '' };
    const key = b.board + '/' + b.id;
    const par = b.openParents.length
      ? '<div class="lab">OPEN UPSTREAM CARDS</div>' +
        b.openParents.map((p) => '<div>' + esc(p.status) + ' · ' + esc(p.id) + ' ' + esc(p.title) + '</div>').join('')
      : '';
    const cm = b.comment
      ? '<div class="lab">LAST COMMENT (' + esc(b.comment.author) + ', ' + clock(b.comment.ts) + ')</div><pre>' +
        esc(b.comment.text) + '</pre>'
      : '';
    return '<div class="bi c-' + esc(b.cat) + (bopen.has(key) ? ' open' : '') + '" data-k="' + esc(key) +
      '"><div class="bh"><span><span class="ctag">' + esc(CAT[b.cat][0]) + '</span></span><span class="t" title="' +
      esc(b.title) + '">' + esc(b.title) + '</span>' +
      '<span class="who"><span style="position:relative;display:inline-block">' + sprite(bot, 2) + '</span>' +
      esc(b.assignee) + '</span><span class="' + (b.stale ? 'old' : 'mut') +
      '" style="font-size:11px;text-align:right">' + Number(b.ageDays) + ' d</span></div>' +
      '<div class="br"><span class="mut">' + esc(b.board) + ' · ' + esc(b.id) + (b.kind ? ' · ' + esc(b.kind) : '') +
      ' —</span> ' + (esc(b.reason) || '<span class="mut">no reason recorded</span>') + '</div>' + '<div class="bx">' +
      par + cm + (b.body ? '<div class="lab">TASK (EXCERPT)</div><pre>' + esc(b.body) + '</pre>' : '') +
      actionsHtml(b, key) + '</div></div>';
  }).join('') ||
    '<div class="mut">no cards in this selection</div>';
  document.querySelectorAll('.bi .bh').forEach((h) =>
    (h.onclick = () => {
      const k = h.parentNode.dataset.k;
      bopen.has(k) ? bopen.delete(k) : bopen.add(k);
      h.parentNode.classList.toggle('open');
    })
  );
  bindActions();
  if (DATA.boardErrors && DATA.boardErrors.length) {
    document.getElementById('blist').insertAdjacentHTML(
      'afterbegin',
      '<div class="note" style="color:var(--amber)">Not readable: ' + DATA.boardErrors.map(esc).join(', ') + '</div>'
    );
  }
}

document.getElementById('bstale').onclick = () => {
  bstale = !bstale;
  blk();
};
document.getElementById('btriage').onclick = () => {
  const tb = document.getElementById('btriage');
  if (!triageSel.length || triageBusy()) {
    return;
  }
  armedButton(tb, triageLabel, 'Confirm: start triage for ' + triageSel.length + ' cards?', () =>
    roundTrip(
      triageTrips,
      'triage',
      undefined,
      { pixelhqTriage: { keys: triageSel.slice(0, 80), filter: { category: bcat, board: bboard, stale: bstale } } },
      (r) => {
        triageTrips.finish('triage', r);
        pushRes(!!r.ok, r.message);
        blk();
      },
      blk
    )
  );
};
