/* ---- Config section of the character card (round 4 §2): state per bot, read-only profile facts, load and reload.
   The SOUL editor is in 38-soul-editor.js, the version history in 39-soul-history.js. The data comes from the host bridge
   (desktop/plugin.js: pixelhqProfile -> pixelhqProfileResult); nothing is requested before the section is opened.
   Rendering (D8/D16): the card is redrawn by every snapshot, so the section keeps its state in `confStates` and, while a draft
   exists, the very same element is moved into the new card (heldConfig/mountConfig). The textarea is never redrawn under the
   cursor and never replaced by a refresh while a draft exists. ---- */
const CONF_LIST_MAX = 12;
const CONF_STATES = ['ready', 'unreachable', 'ambiguous', 'unsupported', 'error'];
const CONF_TEXT = {
  unreachable: 'Not reachable from this Desktop',
  ambiguous: 'More than one Desktop connection offers this bot; nothing was called',
  unsupported: 'This Hermes version has no profile editor API',
  error: 'The profile could not be read'
};
const CONF_HINT = 'Change model, skills and toolsets in Hermes (Bot Mode → Edit)';
const CONF_KEPT = 'Current version loaded — your draft is kept';
const CONF_MOVED_MAX = 20;
const confMoved = new Map();
const confStates = new Map();
const confTrips = hostTrips(TRIP_MS.other, (key, info) => refreshConfig(confStates.get(info.cfg)));
const confSaveTrips = hostTrips(TRIP_MS.action, (key, info) => refreshConfig(confStates.get(info.cfg)));
const confHosted = () => window.parent !== window;
const confKeyOf = (b) => (b.remote === true ? 'remote/' : 'local/') + b.id;
const confMsg = (m) => String(m ?? '').slice(0, 200);
const confIsObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

function confState(b) {
  const key = confKeyOf(b);
  if (!confStates.has(key)) {
    confStates.set(key, {
      key, bot: b.id, remote: b.remote === true, open: false, load: 'idle', message: '', data: null, more: {},
      draft: null, hist: { load: 'idle', items: [], message: '' }, el: null, kept: false, late: ''
    });
  }
  return confStates.get(key);
}

/* Text that comes from the SOUL is put into the page through slots: the markup holds an empty element, textContent fills it. */
function textSlots() {
  const list = [];
  return {
    put(text) {
      list.push(String(text));
      return '<span data-slot="' + (list.length - 1) + '"></span>';
    },
    fill(root) {
      root.querySelectorAll('[data-slot]').forEach((s) => {
        s.textContent = list[Number(s.dataset.slot)];
      });
    }
  };
}

function confList(v) {
  return (Array.isArray(v) ? v : []).slice(0, 2000).filter(confIsObject).map((e) => ({
    name: String(e.name ?? '').slice(0, 128), enabled: e.enabled !== false, transport: String(e.transport ?? '').slice(0, 32)
  }));
}

/* The bridge already bounds the answer; the page still copes with anything: no usable SOUL text or hash -> null. */
function cleanProfile(d) {
  if (!confIsObject(d) || typeof d.soul !== 'string' || !/^[0-9a-f]{64}$/.test(d.soulHash)) {
    return null;
  }
  const model = confIsObject(d.model) ? d.model : {};
  return {
    name: String(d.name ?? '').slice(0, 64), description: String(d.description ?? '').slice(0, 2000), soul: d.soul,
    soulHash: d.soulHash,
    model: { provider: String(model.provider ?? '').slice(0, 128), default: String(model.default ?? '').slice(0, 128) },
    skills: confList(d.skills), toolsets: confList(d.toolsets), pinned: d.toolsets_pinned === true, mcp: confList(d.mcp_servers)
  };
}

/* Standalone page: the demo snapshot carries synthetic describe answers (demo.py); a real snapshot has none. */
function confDemoProfile(st) {
  const raw = DATA && DATA.demo === true && DATA.demoProfiles && DATA.demoProfiles[st.bot];
  st.data = raw ? cleanProfile({ ...raw, soulHash: '0'.repeat(64) }) : null;
  st.load = st.data ? 'ready' : 'idle';
}

/* What the panel shows: loading | demo | nohost | idle | ready | unreachable | ambiguous | unsupported | error (a timeout is an error). */
function confView(st) {
  const key = 'describe|' + st.key;
  if (!confHosted()) {
    return { state: st.data ? 'demo' : 'nohost', message: '' };
  }
  if (confTrips.busy(key)) {
    return { state: 'loading', message: '' };
  }
  if (st.load === 'loading') {
    return { state: 'error', message: (confTrips.result(key) || {}).message };
  }
  return { state: st.load, message: st.message };
}

const confShowsData = (st) => !!st.data && ['ready', 'demo'].includes(confView(st).state);

function loadProfile(st) {
  if (!confHosted()) {
    confDemoProfile(st);
    return;
  }
  const key = 'describe|' + st.key;
  if (confTrips.busy(key)) {
    return;
  }
  const rid = newRid();
  st.load = 'loading';
  st.message = '';
  roundTrip(
    confTrips,
    key,
    { cfg: st.key, rid },
    { pixelhqProfile: { rid, bot: st.bot, remote: st.remote } },
    (r) => onProfileResult({ rid, state: 'error', message: r.message }),
    () => refreshConfig(st)
  );
}

/* The trip that belongs to a result: the request id must match one that is open (or timed out), else the result is dropped. */
function confTake(trips, kind, r) {
  for (const [key, info] of trips.waiting()) {
    if (key.startsWith(kind + '|') && info && info.rid === r.rid) {
      trips.finish(key, r);
      return info;
    }
  }
  return null;
}

const confResult = (r, states) =>
  confIsObject(r) && typeof r.rid === 'string'
    ? { ...r, state: states.includes(r.state) ? r.state : 'error', message: confMsg(r.message) }
    : null;

/* A describe reply while a draft exists only moves the base (R4-D3): the textarea keeps its element, focus and caret. A preview on
   screen was computed against the old base, so it goes back to the editor, which diffs afresh at the next preview. */
function keepDraft(st, data) {
  const d = st.draft;
  d.base = eolNormal(data.soul);
  d.baseHash = data.soulHash;
  confSaveTrips.forget('save|' + st.key);
  if (d.mode === 'preview') {
    d.mode = 'edit';
    d.rid = null;
    d.note = CONF_KEPT;
    refreshRegion(st, 'soul', true);
    return;
  }
  st.kept = true;
  for (const el of confEls(st.key)) {
    el.querySelectorAll('[data-cfg-result]').forEach((line) => line.parentNode.removeChild(line));
    const ta = el.querySelector('[data-cfg-text]');
    if (ta && ta.oninput) {
      ta.oninput();
    }
  }
}

function onProfileResult(raw) {
  const r = confResult(raw, CONF_STATES);
  const info = r && confTake(confTrips, 'describe', r);
  const st = info && confStates.get(info.cfg);
  if (!st) {
    return;
  }
  const data = r.state === 'ready' ? cleanProfile(r.data) : null;
  st.load = r.state === 'ready' && !data ? 'error' : r.state;
  st.message = r.state === 'ready' && !data ? 'Unexpected profile answer' : r.message;
  st.data = data;
  if (data && st.draft) {
    keepDraft(st, data);
  }
  if (data) {
    loadHistory(st);
  }
  refreshConfig(st);
}

/* Messages of the four Config answers (called from the page's message listener); true when the message was one of them. */
function onConfigMessage(m) {
  const handlers = {
    pixelhqProfileResult: onProfileResult,
    pixelhqSoulSaveResult: onSoulSaveResult,
    pixelhqSoulHistoryResult: onHistoryResult,
    pixelhqSoulHistoryItemResult: onHistoryItemResult,
    pixelhqUpdateInfoResult: onUpdateResult
  };
  for (const key of Object.keys(handlers)) {
    if (m[key]) {
      handlers[key](m[key]);
      return true;
    }
  }
  return false;
}

/* ---- Read-only facts ---- */
function confNames(st, id, names) {
  const open = st.more[id] === true;
  let h = (open ? names : names.slice(0, CONF_LIST_MAX)).map(esc).join(', ');
  if (names.length > CONF_LIST_MAX) {
    h += ' <button type="button" class="lnk" data-cfg-more="' + id + '">' +
      (open ? 'show fewer' : '+' + (names.length - CONF_LIST_MAX) + ' more') + '</button>';
  }
  return h || '<span class="mut">none</span>';
}

function factsHtml(st) {
  const d = st.data;
  const row = (k, v) => '<span class="mut">' + k + '</span><span>' + v + '</span>';
  const off = d.skills.filter((s) => !s.enabled).map((s) => s.name);
  const model = [d.model.provider, d.model.default].filter(Boolean).map(esc).join(' / ');
  const servers = d.mcp.map((s) => s.name + ' (' + (s.transport || '?') + ', ' + (s.enabled ? 'enabled' : 'disabled') + ')');
  return '<div class="kv cfg-facts">' + row('Model', model || '–') + row('Description', esc(d.description) || '–') +
    row('Skills', (d.skills.length - off.length) + ' of ' + d.skills.length + ' enabled' +
      (off.length ? ' · disabled: ' + confNames(st, 'skills', off) : '')) +
    row('Toolsets', confNames(st, 'toolsets', d.toolsets.filter((t) => t.enabled).map((t) => t.name)) +
      ' · pinned: ' + (d.pinned ? 'yes' : 'no')) +
    row('MCP servers', confNames(st, 'mcp', servers)) + '</div><div class="mut hint">' + esc(CONF_HINT) + '</div>';
}

function drawFacts(box, st) {
  box.innerHTML = confShowsData(st) ? factsHtml(st) : '';
  box.querySelectorAll('[data-cfg-more]').forEach((btn) =>
    (btn.onclick = () => {
      st.more[btn.dataset.cfgMore] = !st.more[btn.dataset.cfgMore];
      refreshRegion(st, 'facts', true);
    })
  );
}

/* ---- State line and Reload ---- */
const confConflict = (st) => (confSaveTrips.result('save|' + st.key) || {}).state === 'conflict';

function statusHtml(v, st) {
  const notes = {
    demo: 'Standalone page: synthetic demo data, read-only. Editing and the version history need Hermes Desktop.',
    nohost: 'The configuration is only available inside Hermes Desktop (there is no host on the standalone page).'
  };
  const extra = (st.kept && st.draft ? '<div class="res ok" role="status" data-cfg-kept>' + esc(CONF_KEPT) + '</div>' : '') +
    (st.late ? '<div class="res warn" role="status" data-cfg-late>' + esc(st.late) + '</div>' : '');
  if (notes[v.state]) {
    return '<div class="note">' + notes[v.state] + '</div>';
  }
  if (v.state === 'loading') {
    return '<div class="res" role="status">Loading configuration …</div>' + extra;
  }
  if (v.state === 'ready' || v.state === 'idle') {
    return extra;
  }
  return '<div class="res ' + (v.state === 'error' ? 'bad' : 'warn') + '" role="status">' +
    esc(confMsg(v.message) || CONF_TEXT[v.state] || CONF_TEXT.error) + '</div>' + extra;
}

function drawStatus(box, st) {
  const v = confView(st);
  const can = confHosted() && v.state !== 'loading' && (!st.draft || confConflict(st));
  box.dataset.state = v.state;
  box.innerHTML = statusHtml(v, st) + (confHosted()
    ? '<div class="acts"><button type="button" data-cfg-reload' + (can ? '' : ' disabled') + '>Reload</button></div>'
    : '');
  const reload = box.querySelector('[data-cfg-reload]');
  if (reload) {
    reload.onclick = () => reloadConfig(st);
  }
}

/* The notes of a finished episode (a kept draft, a save that finished after the panel moved on) go with the next one. */
function dropNotes(st) {
  st.kept = false;
  st.late = '';
}

function reloadConfig(st) {
  if (!confHosted() || confView(st).state === 'loading' || (st.draft && !confConflict(st))) {
    return;
  }
  if (!st.draft) {
    confSaveTrips.forget('save|' + st.key);
    dropNotes(st);
  }
  st.hist.load = 'idle';
  loadProfile(st);
}

/* ---- Section shell: collapsed by default, state survives the redraws of the card ---- */
const confEls = (key) => [...document.querySelectorAll('[data-cfg]')].filter((el) => el.dataset.cfg === key);
const CONF_REGIONS = { status: drawStatus, facts: drawFacts, soul: drawSoul, history: drawHistory };

/* `user`: the change comes from a click on this panel; otherwise a refresh may not replace the editor under the cursor. */
function refreshRegion(st, name, user) {
  if (!st || (name === 'soul' && !user && st.draft && st.draft.mode === 'edit')) {
    return;
  }
  for (const el of confEls(st.key)) {
    const box = el.querySelector('[data-cfg-' + name + ']');
    if (box) {
      (user ? renderDirect : renderUnlessFocused)(box, () => CONF_REGIONS[name](box, st));
    }
  }
}

function refreshConfig(st) {
  for (const name of Object.keys(CONF_REGIONS)) {
    refreshRegion(st, name, false);
  }
}

function drawConfig(el, st) {
  st.el = el;
  el.innerHTML = '<div class="sec cfg-sec"><button type="button" class="cfg-toggle" data-cfg-toggle aria-expanded="' + st.open +
    '">' + (st.open ? '▾' : '▸') + ' CONFIG</button></div>' +
    (st.open ? '<div data-cfg-status></div><div data-cfg-facts></div><div data-cfg-soul></div><div data-cfg-history></div>' : '');
  el.querySelector('[data-cfg-toggle]').onclick = () => {
    st.open = !st.open;
    if (st.open && st.load === 'idle') {
      loadProfile(st);
    }
    renderDirect(el, () => drawConfig(el, st));
  };
  if (st.open) {
    for (const name of Object.keys(CONF_REGIONS)) {
      CONF_REGIONS[name](el.querySelector('[data-cfg-' + name + ']'), st);
    }
  }
}

const confSlotHtml = (b) => '<div class="cfg" data-cfg="' + esc(confKeyOf(b)) + '"></div>';

/* The draft's element, when it is on the page now: the card is redrawn around it instead of replacing it. */
function heldConfig(b) {
  const st = confStates.get(confKeyOf(b));
  return st && st.draft && st.el && [...document.querySelectorAll('[data-cfg]')].includes(st.el) ? st.el : null;
}

function mountConfig(root, b, held) {
  const slot = root.querySelector('[data-cfg]');
  if (!slot) {
    return;
  }
  if (held) {
    slot.replaceWith(held);
  } else {
    drawConfig(slot, confState(b));
  }
}
