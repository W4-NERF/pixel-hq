/* Pixel HQ page script. The files in this folder are joined in file-name order into one inline script:
   one shared scope, no build step (see pixelhq/page.py). */
/* Every string coming from cards, sessions or the ledger goes through esc() before it touches innerHTML. */
let DATA = /*PIXELHQ_DATA*/null;
let LIVE = null;
let LIVE_ERR = null;
const CFG = () =>
  DATA && DATA.cfg ||
    {
      locale: 'en-GB',
      timezone: 'UTC',
      xp: { pass: 10, revise: 3, fail: -5 },
      staleDays: 14,
      rooms: [],
      operator: 'operator',
      orchestrator: 'default'
    };

// Stale-backend notice: the files on disk were updated while the gateway keeps running the older code.
const staleText = () => {
  const c = CFG();
  const v = c.version;
  const d = c.diskVersion;
  return typeof v === 'string' && typeof d === 'string' && v && d && v !== d
    ? 'Pixel HQ ' + d + ' is installed but ' + v +
      ' is still running — restart the Hermes gateway (`hermes gateway restart`) to finish the update.'
    : '';
};
const staleNotice = () => (staleText() ? staleText() + ' · ' : '');
let hostMode = null;
const validMode = (mode) => mode === 'light' || mode === 'dark';

function appearanceMode() {
  const override = window.parent === window ? new URLSearchParams(location.search).get('mode') : null;
  return validMode(override)
    ? override
    : validMode(CFG().appearance)
    ? CFG().appearance
    : validMode(hostMode)
    ? hostMode
    : 'dark';
}

function applyAppearance() {
  document.documentElement.dataset.mode = appearanceMode();
}

const PALETTE = {
  dark: {
    eye: '#0B0F14',
    accent: '#DCE4EC',
    amber: '#C9A23F',
    shade: 'rgba(11,15,20,.5)',
    rust: '#C1652E',
    fallback: '#93A1AF',
    swatches: [
      '#93A1AF',
      '#7E9A52',
      '#C1652E',
      '#C9A23F',
      '#5FA36A',
      '#6F9AA8',
      '#9FB27A',
      '#D98A5C',
      '#A990C5',
      '#6E9CD0',
      '#D2859F',
      '#B5C0CC'
    ]
  },
  light: {
    eye: '#17202A',
    accent: '#46525E',
    amber: '#8A6A12',
    shade: 'rgba(23,32,42,.5)',
    rust: '#A8521F',
    fallback: '#46525E',
    swatches: [
      '#46525E',
      '#5F7A3A',
      '#A8521F',
      '#8A6A12',
      '#3F7F4B',
      '#426C7A',
      '#556B36',
      '#A04E20',
      '#7A559B',
      '#396FA9',
      '#A64469',
      '#344454'
    ]
  }
};
const palette = () => PALETTE[appearanceMode()];
const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
const safeColor = (c) => /^#[0-9a-fA-F]{6}$/.test(c) ? c : palette().fallback;

function submitToHost(message, unavailable) {
  if (window.parent === window) {
    unavailable({ ok: false, message: 'standalone page: no host, nothing was sent' });
    return;
  }
  window.parent.postMessage(message, '*');
}

function liveOf(id) {
  const v = LIVE && LIVE.bots && LIVE.bots[id];
  return v || null;
}

function shortStep(st) {
  if (!st) {
    return '';
  }
  let m;
  if ((m = st.match(/terminal command running \((\d+)s/))) {
    return 'terminal · ' + m[1] + ' s';
  }
  if ((m = st.match(/sequential tool running \((\d+)s\): (\w+)/))) {
    return m[2] + ' · ' + m[1] + ' s';
  }
  if ((m = st.match(/delegate_task: subagent running (\w+) \(iteration (\d+)\/(\d+)\)/))) {
    return 'subagent ' + m[2] + '/' + m[3];
  }
  if ((m = st.match(/tool running: (\w+)/))) {
    return m[1];
  }
  if (/receiving stream response/.test(st)) {
    return 'thinking …';
  }
  if (/starting new turn/.test(st)) {
    return 'new turn';
  }
  return st.length > 22 ? st.slice(0, 21) + '…' : st;
}

function liveStatus(b) {
  const v = liveOf(b.id);
  if (!v) {
    return { status: b.status, label: null };
  }
  if (v.active) {
    const s = v.sessions[0];
    if (s) {
      return { status: 'running', label: shortStep(s.step) || 'active' };
    }
    const t = v.tasks[0];
    return {
      status: 'running',
      label: t ? 'kanban · ' + (t.heartbeatAge == null ? 'no heartbeat' : 'hb ' + t.heartbeatAge + ' s') : 'active'
    };
  }
  return { status: b.status === 'running' ? 'idle' : b.status, label: null };
}

const ATTR = ['Precision', 'Stamina', 'Discipline', 'Wisdom'];
const ATTR_T = ['correctness', 'completeness', 'format', 'safety'];
const fmtN = (n) => Number(n || 0).toLocaleString(CFG().locale);
const fmt1 = (v, d) => v == null ? '–' : Number(v).toLocaleString(CFG().locale, { maximumFractionDigits: d || 0 });

function ago(ts) {
  if (!ts) {
    return '–';
  }
  const s = (LIVE ? LIVE.generated : DATA.generated) - ts;
  if (s < 90) {
    return 'just now';
  }
  if (s < 3600) {
    return Math.round(s / 60) + ' min ago';
  }
  if (s < 86400) {
    return Math.round(s / 3600) + ' h ago';
  }
  return Math.round(s / 86400) + ' d ago';
}

function clock(ts) {
  try {
    return new Date(ts * 1000).toLocaleString(
      CFG().locale,
      { timeZone: CFG().timezone, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
    );
  } catch (e) {
    return new Date(ts * 1000).toISOString().slice(5, 16);
  }
}

function hm() {
  try {
    return new Date().toLocaleTimeString(
      CFG().locale,
      { timeZone: CFG().timezone, hour: '2-digit', minute: '2-digit' }
    );
  } catch (e) {
    return new Date().toISOString().slice(11, 16);
  }
}

const hpTxt = (b) => b.hp == null ? '–' : Number(b.hp) + '%';

let sel = null;
let ofilter = 'all';
let bzone = 'all';
let bsort = 'lvl';

/* Embedded (desktop plugin, sandboxed iframe): data arrives via postMessage from the host, "Reload" asks
   the host. Standalone (dist/pixel-hq.html): the snapshot is embedded at render time. */
/* ?actions=1: show action buttons on the standalone page (demo video) */
const EMBED = window.parent !== window || /[?&]actions=1\b/.test(location.search);

function setStand(t) {
  document.getElementById('stand').textContent = t;
}
