/* ---- Bots of other hosts (round 5 §3): read-only. Nothing here sends a message to the host; every string that comes from
   another host goes through esc() like any other text. A bot of another host is keyed "<source>/<id>" in the snapshot and
   carries `remote: true` plus `source`; a roster-only `remote: true` bot without a source is the older "Kanban status
   only" kind and keeps its behaviour. ---- */
const hostOf = (b) => (b && b.remote === true && typeof b.source === 'string' ? b.source : '');
const isHostBot = (b) => hostOf(b) !== '';
/* The name shown for a bot: a bot of another host is keyed "<source>/<id>", its badge already says where it runs. */
const botLabel = (b) => (isHostBot(b) && b.name ? String(b.name) : String(b.id));
const hostHint = (b) => 'Runs on ' + hostOf(b) + ' — actions are available on that host.';

/* "as of 40 s ago": the age of the data a remote bot or card shows, measured against the newest server time the page has
   seen (R5-D6): the newer of the snapshot's and the live data's `generated`, never the older one. */
function asOfText(ts) {
  if (ts == null || !Number.isFinite(Number(ts))) {
    return 'no data yet';
  }
  const times = [DATA, LIVE].filter((part) => part && Number.isFinite(Number(part.generated))).map((part) => Number(part.generated));
  const now = times.length ? Math.max(...times) : Number(ts);
  return 'as of ' + dur(Math.max(0, now - Number(ts))) + ' ago';
}

/* The host badge, plus a `stale` badge while the document is older than the threshold or the source delivers nothing. */
function hostBadges(b) {
  const source = hostOf(b);
  if (!source) {
    return '';
  }
  const state = b.sourceState ? ' · source ' + b.sourceState : '';
  return '<span class="host" title="' + esc('Runs on ' + source + state) + '">' + esc(source) + '</span>' +
    (b.stale === true
      ? '<span class="host stale" title="' + esc('Data of ' + source + ' is stale: ' + asOfText(b.asOf)) + '">stale</span>'
      : '');
}

/* Status of a bot of another host: only the document speaks, never the live poll. A stale document never says "working". */
function hostStatus(b) {
  const status = b.stale === true && b.status === 'running' ? 'idle' : b.status;
  return { status, label: status === 'running' ? shortStep(String(b.currentStep || '')) || 'active' : null };
}

/* Footer: one line per configured source with its state. `text` is the collector's wording ("ok · 35 s", "stale · 12 min",
   "unreachable (timeout)", "invalid (reason)"); a failed fetch behind a kept document is named after it. */
function remoteFootHtml() {
  const list = Array.isArray(DATA.remoteSources) ? DATA.remoteSources : [];
  return list.map((s) => {
    const failed = s.error && (s.state === 'ok' || s.state === 'stale') ? ' · last fetch failed: ' + s.error : '';
    return '<div class="rfl rf-' + esc(s.state) + '" data-remote-source="' + esc(s.source || s.name) + '">Host <b>' +
      esc(s.source || s.name) + '</b> (' + esc(s.kind) + ') · ' + esc(s.text) + esc(failed) + '</div>';
  }).join('');
}

function renderRemoteFoot() {
  document.getElementById('remote-foot').innerHTML = remoteFootHtml();
}

/* Live tab. A remote bot is "working" only while its document is fresh: the row is built from the document's own
   `currentStep`, `lastTool` and `lastActive`, and has no review, Open, Nudge or Talk control. */
function hostLiveHtml(b) {
  const meta = [b.lastActivity ? 'last active ' + ago(b.lastActivity) : '', b.model || '', hostHint(b)]
    .filter(Boolean).join(' · ');
  return '<div class="lc rem" data-remote-live="' + esc(b.id) + '" style="border-left-color:' + safeColor(b.color) +
    '"><div class="h"><div class="holder">' + sprite(b, 4) + '</div><div><div class="nm">' + esc(botLabel(b)) + hostBadges(b) +
    '</div><div class="cl">' + esc(b.title) + ' · ' + esc(asOfText(b.asOf)) + '</div></div></div><div class="ls">' +
    '<div class="st run" title="' + esc(b.currentStep) + '">' + (esc(b.currentStep) || 'working') + '</div>' +
    (b.lastTool ? '<div class="tl"><b>' + esc(b.lastTool) + '</b></div>' : '') + '<div class="mt">' + esc(meta) + '</div></div></div>';
}

/* R5-D4: a bot of another host that is no longer working leaves the active list at once, also while that list waits for the
   focus to leave a review field (a local input elsewhere). A host row holds no field, so removing it never moves the focus. */
function dropIdleHostRows(working) {
  const list = document.getElementById('lactive');
  list.querySelectorAll('[data-remote-live]').forEach((row) => {
    if (!working.has(row.dataset.remoteLive) && row.parentNode) {
      row.parentNode.removeChild(row);
    }
  });
}

function hostIdleText(b) {
  return [
    asOfText(b.asOf),
    b.currentStep ? 'last step: ' + b.currentStep : '',
    b.lastTool ? 'tool: ' + b.lastTool : '',
    b.lastActivity ? 'last active ' + ago(b.lastActivity) : ''
  ].filter(Boolean).join(' · ');
}
