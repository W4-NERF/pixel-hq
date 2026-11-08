#!/usr/bin/env node
/* Pixel HQ demo film — renders the standalone demo page (synthetic demo data only, never the real app)
 * frame by frame in headless Chromium and pipes the frames into ffmpeg.
 *
 *   python3 ../../pixelhq/render.py --demo  # first: build dist/pixel-hq.html from synthetic data
 *   node film.js                          # 16:9, 30 fps draft  -> pixel-hq-demo-16x9.mp4
 *   node film.js --format=4x5 --fps=60    # 4:5 feed cut (X)
 *   node film.js --fps=60 --audio         # adds a silent AAC track (some uploaders want one)
 *
 * Needs: node, playwright (+ its chromium), ffmpeg (FFMPEG=/path/to/ffmpeg to override).
 * Deterministic: a virtual clock drives timers and every CSS animation, so each run gives identical frames.
 */
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const args = Object.fromEntries(process.argv.slice(2).map((a) => { const [k, v] = a.replace(/^--/, '').split('='); return [k, v ?? true]; }));
const FMT = args.format || '16x9';
const FPS = +(args.fps || 30);
const PAGE = path.resolve(args.page || path.join(__dirname, '..', '..', 'dist', 'pixel-hq.html')); // python3 pixelhq/render.py --demo
const OUT = path.resolve(args.out || `pixel-hq-demo-${FMT}.mp4`);
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const ONLY = args.until ? +args.until : Infinity; // stop early (seconds) for quick checks

/* What the stand-in host answers — mirrors the real plugin's wording (see pixelhq/actions.py and
 * desktop/plugin.js). Placeholders: {board} {id} {n} {orchestrator} */
const HOST_TEXT = {
  // real wording of the Hermes host: pixelhq/actions.py -> "<label>: <id> <before> → <after>." and
  // desktop/plugin.js -> 'Triage chat "<title>" with <n> cards started and opened.' (title = "Blocked-card triage <dd/mm, HH:MM>")
  answer: 'Answer & unblock: {id} blocked → ready.',
  triage: 'Triage chat "Blocked-card triage 08/11, 13:20" with {n} cards started and opened.',
  latency: 700,
};

const FORMATS = {
  '16x9': { name: '16x9', W: 1920, H: 1080, capX: 56, capY: 52, capPad: 18, kick: 17, main: 40, sub: 22, curPx: 2, safeB: 200,
    endGap: 34, endSprGap: 28, endSprH: 76, endSprPx: 7, endTitle: 64, endCmd: 34, endLine: 22 },
  '4x5': { name: '4x5', W: 1080, H: 1350, capX: 36, capY: 44, capPad: 16, kick: 16, main: 34, sub: 20, curPx: 2, safeB: 250,
    endGap: 30, endSprGap: 12, endSprH: 64, endSprPx: 6, endTitle: 56, endCmd: 28, endLine: 19 },
};
const F = FORMATS[FMT];
if (!F) throw new Error('unknown format ' + FMT);

/* ---------- director state ---------- */
let page, ff, T = 0;
let cam, camTw = null;
const cur = { px: 1250, py: 760, vis: true, press: false };
let curTw = null, cap = null, end = null, mouse = { x: -1, y: -1 }, nextLive = 0;
const fx = [];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
let seed = 7;
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

function camNow() {
  if (!camTw) return cam;
  const u = ease(clamp((T - camTw.t0) / camTw.dur, 0, 1)), a = camTw.from, b = camTw.to;
  const c = { cx: a.cx + (b.cx - a.cx) * u, cy: a.cy + (b.cy - a.cy) * u, s: Math.exp(Math.log(a.s) + (Math.log(b.s) - Math.log(a.s)) * u) };
  if (T >= camTw.t0 + camTw.dur) { cam = b; camTw = null; }
  return c;
}
function camTo(to, dur) { camTw = { from: camNow(), to, t0: T, dur }; }
function curPage() {
  if (!curTw) return { x: cur.px, y: cur.py };
  const u = ease(clamp((T - curTw.t0) / curTw.dur, 0, 1));
  const dx = curTw.tx - curTw.fx, dy = curTw.ty - curTw.fy, d = Math.hypot(dx, dy) || 1, arc = Math.sin(Math.PI * u) * d * 0.06;
  const p = { x: curTw.fx + dx * u - (dy / d) * arc, y: curTw.fy + dy * u + (dx / d) * arc };
  if (T >= curTw.t0 + curTw.dur) { cur.px = curTw.tx; cur.py = curTw.ty; curTw = null; }
  return p;
}
const toScreen = (p, c) => ({ x: F.W / 2 + (p.x - c.cx) * c.s, y: F.H / 2 + (p.y - c.cy) * c.s });

async function frame() {
  await page.clock.runFor(1000 / FPS);
  const c = camNow(), sp = toScreen(curPage(), c);
  let live = null;
  if (T >= nextLive) { live = T; nextLive += 1; }
  const p = { T, cam: c, cur: { x: sp.x, y: sp.y, vis: cur.vis, press: cur.press, k: Math.sqrt(c.s) },
    cap: cap && T < cap.t1 ? cap : null, fx: fx.filter((f) => T - f.t0 < 0.4), end, live };
  await page.evaluate((p) => window.__stage.frame(p), p);
  if (Math.abs(sp.x - mouse.x) > 0.05 || Math.abs(sp.y - mouse.y) > 0.05) { await page.mouse.move(sp.x, sp.y); mouse = sp; }
  const buf = await page.screenshot({ type: 'png', caret: 'initial' });
  if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  T += 1 / FPS;
  if (T > ONLY) throw new Error('STOP');
}
async function until(t) { while (T < t - 1e-6) await frame(); }
const wait = (s) => until(T + s);

async function rect(sel) {
  const sels = Array.isArray(sel) ? sel : [sel];
  const rs = await page.evaluate((ss) => ss.map((s) => window.__stage.pageRect(s)), sels);
  if (rs.some((r) => !r)) throw new Error('not found: ' + sels.join(', '));
  const x = Math.min(...rs.map((r) => r.x)), y = Math.min(...rs.map((r) => r.y));
  return { x, y, w: Math.max(...rs.map((r) => r.x + r.w)) - x, h: Math.max(...rs.map((r) => r.y + r.h)) - y };
}
/* camera that frames a page rect inside the area above the caption band */
function frameRect(r, o = {}) {
  const pad = o.pad ?? 24, safeB = o.safe === false ? 0 : F.safeB, sMin = F.W / 1920;
  const s = clamp(Math.min(F.W / (r.w + 2 * pad), (F.H - safeB) / (r.h + 2 * pad)), sMin, o.maxS ?? 2.4);
  const hw = F.W / (2 * s), hh = F.H / (2 * s);
  return { cx: clamp(r.x + r.w / 2, hw, 1920 - hw), cy: Math.max(r.y + r.h / 2 + safeB / (2 * s), hh), s };
}
const focus = async (sel, o) => frameRect(await rect(sel), o);
const full = () => (F.name === '16x9' ? { cx: 960, cy: 540, s: 1 } : frameRect({ x: 0, y: 0, w: 1100, h: 860 }, { pad: 0, safe: false }));
/* camera that keeps a header control reachable (16:9: whole page; 4:5: the half it sits in) */
async function nav(sel) {
  if (F.name === '16x9') return full();
  const r = await rect(sel);
  return frameRect({ x: clamp(r.x + r.w / 2 - 560, 0, 820), y: 0, w: 1100, h: 860 }, { pad: 0, safe: false });
}

async function moveTo(sel, dur = 0.8, o = {}) {
  const r = await rect(sel), p = curPage();
  curTw = { fx: p.x, fy: p.y, tx: r.x + r.w * (o.ox ?? 0.5), ty: r.y + r.h * (o.oy ?? 0.5), t0: T, dur };
  if (!o.async) await wait(dur + 0.05);
}
async function click() {
  const sp = toScreen(curPage(), camNow());
  fx.push({ x: sp.x, y: sp.y, t0: T });
  cur.press = true;
  await page.mouse.down();
  await wait(0.07);
  await page.mouse.up();
  cur.press = false;
  await wait(0.03);
}
async function type(text, cps = 15) {
  for (const ch of text) { await page.keyboard.type(ch); await wait((0.6 + 0.8 * rnd()) / cps + (ch === ' ' ? 0.03 : 0) + (ch === '.' ? 0.18 : 0)); }
}
function caption(k, m, s, dur) { cap = { k, m, s: s || '', t0: T, t1: T + dur }; }

/* ---------- the film ---------- */
async function film() {
  const K = 'PIXEL HQ · A HERMES AGENT PLUGIN';
  const wide = F.name === '16x9';
  cam = full();

  // 1 · cold open: the floor, slow push in
  camTo(await focus(wide ? '#floor' : '#floor .room.main', { pad: 12 }), 6.4);
  await wait(0.35);
  caption(K, 'Nine bots. Fourteen blocked cards.', '', 3.0);
  await wait(3.15);
  caption(K, 'Which ones are waiting on you?', '', 3.4);
  await wait(1.0);
  await moveTo('.desk[data-id="devops"]', 1.4, { oy: 0.45 });
  await wait(0.5);

  // 2 · office: one click, the character card
  await click();
  camTo(wide ? await focus('#detail .card', { pad: 16, maxS: 1.6, safe: false }) : await focus('#detail .card', { pad: 12, maxS: 2 }), 1.2);
  await moveTo('#detail .card .bar.hp', 1.3, { ox: 0.7, async: true });
  caption('OFFICE', 'Every Hermes profile is a character.', 'Level, XP and HP come from its QC reviews.', 5.0);
  await wait(5.2);

  // 3 · live: what every bot is doing right now
  camTo(await nav('[data-tab="live"]'), 0.9);
  await moveTo('[data-tab="live"]', 0.95);
  await click();
  await wait(0.25);
  camTo(await focus('#lactive .lc', { pad: 16, maxS: 2.0 }), 1.3);
  await moveTo('#lactive .lc .ls.sub', 1.3, { ox: 0.55, oy: 0.35, async: true });
  caption('LIVE', 'What every bot is doing right now.', 'Down to the tool call, and the sub-agents it spawned.', 5.8);
  await wait(6.0);

  // 4 · blocked: find the cards that wait for you, answer one
  camTo(await nav('#blktab'), 0.9);
  await moveTo('#blktab', 0.95);
  await click();
  caption('BLOCKED', 'Every blocked card, sorted by why.', '', 3.0);
  await wait(1.1);
  await moveTo('[data-bc="you"]', 0.8);
  await wait(0.3);
  await click();
  const bl = await rect(['#bcats', '#blist']);
  camTo(frameRect(wide ? bl : { x: bl.x, y: bl.y, w: 1000, h: bl.h }, { pad: 16, maxS: 1.45 }), 1.0);
  caption('BLOCKED', 'Four of them are waiting on you.', '', 2.9);
  await wait(0.9);
  const card = '.bi[data-k="security/t_842e7fc2"]';
  await moveTo(card + ' .bh', 0.8, { ox: 0.25 });
  await wait(0.2);
  await click();
  await wait(0.1);
  const cr = await rect(card);
  camTo(frameRect({ x: cr.x, y: cr.y, w: wide ? 980 : 760, h: cr.h + 40 }, { pad: 20, maxS: 2.0 }), 1.0);
  await moveTo(card + ' textarea', 0.9, { ox: 0.08, oy: 0.45 });
  await click();
  caption('ANSWER & UNBLOCK', 'Answer it right here.', '', 3.4);
  await wait(0.2);
  await type('Keep 90-day retention. Go ahead.');
  await wait(0.2);
  await moveTo(card + ' [data-act="answer"]', 0.7);
  await click(); // arms
  caption('ANSWER & UNBLOCK', 'Second click confirms.', '', 1.6);
  await wait(1.0);
  await click(); // confirms -> running … -> host reply
  await wait(0.9);
  caption('ANSWER & UNBLOCK', 'Your answer becomes the unblock reason.', 'The bot picks up from there.', 3.4);
  await moveTo(card + ' .res', 0.8, { ox: 0.9, oy: 1.6, async: true });
  await wait(3.0);
  camTo(await nav('#reload'), 1.0);
  await moveTo('#reload', 1.1);
  await wait(0.15);
  await click();
  await wait(0.55);
  // the counters after the reload: tab, HUD and chip all say 13 / 3 now
  camTo(frameRect(wide ? { x: 0, y: 0, w: 1160, h: 300 } : { x: 380, y: 0, w: 780, h: 300 }, { pad: 12 }), 0.9);
  await moveTo('#hud', 0.9, { ox: wide ? 0.5 : 0.48, oy: 0.95, async: true });
  caption('BLOCKED', 'Thirteen to go.', '', 2.4);
  await wait(2.4);

  // 5 · triage run: hand the rest to the orchestrator
  camTo(await nav('[data-bc="all"]'), 0.8);
  await moveTo('[data-bc="all"]', 0.9);
  await click();
  await wait(0.2);
  if (!wide) camTo(await nav('#btriage'), 0.9);
  await moveTo('#btriage', 1.0, { ox: 0.6 });
  await click(); // arms
  caption('TRIAGE RUN', 'Or hand the rest to your orchestrator.', 'One decision package. Nothing changes without your go.', 5.4);
  await wait(1.1);
  await click(); // confirms
  await wait(0.3);
  const br = await rect(['#bres', '#bcats']);
  camTo(frameRect({ x: 0, y: br.y - 8, w: wide ? 1050 : 820, h: br.h + 70 }, { pad: 18, maxS: 1.9 }), 1.0);
  await moveTo('#bres', 1.0, { ox: 0.42, oy: 1.3, async: true });
  await wait(3.9);

  // 6 · leaderboard
  camTo(await nav('[data-tab="board"]'), 0.9);
  await moveTo('[data-tab="board"]', 1.0);
  await click();
  caption('LEADERBOARD', "And yes, there's a leaderboard.", '', 3.8);
  const tbr = await rect('#board table');
  camTo(frameRect(wide ? tbr : { x: tbr.x, y: tbr.y, w: 900, h: tbr.h }, { pad: 16, maxS: 1.35 }), 1.2);
  await moveTo('th[data-k="hp"]', 1.0);
  await click();
  await wait(2.0);

  // 7 · end card
  cur.vis = false;
  end = { t0: T, lines: ['github.com/W4-NERF/pixel-hq · MIT', 'Hermes Agent Plugin Hackathon'] };
  await wait(5.6);
}

(async () => {
  const b = await chromium.launch();
  page = await b.newPage({ viewport: { width: F.W, height: F.H }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.error('pageerror', e.message));
  const html = fs.readFileSync(PAGE, 'utf8');
  if (!/"demo":\s*true/.test(html)) throw new Error('refusing: page does not carry demo data (render.py --demo)');
  const t0 = parseFloat((html.match(/"generated":\s*([\d.]+)/) || [0, Date.now() / 1000])[1]);
  await page.clock.install({ time: t0 * 1000 });
  await page.goto('file://' + PAGE + '?actions=1');
  await page.clock.pauseAt(t0 * 1000 + 5000);
  if (!(await page.evaluate(() => DATA && DATA.demo === true))) throw new Error('refusing: DATA.demo is not true');
  await page.addScriptTag({ path: path.join(__dirname, 'stage.js') });
  await page.evaluate(([f, h]) => window.__stage.init(f, h), [F, HOST_TEXT]);
  await page.evaluate(() => document.fonts.ready);

  const audio = args.audio ? ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo'] : [];
  ff = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-', ...audio,
    '-c:v', 'libx264', '-preset', args.preset || 'veryfast', '-crf', String(args.crf || 16), '-pix_fmt', 'yuv420p', '-r', String(FPS),
    ...(args.audio ? ['-c:a', 'aac', '-b:a', '64k', '-shortest'] : []), '-movflags', '+faststart', OUT], { stdio: ['pipe', 'inherit', 'inherit'] });
  const started = Date.now();
  try { await film(); } catch (e) { if (e.message !== 'STOP') { console.error(e); } }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
  await b.close();
  console.log(`${OUT}  ${T.toFixed(2)} s  ${FMT} @${FPS}  rendered in ${((Date.now() - started) / 1000).toFixed(0)} s`);
})();
