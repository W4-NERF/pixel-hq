/* ---- live ---- */
const SRC = {
  desktop: 'desktop',
  kanban: 'kanban',
  cron: 'cron',
  subagent: 'sub',
  cli: 'cli',
  oneshot: 'oneshot',
  matrix: 'matrix',
  discord: 'discord',
  email: 'mail',
  tool: 'tool'
};
const dur = (s) =>
  s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : Math.round(s / 360) / 10 + ' h';
const kt = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1000 ? Math.round(n / 1000) + 'k' : String(n);

function sessHtml(s, now, sub, agent) {
  const st = s.step
    ? '<div class="st' + (s.stale ? ' stale' : ' run') + '" title="' + esc(s.step) + '">' + esc(s.step) +
      (s.stale ? ' — no progress for ' + dur(now - s.lastAt) : '') + '</div>'
    : '<div class="st" style="color:var(--mut)">waiting for the next step</div>';
  const tl = s.tool
    ? '<div class="tl" title="' + esc(s.tool.name + ' ' + (s.tool.arg || '')) + '"><b>' + esc(s.tool.name) + '</b>' +
      (s.tool.arg ? ' › ' + esc(s.tool.arg) : '') + ' <span class="mut">(' + ago(s.tool.ts) + ')</span></div>'
    : '';
  const meta = [
    'for ' + dur(now - s.startedAt),
    s.msgs + ' msgs',
    s.toolCalls + ' tools',
    kt(s.inTok + s.outTok) + ' tok',
    s.cost != null
      ? s.cost.toLocaleString(CFG().locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' $'
      : null,
    s.model || null
  ].filter(Boolean).join(' · ');
  return '<div class="ls' + (sub ? ' sub' : '') + '"><div class="t"><span class="src ' +
    (sub ? 'sub' : esc(SRC[s.source] || '')) + '">' + (sub ? 'subagent' : esc(SRC[s.source] || s.source)) + '</span>' +
    esc(s.title) + '</div>' + st + tl + '<div class="mt">' + esc(meta) + '</div>' + jumpHtml(agent, s.id, s.stale) +
    (!sub && s.source !== 'subagent' ? reviewHtml(agent, s.id, s.title) : '') +
    (s.children || []).map((c) => sessHtml(c, now, true, agent)).join('') + '</div>';
}

function taskHtml(t, now) {
  const hb = t.heartbeatAge == null ? 'no heartbeat' : 'heartbeat ' + dur(t.heartbeatAge) + ' ago';
  const bad = t.heartbeatAge == null || t.heartbeatAge > 600;
  return '<div class="ls"><div class="t"><span class="src kanban">kanban</span>' + esc(t.board) + ' · ' + esc(t.title) +
    '</div><div class="st' + (bad ? ' stale' : ' run') + '">' + esc(hb) +
    (t.startedAt ? ' · running for ' + dur(now - t.startedAt) : '') + '</div><div class="mt">' + esc(t.id) +
    (t.pid ? ' · PID ' + esc(t.pid) : '') + '</div></div>';
}

function liveTab() {
  const tabEl = document.getElementById('livetab');
  const note = document.getElementById('livenote');
  if (!LIVE) {
    tabEl.textContent = 'Live';
    note.style.display = '';
    note.textContent = LIVE_ERR ? 'Live data unavailable: ' + LIVE_ERR : 'Loading live data …';
    renderDirect(document.getElementById('lactive'), () => {
      document.getElementById('lactive').innerHTML = '';
    });
    document.getElementById('lidle').innerHTML = '';
    return;
  }
  note.style.display = LIVE_ERR ? '' : 'none';
  if (LIVE_ERR) {
    note.textContent = 'Last live poll failed: ' + LIVE_ERR + ' (as of ' + clock(LIVE.generated) + ')';
  }
  const act = [];
  const idle = [];
  DATA.bots.forEach((b) => {
    const v = liveOf(b.id);
    if (v && v.active) {
      act.push([b, v]);
    } else {
      idle.push([b, v]);
    }
  });
  tabEl.textContent = 'Live (' + act.length + ')';
  renderUnlessFocused(document.getElementById('lactive'), liveActive);
  document.getElementById('lidle').innerHTML = idle.map(([b, v]) => {
    const l = v && v.last;
    const z = v && v.remote
      ? 'remote host – Kanban status only'
      : l
      ? 'last seen ' + ago(l.at) + ' · ' + (l.title || l.step || l.source)
      : v && v.error
      ? 'state.db: ' + v.error
      : 'no session found';
    return '<div><span class="n">' + esc(b.id) + '</span><span class="z" title="' + esc(z) + '">' + esc(z) +
      '</span></div>';
  }).join('');
}

/* Active rows hold the review forms, so this part waits for the focus to leave (D8). */
function liveActive() {
  const now = LIVE.generated;
  const act = DATA.bots.map((b) => [b, liveOf(b.id)]).filter(([, v]) => v && v.active);
  document.getElementById('lactive').innerHTML = act.map(([b, v]) =>
    '<div class="lc" style="border-left-color:' + safeColor(b.color) + '"><div class="h"><div class="holder">' +
      sprite(b, 4) + '</div><div><div class="nm">' + esc(b.id) + '</div><div class="cl">' + esc(b.title) + ' · ' +
      v.sessions.length + ' session' + (v.sessions.length === 1 ? '' : 's') +
      (v.tasks.length ? ' · ' + v.tasks.length + ' card' + (v.tasks.length === 1 ? '' : 's') : '') +
      '</div></div></div>' + v.sessions.map((s) => sessHtml(s, now, false, b.id)).join('') +
      v.tasks.map((t) => taskHtml(t, now)).join('') + '</div>'
  ).join('') ||
    '<div class="mut">no bot is working right now</div>';
  bindReviews(document.getElementById('lactive'));
  bindJumps(document.getElementById('lactive'));
}

function liveRender() {
  try {
    hud();
    office();
    liveTab();
  } catch (e) {
    setStand('live render error: ' + e);
  }
}
