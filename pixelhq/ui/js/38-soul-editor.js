/* ---- SOUL editor of the Config section (round 4 §2, §3): Edit -> Preview changes -> Confirm save (armed) / Back / Cancel.
   `st.draft` = {kind: 'edit' | 'restore', mode: 'edit' | 'preview', text, base, baseHash, rid, note, label}: `base` is the text the
   editor was opened with, `baseHash` its hash (the bridge compares it with a fresh read before it writes anything). A restore
   (39-soul-history.js) is a draft that starts in the preview. The text of the SOUL reaches the page only through
   textarea.value and textContent slots. ---- */
const CONF_SAVE_STATES = ['saved', 'unverified', 'conflict', 'failed', 'unsupported', 'error'];
const CONF_SAVE_TEXT = {
  saved: 'SOUL saved.',
  unverified: 'Saved, but the read-back differs',
  conflict: 'The SOUL changed since you opened it. Reload to see the current version.',
  failed: 'The SOUL was not written.',
  unsupported: 'This Hermes version has no profile editor API',
  error: 'The SOUL was not saved.'
};

function saveLineHtml(st) {
  const key = 'save|' + st.key;
  if (confSaveTrips.busy(key)) {
    const verb = st.draft && st.draft.kind === 'restore' ? 'Restoring' : 'Saving';
    return '<div class="res" role="status" data-cfg-result="saving">' + verb + ' …</div>';
  }
  const r = confSaveTrips.result(key);
  if (!r) {
    return '';
  }
  const cls = r.state === 'saved' ? 'ok' : r.state === 'unverified' || r.state === 'conflict' ? 'warn' : 'bad';
  return '<div class="res ' + cls + '" role="status" data-cfg-result="' + esc(r.state || 'timeout') + '">' +
    esc(confMsg(r.message || CONF_SAVE_TEXT[r.state])) + '</div>';
}

function soulViewHtml(st) {
  const can = confHosted() && confView(st).state === 'ready';
  return '<div class="lab">SOUL · ' + soulLineCount(st.data.soul) + ' lines</div>' +
    '<textarea class="ta soul" data-cfg-text rows="10" spellcheck="false" readonly aria-label="Current SOUL"></textarea>' +
    '<div class="acts"><button type="button" data-cfg-edit' + (can ? '' : ' disabled title="Needs Hermes Desktop"') +
    '>Edit</button></div>' + saveLineHtml(st);
}

function soulEditHtml(st) {
  return '<div class="lab">SOUL · editing <span class="mut" data-cfg-count></span></div>' +
    (st.draft.note ? '<div class="res warn" role="status">' + esc(st.draft.note) + '</div>' : '') +
    '<textarea class="ta soul" data-cfg-text rows="12" spellcheck="false" aria-label="SOUL text"></textarea>' +
    '<div class="res bad" role="alert" data-cfg-problem></div>' +
    '<div class="acts"><button type="button" data-cfg-preview>Preview changes</button>' +
    '<button type="button" data-cfg-cancel>Cancel</button></div><div class="mut hint" data-cfg-hint></div>' + saveLineHtml(st);
}

function soulPreviewHtml(st, slots) {
  const d = st.draft;
  const diff = soulDiff(d.base, d.text);
  const problem = soulProblem(d.text);
  const restore = d.kind === 'restore';
  const off = confSaveTrips.busy('save|' + st.key);
  const lock = off || !!problem || diff.identical;
  return '<div class="lab">' + (restore ? 'RESTORE PREVIEW · ' + esc(d.label) : 'CHANGES') + ' <span class="mut">+' + diff.added +
    ' −' + diff.removed + (diff.coarse ? ' · large change, shown as a replaced block' : '') + '</span></div>' +
    (lostMessaging(d.base, d.text)
      ? '<div class="res warn" role="status" data-cfg-warning>The Bot Mode messaging section was removed · saving is still possible</div>'
      : '') +
    (problem ? '<div class="res bad" role="alert">' + esc(problem) + '</div>' : '') + diffHtml(diff, slots.put) +
    '<div class="acts"><button type="button" data-cfg-confirm' + (lock ? ' disabled' : '') + '>' +
    (restore ? 'Confirm restore' : 'Confirm save') + '</button>' +
    (restore ? '' : '<button type="button" data-cfg-back' + (off ? ' disabled' : '') + '>Back to editing</button>') +
    '<button type="button" data-cfg-cancel' + (off ? ' disabled' : '') + '>Cancel</button></div>' + saveLineHtml(st);
}

function soulHtml(st, slots) {
  const d = st.draft;
  if (d) {
    return d.mode === 'preview' ? soulPreviewHtml(st, slots) : soulEditHtml(st);
  }
  return confShowsData(st) ? soulViewHtml(st) : saveLineHtml(st);
}

function drawSoul(box, st) {
  const slots = textSlots();
  const d = st.draft;
  box.innerHTML = soulHtml(st, slots);
  slots.fill(box);
  const ta = box.querySelector('[data-cfg-text]');
  if (ta) {
    ta.value = d ? d.text : st.data.soul;
  }
  bindSoul(box, st);
}

/* The text area reports every keystroke to the draft; the buttons and messages around it are updated in place (no redraw). */
function bindEditor(box, st) {
  const d = st.draft;
  const ta = box.querySelector('[data-cfg-text]');
  const preview = box.querySelector('[data-cfg-preview]');
  const problem = box.querySelector('[data-cfg-problem]');
  const count = box.querySelector('[data-cfg-count]');
  const hint = box.querySelector('[data-cfg-hint]');
  const sync = () => {
    const bad = soulProblem(d.text);
    const same = sameSoul(d.base, d.text);
    preview.disabled = !!bad || same;
    problem.textContent = bad;
    hint.textContent = same && !bad ? 'No changes yet' : '';
    count.textContent = '· ' + soulLineCount(d.text) + ' lines · ' + soulBytes(d.text) + ' bytes';
  };
  ta.oninput = () => {
    d.text = ta.value;
    sync();
  };
  sync();
}

function bindSoul(box, st) {
  const on = (sel, fn) => {
    const el = box.querySelector(sel);
    if (el) {
      el.onclick = fn;
    }
  };
  on('[data-cfg-edit]', () => startEdit(st));
  on('[data-cfg-preview]', () => toPreview(st));
  on('[data-cfg-back]', () => backToEdit(st));
  on('[data-cfg-cancel]', () => cancelDraft(st));
  const confirm = box.querySelector('[data-cfg-confirm]');
  if (confirm) {
    const restore = st.draft.kind === 'restore';
    const label = restore ? 'Confirm restore' : 'Confirm save';
    const armed = restore ? 'Click again to restore' : 'Click again to save';
    confirm.onclick = () => armedButton(confirm, () => label, armed, () => sendSave(st));
  }
  if (st.draft && st.draft.mode === 'edit') {
    bindEditor(box, st);
  }
}

/* A draft appears or goes away: the editor, the Reload button and the history buttons all change. */
function refreshDraftUi(st) {
  refreshRegion(st, 'soul', true);
  refreshRegion(st, 'status', true);
  refreshRegion(st, 'history', true);
}

function focusEditor(st) {
  for (const el of confEls(st.key)) {
    const ta = el.querySelector('[data-cfg-text]');
    if (ta && !ta.readOnly) {
      ta.focus();
    }
  }
}

function startEdit(st) {
  if (!confHosted() || !confShowsData(st) || st.draft) {
    return;
  }
  confSaveTrips.forget('save|' + st.key);
  dropNotes(st);
  const text = eolNormal(st.data.soul);
  st.draft = { kind: 'edit', mode: 'edit', text, base: text, baseHash: st.data.soulHash, rid: null, ridKey: '', note: '', label: '' };
  refreshDraftUi(st);
  focusEditor(st);
}

function toPreview(st) {
  const d = st.draft;
  if (!d || d.mode !== 'edit' || soulProblem(d.text) || sameSoul(d.base, d.text)) {
    return;
  }
  d.mode = 'preview';
  refreshRegion(st, 'soul', true);
}

function backToEdit(st) {
  const d = st.draft;
  if (!d || d.kind !== 'edit' || d.mode !== 'preview' || confSaveTrips.busy('save|' + st.key)) {
    return;
  }
  d.mode = 'edit';
  refreshRegion(st, 'soul', true);
  focusEditor(st);
}

function cancelDraft(st) {
  if (!st.draft || confSaveTrips.busy('save|' + st.key)) {
    return;
  }
  st.draft = null;
  confSaveTrips.forget('save|' + st.key);
  dropNotes(st);
  refreshDraftUi(st);
}

/* ---- Save: one message to the host (the bridge runs re-read, backup, write, read-back, spec §3) ---- */
/* The request id belongs to one attempt (this base, this text): a retry after a timeout reuses it, so the bridge attaches it to the
   save that may still be running (R4-D2); another text or base is another save. The id of a save that moved on is remembered, so
   its late answer becomes a note. */
function saveRid(st) {
  const d = st.draft;
  const ridKey = d.baseHash + '\n' + d.text;
  if (d.rid && d.ridKey !== ridKey) {
    d.rid = null;
  }
  d.rid = d.rid || newRid();
  d.ridKey = ridKey;
  const prior = confSaveTrips.info('save|' + st.key);
  if (prior && prior.rid !== d.rid) {
    confMoved.set(prior.rid, { cfg: st.key });
    for (const old of [...confMoved.keys()].slice(0, Math.max(0, confMoved.size - CONF_MOVED_MAX))) {
      confMoved.delete(old);
    }
  }
  return d.rid;
}

function sendSave(st) {
  const d = st.draft;
  const key = 'save|' + st.key;
  if (!confHosted() || !d || d.mode !== 'preview' || confSaveTrips.busy(key) || soulProblem(d.text) || sameSoul(d.base, d.text)) {
    return;
  }
  const rid = saveRid(st);
  roundTrip(
    confSaveTrips,
    key,
    { cfg: st.key, rid, text: eolNormal(d.text) },
    { pixelhqSoulSave: { rid, bot: st.bot, remote: st.remote, baseHash: d.baseHash, soul: d.text } },
    (r) => onSoulSaveResult({ rid, state: 'error', message: r.message }),
    () => refreshRegion(st, 'soul', true)
  );
}

/* The write went through. Normally the draft is done and the panel shows the new SOUL; a draft that is being typed meanwhile
   (the answer was late) is kept and compared with the saved text from now on. Without a usable hash the SOUL is read again. */
function applySaved(st, r, info) {
  const hash = /^[0-9a-f]{64}$/.test(r.soulHash) ? r.soulHash : '';
  const fresh = r.state === 'saved' && !!st.data && !!hash;
  const d = st.draft;
  if (fresh) {
    st.data.soul = info.text;
    st.data.soulHash = hash;
  }
  if (d && (d.mode === 'edit' || d.rid !== info.rid)) {
    if (fresh) {
      d.base = info.text;
      d.baseHash = hash;
      d.rid = null;
    }
  } else {
    st.draft = null;
  }
  if (!fresh) {
    loadProfile(st);
  }
  loadHistory(st);
}

/* A save that finished after the panel moved on (another save started, the draft was cancelled or replaced): it is shown as a note
   and never touches the draft or the SOUL on screen (R4-D2). */
function noteMovedSave(st, r) {
  const what = r.state === 'saved' ? 'SOUL saved.' : CONF_SAVE_TEXT[r.state] || CONF_SAVE_TEXT.error;
  st.late = 'An earlier save finished after you moved on: ' + confMsg(r.message || what) + ' Reload to see the current SOUL.';
  refreshRegion(st, 'status', false);
}

function onSoulSaveResult(raw) {
  const r = confResult(raw, CONF_SAVE_STATES);
  const info = r && confTake(confSaveTrips, 'save', r);
  const moved = r && !info ? confMoved.get(r.rid) : null;
  const st = confStates.get((info || moved || {}).cfg);
  if (!st) {
    return;
  }
  if (moved) {
    confMoved.delete(r.rid);
  }
  if (!info || !st.draft || st.draft.rid !== info.rid) {
    if (info) {
      confSaveTrips.forget('save|' + st.key);
    }
    noteMovedSave(st, r);
    return;
  }
  if (r.state === 'saved' || r.state === 'unverified') {
    applySaved(st, r, info);
  } else {
    st.draft.rid = null;
  }
  refreshConfig(st);
}
