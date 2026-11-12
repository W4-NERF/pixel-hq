/* ---- Department numbers (round-3 §4): members · active · blocked · Ø HP · XP for every department header and the totals
   for every room header. `zoneStats` / `roomStats` are pure readers of DATA, LIVE and (edit mode) the roster draft; they
   change nothing and render nothing. Membership is `bot.zone`; in edit mode it comes from the draft, every value from the
   snapshot (the same join the floor uses). ---- */

/* 1234 -> "1.2k", 12345 -> "12k", 1000 -> "1k", 2500000 -> "2.5M". Below 1000 the plain integer. */
function compactN(n) {
  const v = Math.max(0, Math.round(Number(n) || 0));
  if (v < 1000) {
    return String(v);
  }
  const units = [[1e3, 'k'], [1e6, 'M'], [1e9, 'G']];
  for (let i = 0; i < units.length; i++) {
    const x = v / units[i][0];
    const r = x < 10 ? Math.round(x * 10) / 10 : Math.round(x);
    if (r < 1000 || i === units.length - 1) {
      return r + units[i][1];
    }
  }
  return String(v);
}

/* The numbers of a set of bots; `blockers` are the cards of the snapshot (the Blocked tab's rows). */
function statsOfBots(bots) {
  const ids = new Set(bots.map((b) => b.id));
  const hps = bots.map((b) => b.hp).filter((hp) => hp != null && Number.isFinite(Number(hp))).map(Number);
  return {
    members: bots.length,
    active: bots.filter((b) => liveStatus(b).status === 'running').length,
    blocked: (DATA.blockers || []).filter((card) => ids.has(card.assignee)).length,
    hp: hps.length ? Math.round(hps.reduce((a, b) => a + b, 0) / hps.length) : null,
    hpCount: hps.length,
    xp: bots.reduce((sum, b) => sum + (Number(b.xp) || 0), 0)
  };
}

function zoneStats(zoneId, edit) {
  return statsOfBots(floorBots(!!edit).filter((b) => b.zone === zoneId));
}

function roomStats(roomId, edit) {
  const room = (edit ? rosterDraft.rooms : CFG().rooms || []).find((r) => r.id === roomId);
  const zones = new Set(((room && room.zones) || []).map((z) => z.id));
  return statsOfBots(floorBots(!!edit).filter((b) => zones.has(b.zone)));
}

/* One number with its tooltip; `what` names the thing counted ("department" or "room"). */
function statHtml(text, tip, cls) {
  return '<span class="stat' + (cls ? ' ' + cls : '') + '" title="' + esc(tip) + '">' + esc(text) + '</span>';
}

function statsHtml(s, what) {
  const plural = (n, one) => n + ' ' + one + (n === 1 ? '' : 's');
  return '<div class="stats">' +
    statHtml(String(s.members), 'Members: ' + plural(s.members, 'bot') + ' in this ' + what, 'm') +
    statHtml(String(s.active), 'Active: ' + s.active + ' of ' + plural(s.members, 'member') + ' working right now', 'a') +
    statHtml(
      String(s.blocked),
      'Blocked: ' + plural(s.blocked, 'blocked Kanban card') + ' assigned to a member',
      s.blocked ? 'b hot' : 'b'
    ) +
    statHtml(
      'Ø ' + (s.hp == null ? '–' : s.hp + '%'),
      s.hp == null
        ? 'Average HP: none of the members has an HP value yet'
        : 'Average HP: mean of the ' + plural(s.hpCount, 'HP value') + ' of the members, rounded',
      'h'
    ) +
    statHtml(compactN(s.xp) + ' XP', 'XP: sum of the members\' XP (' + fmtN(s.xp) + ')', 'x') + '</div>';
}
