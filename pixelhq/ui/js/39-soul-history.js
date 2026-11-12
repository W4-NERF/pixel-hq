/* ---- SOUL history of the Config section (round 4 §4): the previous versions of this bot's SOUL, newest first.
   Preview fetches one version and opens it as a restore draft (diff current -> chosen, same armed confirmation as a save);
   Confirm restore runs the ordinary save protocol, so the replaced SOUL is backed up like any other. The list and the item
   come from the bridge (pixelhqSoulHistory / pixelhqSoulHistoryItem). ---- */
/* Version id rule, one copy per language: here, VERSION_ID_RE in desktop/plugin.js and FILE_RE in pixelhq/soul_history.py. */
const CONF_VERSION_ID = /^\d{8}T\d{6}Z-[a-z0-9]{8,32}\.md$/;
const CONF_HISTORY_MAX = 50;

function cleanHistory(items) {
  return (Array.isArray(items) ? items : [])
    .filter((it) => confIsObject(it) && typeof it.id === 'string' && CONF_VERSION_ID.test(it.id))
    .slice(0, CONF_HISTORY_MAX)
    .map((it) => ({
      id: it.id, savedAt: String(it.savedAt ?? '').slice(0, 32), bytes: Number.isInteger(it.bytes) ? it.bytes : 0,
      firstLine: String(it.firstLine ?? '').slice(0, 80)
    }));                                                 // the backend's order (newest first by write time) is kept (R4-D5)
}

function confTime(iso) {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? String(iso).slice(0, 32) : clock(ms / 1000);
}

function loadHistory(st) {
  if (!confHosted()) {
    return;
  }
  const key = 'hist|' + st.key;
  if (confTrips.busy(key)) {
    st.hist.again = true;
    return;
  }
  const rid = newRid();
  st.hist.load = 'loading';
  st.hist.message = '';
  roundTrip(
    confTrips,
    key,
    { cfg: st.key, rid },
    { pixelhqSoulHistory: { rid, bot: st.bot, remote: st.remote } },
    (r) => onHistoryResult({ rid, state: 'error', message: r.message }),
    () => refreshRegion(st, 'history', true)
  );
}

function onHistoryResult(raw) {
  const r = confResult(raw, CONF_STATES);
  const info = r && confTake(confTrips, 'hist', r);
  const st = info && confStates.get(info.cfg);
  if (!st) {
    return;
  }
  st.hist.load = r.state;
  st.hist.message = r.message;
  st.hist.items = r.state === 'ready' ? cleanHistory(r.items) : [];
  refreshRegion(st, 'history', true);
  if (st.hist.again) {
    st.hist.again = false;
    loadHistory(st);
  }
}

function previewVersion(st, id) {
  const key = 'item|' + st.key;
  if (!confHosted() || !confShowsData(st) || st.draft || confTrips.busy(key) || confSaveTrips.busy('save|' + st.key)) {
    return;
  }
  if (!st.hist.items.some((it) => it.id === id)) {
    return;
  }
  const rid = newRid();
  roundTrip(
    confTrips,
    key,
    { cfg: st.key, rid, id },
    { pixelhqSoulHistoryItem: { rid, bot: st.bot, remote: st.remote, id } },
    (r) => onHistoryItemResult({ rid, state: 'error', message: r.message }),
    () => refreshRegion(st, 'history', true)
  );
}

/* A version arrived: it becomes a restore draft in the preview. A late answer for a panel that has a draft meanwhile is dropped. */
function onHistoryItemResult(raw) {
  const r = confResult(raw, CONF_STATES);
  const info = r && confTake(confTrips, 'item', r);
  const st = info && confStates.get(info.cfg);
  if (!st) {
    return;
  }
  if (r.state === 'ready' && typeof r.text === 'string' && r.id === info.id && st.data && !st.draft) {
    const item = st.hist.items.find((it) => it.id === info.id);
    confTrips.forget('item|' + st.key);
    confSaveTrips.forget('save|' + st.key);
    dropNotes(st);
    st.draft = {
      kind: 'restore', mode: 'preview', text: eolNormal(r.text), base: eolNormal(st.data.soul), baseHash: st.data.soulHash,
      rid: null, note: '', label: item ? confTime(item.savedAt) : info.id
    };
    refreshDraftUi(st);
    return;
  }
  if (r.state === 'ready') {
    confTrips.forget('item|' + st.key);
  }
  refreshRegion(st, 'history', true);
}

/* '' when the list is loaded or not asked for yet; a timed-out request is shown as an error. */
function historyProblem(st) {
  const key = 'hist|' + st.key;
  const h = st.hist;
  if (h.load === 'loading' && !confTrips.busy(key)) {
    return { state: 'error', message: (confTrips.result(key) || {}).message };
  }
  return ['idle', 'ready', 'loading'].includes(h.load) ? null : { state: h.load, message: h.message };
}

function versionRows(st, slots, lock) {
  return st.hist.items.map((it) =>
    '<div class="hrow" data-cfg-version="' + esc(it.id) + '"><span class="mut">' + esc(confTime(it.savedAt)) + '</span><span class="mut">' +
      it.bytes + ' B</span><span class="hfirst">' + slots.put(it.firstLine || '(empty first line)') +
      '</span><button type="button" data-cfg-restore="' + esc(it.id) + '"' + (lock ? ' disabled' : '') + '>Preview</button></div>'
  ).join('');
}

function historyHtml(st, slots) {
  const h = st.hist;
  const picking = confTrips.busy('item|' + st.key);
  const lock = !!st.draft || picking || confSaveTrips.busy('save|' + st.key);
  const problem = historyProblem(st);
  const item = confTrips.result('item|' + st.key);
  let html = '<div class="lab">HISTORY · newest first</div>';
  if (confTrips.busy('hist|' + st.key)) {
    html += '<div class="res" role="status">Loading history …</div>';
  } else if (problem) {
    html += '<div class="res ' + (problem.state === 'error' ? 'bad' : 'warn') + '" role="status" data-cfg-history-state="' +
      esc(problem.state) + '">' + esc(confMsg(problem.message) || CONF_TEXT[problem.state] || CONF_TEXT.error) + '</div>';
  } else if (h.load === 'ready') {
    html += h.items.length ? versionRows(st, slots, lock) : '<div class="mut hint">No earlier versions yet.</div>';
  }
  if (picking) {
    html += '<div class="res" role="status">Loading version …</div>';
  } else if (item && (item.ok === false || item.state !== 'ready')) {
    html += '<div class="res bad" role="status">' + esc(confMsg(item.message) || CONF_TEXT.error) + '</div>';
  }
  return html;
}

function drawHistory(box, st) {
  const v = confView(st);
  const slots = textSlots();
  box.innerHTML = v.state === 'demo'
    ? '<div class="lab">HISTORY</div><div class="mut hint">The version history is disabled on the standalone page.</div>'
    : v.state === 'ready' ? historyHtml(st, slots) : '';
  slots.fill(box);
  box.querySelectorAll('[data-cfg-restore]').forEach((btn) => (btn.onclick = () => previewVersion(st, btn.dataset.cfgRestore)));
}
