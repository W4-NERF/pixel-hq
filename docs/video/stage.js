/* Pixel HQ film — browser side. Injected into the standalone demo page (demo data only).
 * - camera: CSS transform on <body> (text stays vector-sharp at any zoom)
 * - overlay: caption box, pixel cursor, click ripple, end card (a sibling of <body>, not transformed)
 * - time: every CSS animation is paused and set from the film clock, so frames are deterministic
 * - host: stands in for the Hermes desktop host (postMessage protocol of ui.html) with demo replies
 */
(() => {
  const S = (window.__stage = {});
  const W = innerWidth, H = innerHeight, PAGE_W = 1920;
  let cam = { cx: 960, cy: 540, s: 1 };
  const born = new WeakMap();

  /* ---------- host stand-in: replies are placeholders, see HOST_TEXT in film.js ---------- */
  let HOST = { answer: '', triage: '', latency: 700 };
  const unblocked = new Set();
  const live0 = JSON.parse(JSON.stringify(DATA.live));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const fill = (tpl, o) => tpl.replace(/\{(\w+)\}/g, (_, k) => (o[k] ?? ''));
  window.addEventListener('message', (e) => {
    const m = e.data || {};
    if (m.pixelhqAction) {
      const a = m.pixelhqAction;
      setTimeout(() => {
        if (a.action === 'answer') unblocked.add(a.board + '/' + a.id);
        window.postMessage({ pixelhqActionResult: { board: a.board, id: a.id, action: a.action, ok: true, message: fill(HOST.answer, a) } }, '*');
      }, HOST.latency);
    }
    if (m.pixelhqTriage) {
      const t = m.pixelhqTriage;
      setTimeout(() => window.postMessage({ pixelhqTriageResult: { ok: true, message: fill(HOST.triage, { n: t.keys.length, orchestrator: CFG().orchestrator, scope: t.scope }) } }, '*'), HOST.latency + 300);
    }
    if (m.pixelhqReload) {
      setTimeout(() => {
        const d = clone(DATA);
        d.generated = Date.now() / 1000;
        d.blockers = d.blockers.filter((b) => {
          const gone = unblocked.has(b.board + '/' + b.id);
          if (gone) { const bot = d.bots.find((x) => x.id === b.assignee); if (bot) bot.blocked = Math.max(0, bot.blocked - 1); }
          return !gone;
        });
        window.postMessage({ pixelhq: d }, '*');
      }, 450);
    }
  });
  /* live poll: the host pushes a fresh live snapshot; we age the demo snapshot by e seconds */
  function liveAt(e) {
    const L = clone(live0);
    const bump = (s) => s.replace(/\((\d+)s/g, (_, n) => '(' + (+n + Math.floor(e)) + 's');
    L.generated = live0.generated + e;
    const sess = (s, k) => {
      s.step = s.step && bump(s.step);
      s.lastAt += e;
      s.msgs += Math.floor(e / (6 + k));
      s.toolCalls += Math.floor(e / (9 + k));
      s.inTok += Math.floor(e * (700 + 90 * k));
      if (s.cost != null) s.cost += e * 0.006;
      (s.children || []).forEach((c, j) => sess(c, k + j + 3));
    };
    Object.values(L.bots).forEach((v, i) => {
      (v.sessions || []).forEach((s, j) => sess(s, i + j));
      (v.tasks || []).forEach((t) => { if (t.heartbeatAge != null) t.heartbeatAge = Math.round((t.heartbeatAge + e) % 30); });
    });
    return L;
  }

  /* ---------- camera ---------- */
  function applyCam(c) {
    cam = c;
    document.body.style.transform = `translate(${W / 2 - c.cx * c.s}px,${H / 2 - c.cy * c.s}px) scale(${c.s})`;
  }
  S.pageRect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect(), tx = W / 2 - cam.cx * cam.s, ty = H / 2 - cam.cy * cam.s;
    return { x: (r.left - tx) / cam.s, y: (r.top - ty) / cam.s, w: r.width / cam.s, h: r.height / cam.s };
  };

  /* ---------- overlay ---------- */
  const CUR = [
    'X...........', 'XX..........', 'XOX.........', 'XOOX........', 'XOOOX.......', 'XOOOOX......', 'XOOOOOX.....',
    'XOOOOOOX....', 'XOOOOOOOX...', 'XOOOOOOOOX..', 'XOOOOOXXXXX.', 'XOOXOOX.....', 'XOX.XOOX....', 'XX..XOOX....',
    'X....XOOX...', '.....XOOX...', '......XX....'];
  function cursorSvg(px) {
    let r = '';
    CUR.forEach((row, y) => [...row].forEach((c, x) => {
      if (c !== '.') r += `<rect x="${x}" y="${y}" width="1" height="1" fill="${c === 'X' ? '#0B0F14' : '#DCE4EC'}"/>`;
    }));
    return `<svg width="${12 * px}" height="${17 * px}" viewBox="0 0 12 17" shape-rendering="crispEdges">${r}</svg>`;
  }
  let F; // format config
  S.init = (fmt, host) => {
    F = fmt; HOST = Object.assign(HOST, host);
    const st = document.createElement('style');
    st.textContent = `
      :root{color-scheme:dark}
      html{overflow:hidden;background:#0B0F14}
      body{width:${PAGE_W}px;transform-origin:0 0}
      #__ov{position:fixed;left:0;top:0;width:${W}px;height:${H}px;pointer-events:none;z-index:2147483000}
      #__cap{position:absolute;left:${F.capX}px;bottom:${F.capY}px;max-width:${W - 2 * F.capX}px;background:#131B24;
        border:1px solid rgba(206,220,235,.14);border-left:4px solid #7E9A52;padding:${F.capPad}px ${F.capPad + 8}px;
        box-shadow:inset 3px 3px 0 rgba(255,255,255,.04),inset -3px -3px 0 rgba(0,0,0,.35),0 8px 0 rgba(0,0,0,.35);opacity:0}
      #__cap .k{font:${F.kick}px 'Silkscreen',monospace;letter-spacing:.16em;color:#7E9A52;margin-bottom:${Math.round(F.kick * .6)}px}
      #__cap .m{font:${F.main}px/1.25 'Silkscreen',monospace;color:#DCE4EC;letter-spacing:.02em}
      #__cap .s{font:${F.sub}px/1.4 'IBM Plex Mono',monospace;color:#93A1AF;margin-top:${Math.round(F.sub * .5)}px}
      #__cap .h{color:transparent}
      #__cur{position:absolute;left:0;top:0;transform-origin:0 0}
      #__fx i{position:absolute;display:block;background:#DCE4EC}
      #__end{position:absolute;inset:0;background:#0B0F14;opacity:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:${F.endGap}px}
      #__end .party{display:flex;gap:${F.endSprGap}px;align-items:flex-end;height:${F.endSprH}px}
      #__end .party>div{position:relative}
      #__end .t{font:${F.endTitle}px 'Silkscreen',monospace;letter-spacing:.06em;color:#DCE4EC}
      #__end .cmd{font:600 ${F.endCmd}px 'IBM Plex Mono',monospace;color:#DCE4EC;border:1px solid rgba(206,220,235,.14);background:#131B24;padding:${Math.round(F.endCmd * .5)}px ${F.endCmd}px;white-space:pre}
      #__end .cmd .p{color:#7E9A52}#__end .cmd .h{color:transparent}#__end .cmd .c{background:#DCE4EC;color:#0B0F14}
      #__end .l{font:${F.endLine}px 'IBM Plex Mono',monospace;color:#93A1AF;text-align:center;line-height:1.6}
    `;
    document.head.appendChild(st);
    const ov = document.createElement('div');
    ov.id = '__ov';
    ov.innerHTML = `<div id="__end"></div><div id="__cap"><div class="k"></div><div class="m"></div><div class="s"></div></div><div id="__fx"></div><div id="__cur">${cursorSvg(F.curPx)}</div>`;
    document.documentElement.appendChild(ov);
    applyCam({ cx: PAGE_W / 2, cy: H / 2 / (W / PAGE_W), s: W / PAGE_W });
  };

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const reveal = (txt, n) => esc(txt.slice(0, n)) + '<span class="h">' + esc(txt.slice(n)) + '</span>';
  let capKey = '', endBuilt = false;

  S.frame = (p) => {
    applyCam(p.cam);
    /* cursor lives in page space (like a zoomed screen recording); film.js passes its screen position */
    const cx = p.cur.x, cy = p.cur.y;
    const cur = document.getElementById('__cur');
    cur.style.display = p.cur.vis ? '' : 'none';
    cur.style.transform = `translate(${cx - 1}px,${cy - 1}px) scale(${(p.cur.press ? 0.86 : 1) * p.cur.k})`;
    /* click ripple: 8 pixels flying out */
    document.getElementById('__fx').innerHTML = p.fx.map((f) => {
      const u = clamp((p.T - f.t0) / 0.32, 0, 1);
      if (u >= 1) return '';
      const r = 6 + 26 * ease(u), q = F.curPx * 1.5;
      return [...Array(8)].map((_, i) => {
        const a = (i * Math.PI) / 4;
        return `<i style="left:${f.x + Math.cos(a) * r - q / 2}px;top:${f.y + Math.sin(a) * r - q / 2}px;width:${q}px;height:${q}px;opacity:${1 - u}"></i>`;
      }).join('');
    }).join('');
    /* caption: types on like a terminal, sub-line fades in after */
    const capEl = document.getElementById('__cap'), c = p.cap;
    if (c) {
      const key = c.k + '|' + c.m + '|' + c.s;
      if (key !== capKey) { capEl.querySelector('.k').textContent = c.k || ''; capEl.querySelector('.k').style.display = c.k ? '' : 'none'; capKey = key; }
      const el = p.T - c.t0, n = Math.floor(clamp(el * 46, 0, c.m.length));
      capEl.querySelector('.m').innerHTML = reveal(c.m, c.cont ? c.m.length : n);
      const s = capEl.querySelector('.s');
      s.style.display = c.s ? '' : 'none';
      s.textContent = c.s || '';
      s.style.opacity = clamp((el - c.m.length / 46 - 0.1) / 0.3, 0, 1);
      capEl.style.opacity = c.cont ? clamp((c.t1 - p.T) / 0.25, 0, 1) : Math.min(clamp(el / 0.15, 0, 1), clamp((c.t1 - p.T) / 0.25, 0, 1));
    } else capEl.style.opacity = 0;
    /* end card */
    const end = document.getElementById('__end');
    if (p.end) {
      if (!endBuilt) {
        end.innerHTML = `<div class="party">${DATA.bots.map((b) => '<div class="st-running">' + sprite(b, F.endSprPx) + '</div>').join('')}</div>
          <div class="t">PIXEL HQ</div><div class="cmd"></div><div class="l"></div>`;
        endBuilt = true;
      }
      const e = p.T - p.end.t0, cmd = 'hermes plugins install pixel-hq', n = Math.floor(clamp((e - 0.9) * 20, 0, cmd.length));
      end.style.opacity = clamp(e / 0.45, 0, 1);
      const caret = n < cmd.length || Math.floor((e * 1000) / 530) % 2 === 0;
      end.querySelector('.cmd').innerHTML = '<span class="p">$ </span>' + esc(cmd.slice(0, n)) + (caret ? '<span class="c">' + (cmd[n] ? esc(cmd[n]) : ' ') + '</span>' + '<span class="h">' + esc(cmd.slice(n + 1)) + '</span>' : '<span class="h">' + esc(cmd.slice(n)) + ' </span>');
      const l = end.querySelector('.l');
      l.innerHTML = p.end.lines.map(esc).join('<br>');
      l.style.opacity = clamp((e - 0.9 - cmd.length / 20 - 0.2) / 0.4, 0, 1);
    } else end.style.opacity = 0;
    /* live poll */
    if (p.live != null) window.postMessage({ pixelhqLive: liveAt(p.live) }, '*');
    /* film clock drives every CSS animation (infinite loops share one phase, finite ones start at birth) */
    const Tms = p.T * 1000;
    for (const a of document.getAnimations()) {
      if (a.playState !== 'paused') a.pause();
      if (a.effect.getTiming().iterations === Infinity) a.currentTime = Tms;
      else { if (!born.has(a)) born.set(a, Tms); a.currentTime = Tms - born.get(a); }
    }
    return { x: cx, y: cy };
  };
})();
