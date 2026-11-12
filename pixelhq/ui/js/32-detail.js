/* Detail card of the selected bot: bars, attributes, quests, achievements. */
function bars(b) {
  return '<div class="mut" style="font-size:10px">LVL ' + Number(b.lvl) + ' · ' + fmtN(b.xp) + ' XP</div>' +
    (b.xpSummon
      ? '<div class="mut" style="font-size:10px">own ' + fmtN(b.xpOwn) + ' · summons ' + fmtN(b.xpSummon) + '</div>'
      : '') +
    '<div class="bar xp"><b style="width:' + Number(b.xpPct) + '%"></b></div>' +
    '<div class="mut" style="font-size:10px;margin-top:4px">HP ' + hpTxt(b) +
    (b.n ? ' · ' + Number(b.n) + ' reviews' : ' · no reviews yet') + '</div><div class="bar hp' +
    (b.hp != null && b.hp < 75 ? ' low' : '') + '"><b style="width:' + Number(b.hp ?? 0) + '%"></b></div>';
}

function detail(b) {
  const a = b.attrs.map((v, i) =>
    '<div class="attr" title="' + ATTR_T[i] + '"><span>' + ATTR[i] + '</span><div class="bar at"><b style="width:' +
      (v == null ? 0 : Number(v) * 20) + '%"></b></div><span>' + (v == null ? '–' : Number(v)) + '</span></div>'
  ).join('');
  const qs = b.quests.map((q) =>
    '<div class="ql"><span class="s s-' + esc(q.status) + '">' + esc(q.status) + '</span><span><span class="mut">' +
      esc(q.board) + '</span> ' + esc(q.title) + '</span></div>'
  ).join('') ||
    '<div class="mut" style="font-size:11px">no open quests</div>';
  const more = b.openQuests - b.quests.length;
  const ach = b.achievements.map((x) =>
    '<span class="ach ' + esc(x[2]) + '" title="' + esc(x[1]) + '"><i></i>' + esc(x[0]) + '</span>'
  ).join('') ||
    '<span class="mut" style="font-size:11px">none yet</span>';
  document.getElementById('detail').innerHTML = '<div class="card st-' + esc(b.status) + '"><span class="lv">' +
    Number(b.lvl) + '</span><div class="top"><div class="holder">' + sprite(b, 7) + bubble(b) +
    '</div><div style="flex:1;min-width:0"><h2>' + esc(b.id) + '</h2><div class="mut" style="font-size:11px">' +
    esc(b.title) + ' · ' + esc(b.cls) + '</div><div style="margin-top:8px">' + bars(b) + '</div></div></div>' +
    '<div class="sec">STATUS</div><div class="kv"><span class="mut">Status</span><span>' + esc(ST[b.status]) +
    '</span><span class="mut">Current</span><span>' + (esc(b.quest) || '–') +
    '</span><span class="mut">Gear</span><span>' + esc(b.model) + '</span><span class="mut">Location</span><span>' +
    (esc(b.loc) || '–') + (b.gateway ? ' · gateway ' + esc(b.gateway) : '') +
    '</span><span class="mut">Last activity</span><span>' + ago(b.lastActivity) +
    '</span><span class="mut">Sessions 7 d</span><span>' + (b.sessions7d == null ? '–' : Number(b.sessions7d)) +
    '</span></div>' + chatHtml(b) + reviewHtml(b.id, null, b.quest) +
    '<div class="sec">RECORD (PASS/REVISE/FAIL)</div><div class="kv"><span class="mut">Own</span><span>' +
    b.own.map(Number).join(' / ') + '</span><span class="mut">Summons</span><span>' + b.summ.map(Number).join(' / ') +
    (b.subSessions ? ' <span class="mut">· ' + Number(b.subSessions) + ' sub-agent sessions</span>' : '') +
    '</span></div>' + '<div class="sec">ATTRIBUTES' +
    (b.attrsSource === 'kanban'
      ? ' <span class="mut">(from Kanban)</span>'
      : b.attrsSource === 'reviews'
      ? ' <span class="mut">(from reviews)</span>'
      : '') +
    '</div>' + a + '<div class="sec">QUESTS (' + Number(b.openQuests) + ' open, ' + Number(b.blocked) +
    ' blocked)</div>' + qs + (more > 0 ? '<div class="mut" style="font-size:10px">+' + more + ' more</div>' : '') +
    '<div class="sec">ACHIEVEMENTS</div>' + ach + '</div>';
  bindReviews(document.getElementById('detail'));
  bindJumps(document.getElementById('detail'));
}

function showDetail() {
  const b = DATA.bots.find((x) => x.id === sel);
  if (b) {
    detail(b);
  }
}
