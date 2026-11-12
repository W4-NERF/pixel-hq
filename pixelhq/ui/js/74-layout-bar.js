/* ---- Layout edit mode of the Office floor, part 1: the switch and the bar "Unsaved layout changes · Save · Discard · result".
   Edit mode works on the roster draft of 70-roster.js (one draft for the Office floor and the Roster tab). The bar is drawn
   into #office-bar and #roster-bar from the same state: unsaved changes, the pending Save and its result. Save is the roster
   round trip (post first); Discard returns to the saved roster (two-click armed button). The standalone page offers edit mode
   only with ?actions=1 (EMBED). ---- */
let layoutEdit = false;
let layoutAdding = '';
const layoutBarDrawn = new Map();
const layoutEditing = () => layoutEdit && EMBED && !!DATA;

/* Key order does not matter for "the draft differs from the saved roster". */
const rosterCanon = (value) =>
  JSON.stringify(value, (key, item) =>
    item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
      : item
  );

const layoutUnsaved = () =>
  !!rosterDraft && rosterDirty && rosterCanon(rosterDraft) !== rosterCanon(rosterSaved || rosterFromSnapshot());

/* One bar, one footprint: clean (muted line), dirty (message + Save + Discard), busy and result share the fixed height of
   .layout-bar, so switching states never moves the page. `always` draws the clean line when there is nothing else to say. */
function layoutBarHtml(always) {
  const unsaved = layoutUnsaved();
  const busy = rosterBusy();
  const note = rosterResult();
  const off = busy ? ' disabled' : '';
  return (unsaved
    ? '<span class="layout-msg">Unsaved layout changes</span><button type="button" data-layout-save' + off +
      '>Save</button><button type="button" data-layout-discard' + off + '>Discard</button>'
    : '') +
    (always && !unsaved && !busy && !note ? '<span class="layout-clean">No unsaved changes</span>' : '') +
    (busy ? '<span class="layout-result" role="status">Saving roster …</span>' : '') +
    (note && !busy
      ? '<span class="layout-result ' + (note.ok ? 'ok' : 'bad') + '" role="status" title="' + esc(note.message) + '">' +
        esc(note.message) + '</span>'
      : '');
}

/* Discard: back to the saved roster (the snapshot's when nothing was saved in this page load). */
function rosterDiscard() {
  if (rosterBusy()) {
    return;
  }
  rosterDraft = null;
  rosterDirty = false;
  layoutAdding = '';
  rosterTrips.forget('roster');
  renderRoster();
}

function bindLayoutBar(el) {
  const save = el.querySelector('[data-layout-save]');
  const discard = el.querySelector('[data-layout-discard]');
  if (save) {
    save.onclick = saveRoster;
  }
  if (discard) {
    discard.onclick = () => armedButton(discard, () => 'Discard', 'Confirm: discard?', rosterDiscard);
  }
}

/* A bar is redrawn only when its content changes, so an armed Discard button stays armed across unrelated renders.
   The Roster tab always has its bar; the floor has one while edit mode is on, and after leaving it only while unsaved
   changes, a Save or its result are pending (round-3 section 3). */
function renderLayoutBar() {
  const tool = document.getElementById('edit-layout');
  tool.style.display = EMBED ? '' : 'none';
  tool.textContent = layoutEditing() ? 'Done editing' : 'Edit layout';
  tool.classList.toggle('on', layoutEditing());
  tool.setAttribute('aria-pressed', layoutEditing() ? 'true' : 'false');
  for (const id of ['office-bar', 'roster-bar']) {
    const el = document.getElementById(id);
    const html = EMBED ? layoutBarHtml(id === 'roster-bar' || layoutEditing()) : '';
    if (layoutBarDrawn.get(id) === html) {
      continue;
    }
    layoutBarDrawn.set(id, html);
    const drawn = renderDirect(el, () => {
      el.innerHTML = html;
      bindLayoutBar(el);
    });
    if (!drawn) {
      layoutBarDrawn.delete(id);
    }
  }
}

/* Redraws the floor (a running drag holds the render until it ends, 78-layout-drag.js). */
const renderFloor = () => renderDirect(document.getElementById('floor'), drawFloor);

function renderFloorEdit() {
  if (layoutEditing()) {
    renderFloor();
  }
}

function toggleLayoutEdit() {
  if (!EMBED || !DATA) {
    return;
  }
  layoutEdit = !layoutEdit;
  layoutAdding = '';
  if (layoutEdit) {
    rosterEnsureDraft();
  }
  renderLayoutBar();
  renderFloor();
}
