/* ---- "Update available" notice (round 4 §5): header button + info panel, quiet footer line in every other state.
   Only for Pixel HQ itself. The check is Hermes' own plugin list, read by the host bridge (desktop/plugin.js:
   pixelhqUpdateInfo -> pixelhqUpdateInfoResult); the plugin never updates itself. The page asks at load (first snapshot) and then
   at most every 6 h; the standalone page has no host and shows nothing.
   Rendering (D8/D16): button, panel and footer line are static markup (index.html); only text, display and aria flags change, so a
   focused button is never replaced. Values go in through textContent. ---- */
const UPDATE_MS = 6 * 60 * 60 * 1000;
const UPDATE_STATES = ['available', 'current', 'unavailable', 'unsupported', 'error'];
const UPDATE_VERSION_RE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/;
const upd = { asked: null, state: 'idle', installed: null, latest: null, canOpen: false, message: '', open: false };
const updTrips = hostTrips(TRIP_MS.other, () => onUpdateTimeout());
const updEl = (id) => document.getElementById('update-' + id);

function updVersion(v) {
  const o = confIsObject(v) ? v : {};
  const version = typeof o.version === 'string' && UPDATE_VERSION_RE.test(o.version) ? o.version : '';
  const sha = typeof o.sha === 'string' && /^[0-9a-f]{7,64}$/i.test(o.sha) ? o.sha.slice(0, 7) : '';
  return { version, sha };
}

function updLabel(v) {
  if (!v || !(v.version || v.sha)) {
    return '–';
  }
  return (v.version || '') + (v.version && v.sha ? ' ' : '') + (v.sha ? '(' + v.sha + ')' : '');
}

function setText(el, text) {
  if (el.textContent !== text) {
    el.textContent = text;
  }
}

function updFootText() {
  const texts = {
    current: 'Update check: up to date' + (upd.latest && upd.latest.version ? ' (catalog ' + upd.latest.version + ')' : ''),
    unavailable: 'Update check: not available for this installation',
    unsupported: 'Update check: not available (this Hermes version cannot list plugins)',
    error: 'Update check: failed (' + upd.message + ')'
  };
  return confHosted() ? texts[upd.state] || '' : '';
}

function updClose(restoreFocus) {
  upd.open = false;
  updEl('panel').style.display = 'none';
  updEl('btn').setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    updEl('btn').focus();
  }
}

function drawUpdate() {
  const show = confHosted() && upd.state === 'available';
  updEl('btn').style.display = show ? '' : 'none';
  if (!show && upd.open) {
    updClose(false);
  }
  setText(updEl('installed'), updLabel(upd.installed));
  setText(updEl('latest'), updLabel(upd.latest));
  updEl('open').style.display = upd.canOpen ? '' : 'none';
  setText(document.getElementById('update-foot'), updFootText());
}

function updToggle() {
  if (upd.open) {
    updClose(true);
    return;
  }
  upd.open = true;
  updEl('panel').style.display = '';
  updEl('btn').setAttribute('aria-expanded', 'true');
  updEl('panel').focus();
}

function onUpdateResult(r) {
  const info = confIsObject(r) && typeof r.rid === 'string' ? updTrips.info('update') : null;
  if (!info || info.rid !== r.rid || !updTrips.finish('update', r)) {
    return;
  }
  const state = UPDATE_STATES.includes(r.state) ? r.state : 'error';
  if (state === 'error' && upd.state === 'available') {
    return; // a failed re-check does not hide an update that is already known
  }
  upd.state = state;
  upd.message = confMsg(r.message).slice(0, 120);
  upd.installed = updVersion(r.installed);
  upd.latest = updVersion(r.available);
  upd.canOpen = r.canNavigate === true;
  drawUpdate();
}

function onUpdateTimeout() {
  if (upd.state === 'available') {
    return;
  }
  upd.state = 'error';
  upd.message = TIMEOUT_TEXT;
  drawUpdate();
}

/* Called with every render: asks when nothing was asked yet or the last question is 6 h old (or the clock moved back). */
function updateTick() {
  if (!confHosted() || updTrips.busy('update')) {
    return;
  }
  const now = hostClock.now();
  if (upd.asked !== null && now >= upd.asked && now - upd.asked < UPDATE_MS) {
    return;
  }
  upd.asked = now;
  const rid = newRid();
  roundTrip(updTrips, 'update', { rid }, { pixelhqUpdateInfo: { rid } }, () => {}, drawUpdate);
}

updEl('btn').onclick = updToggle;
updEl('close').onclick = () => updClose(true);
updEl('open').onclick = () => {
  updClose(false);
  window.parent.postMessage({ pixelhqOpenPlugins: true }, '*');
};
document.addEventListener('keydown', (e) => {
  if (upd.open && e.key === 'Escape') {
    updClose(true);
  }
});
