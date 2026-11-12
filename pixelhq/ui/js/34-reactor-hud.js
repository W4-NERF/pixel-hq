/* Reactor (GPU/LLM metrics) panel and the HUD strip with the footer line. */
function tps(v) {
  if (v == null) {
    return '–';
  }
  return v >= 1000 ? fmt1(v / 1000, 1) + 'k' : fmt1(v);
}

function reactorHtml(g) {
  if (!g) {
    return '<div class="mut" style="font-size:11px">No GPU/LLM metrics configured (gpu.prometheus_url in config.json).</div>';
  }
  let h = (g.nodes.length
      ? g.nodes.map((n) =>
        '<div class="srv"><div class="px" style="font-size:11px">' + esc(n.id) + '</div><div style="margin:4px 0">' +
          '<span class="led"></span>'.repeat(6) + '</div><div class="mut" style="font-size:10px">GPU ' +
          (n.util == null ? '–' : Number(n.util)) + ' % · ' + (n.power == null ? '–' : Number(n.power)) +
          ' W</div><div class="bar xp"><b style="width:' + Number(n.util || 0) + '%"></b></div></div>'
      ).join('')
      : '<div class="mut">no DCGM data</div>') +
    '<div class="mut" style="font-size:10px">Model: ' + (esc(g.model) || 'not reachable') + '</div>';
  const t = g.srv;
  if (!t) {
    return h + '<div class="mut" style="font-size:10px;margin-top:6px">no serving metrics (' + esc(g.engine) +
      ':*)</div>';
  }
  const kv = t.kv == null ? null : Math.round(t.kv * 100);
  const pair = t.pairBroken == null && t.pairStalled == null
    ? ''
    : t.pairBroken > 0
    ? ' · <span style="color:var(--rust)">node pair broken</span>'
    : t.pairStalled > 0
    ? ' · <span style="color:var(--amber)">node pair stalled</span>'
    : ' · <span style="color:var(--olive)">node pair ok</span>';
  return h + '<div class="srv" style="margin-top:8px"><div class="px" style="font-size:11px">' +
    esc(g.engine.toUpperCase()) + pair + '</div>' +
    '<div class="kv" style="grid-template-columns:112px 1fr;margin-top:4px"><span class="mut">Decode</span><span>' +
    tps(t.decodeTps) + ' tok/s</span><span class="mut">Prefill</span><span>' + tps(t.prefillTps) + ' tok/s</span>' +
    '<span class="mut">Requests</span><span>' + fmt1(t.running) + ' running · ' + fmt1(t.waiting) + ' waiting</span>' +
    (t.specAccept != null
      ? '<span class="mut">Spec. accept</span><span>' + Math.round(t.specAccept * 100) + ' %</span>'
      : '') +
    (t.ttftP50 != null ? '<span class="mut">TTFT p50</span><span>' + fmt1(t.ttftP50, 1) + ' s</span>' : '') + '</div>' +
    '<div class="mut" style="font-size:10px;margin-top:4px">KV cache ' + (kv == null ? '–' : kv + ' %') +
    '</div><div class="bar xp"><b style="width:' + (kv || 0) + '%"></b></div>' +
    '<div class="mut" style="font-size:9px;margin-top:4px">throughput 5 min · accept/TTFT 15 min</div></div>';
}

/* Stale-backend banner (D13, round 3 §5): static markup, only the text and the display flag change, so a hovered or
   focused Dismiss button is never replaced. Dismiss hides it for this page load; the footer line stays. */
let staleDismissed = false;

function staleBanner() {
  const text = staleText();
  const visible = !staleDismissed && text !== '';
  document.getElementById('stale-text').textContent = text;
  document.getElementById('stale-banner').style.display = visible ? '' : 'none';
}

document.getElementById('stale-dismiss').onclick = () => {
  staleDismissed = true;
  document.getElementById('stale-banner').style.display = 'none';
};

function hud() {
  staleBanner();
  const bs = DATA.bots;
  const sum = (k) => bs.reduce((a, b) => a + Number(b[k] || 0), 0);
  const party = sum('n') ? Math.round(100 * sum('p') / sum('n')) : 0;
  const g = DATA.reactor;
  const gpu = g
    ? g.nodes.map((n) => n.id + ' ' + (n.util == null ? '–' : Number(n.util)) + '%').join(' · ') || '–'
    : '–';
  const reactor = g && g.srv && g.srv.decodeTps != null ? tps(g.srv.decodeTps) + ' tok/s' : gpu;
  document.getElementById('brand').textContent = CFG().label || 'PIXEL HQ';
  document.getElementById('hud').innerHTML = [
    ['PARTY HP', party + '%', 'pass rate across all reviews'],
    [
      'ACTIVE BOTS',
      bs.filter((b) => liveStatus(b).status === 'running').length + '/' + bs.length,
      LIVE ? 'live as of ' + clock(LIVE.generated) : 'snapshot'
    ],
    ['BLOCKED QUESTS', sum('blocked'), 'Kanban, all boards'],
    ['TOTAL XP', fmtN(sum('xp')), ''],
    ['REACTOR', reactor, g ? 'decode throughput (5 min) · GPU ' + gpu : 'not configured']
  ].map((x) =>
    '<div title="' + esc(x[2]) + '"><div class="k">' + esc(x[0]) + '</div><div class="v">' + esc(x[1]) + '</div></div>'
  ).join('');
  document.getElementById('stand').textContent = (DATA.demo ? 'DEMO DATA · ' : '') + 'as of ' + clock(DATA.generated);
  const sourceXp = (source) => bs.reduce((total, b) => total + Number((b.xpBySource || {})[source] || 0), 0);
  const signed = (n) => (n > 0 ? '+' : '') + fmtN(n);
  const x = CFG().xp;
  const warnings = [...new Set([...DATA.warnings || [], ...LIVE && LIVE.warnings || []])];
  document.getElementById('foot').textContent = staleNotice() + 'XP: pass ' + (x.pass > 0 ? '+' : '') + x.pass +
    ' · revise ' + (x.revise > 0 ? '+' : '') + x.revise + ' · fail ' + x.fail + ' · XP sources (raw): Kanban ' +
    signed(sourceXp('kanban')) + ' · reviews ' + signed(sourceXp('reviews')) +
    ' · raw source totals may differ from floored XP · level = 1 + floor(sqrt(XP/25)) · HP = pass rate · ' +
    'sub-agents count for the bot that spawned them · collector ' +
    DATA.collectMs + ' ms · sources read-only; actions and reviews require confirmation' +
    (CFG().configError ? ' · ' + CFG().configError : '') +
    (warnings.length ? ' · Warnings: ' + warnings.join(' · ') : '');
}
