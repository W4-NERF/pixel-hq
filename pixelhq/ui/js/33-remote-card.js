/* ---- Character card of a bot of another host (round 5 §3): the facts the document holds, read-only. There is no Talk,
   Open, Ask for status, Rate or Config/SOUL control: the card names the host where those actions exist instead. ---- */
const hostBars = (b) =>
  '<div class="mut" style="font-size:10px">LVL ' + Number(b.lvl) + ' · ' + fmtN(b.xp) + ' XP</div>' +
  '<div class="bar xp"><b style="width:' + Number(b.xpPct) + '%"></b></div>' +
  '<div class="mut" style="font-size:10px;margin-top:4px">HP ' + hpTxt(b) + '</div><div class="bar hp' +
  (b.hp != null && b.hp < 75 ? ' low' : '') + '"><b style="width:' + Number(b.hp ?? 0) + '%"></b></div>';

function hostFacts(b) {
  const row = (name, value) => '<span class="mut">' + esc(name) + '</span><span>' + (esc(value) || '–') + '</span>';
  const status = ST[hostStatus(b).status] || '';
  const known = b.stale === true ? 'Last known ' : '';  // old data never reads as live (the live tab says `last step:`)
  return '<div class="kv">' + row('Status', status + (b.stale === true ? ' (stale)' : '')) + row('Current', b.quest) +
    row(known ? known + 'step' : 'Step', b.currentStep) + row(known ? known + 'tool' : 'Last tool', b.lastTool) + row('Gear', b.model) +
    row('Last activity', b.lastActivity ? ago(b.lastActivity) : '') + row('Data', asOfText(b.asOf)) +
    row('Source', hostOf(b) + (b.sourceState ? ' · ' + b.sourceState : '')) + '</div>';
}

/* The blocked cards of this bot from the document (title and reason only, no controls). */
function hostCardList(b) {
  const cards = (DATA.remoteBlockers || []).filter((c) => c.bot === b.id);
  const rows = cards.slice(0, 12).map((c) =>
    '<div class="ql"><span class="s s-blocked">' + esc((CAT[c.cat] || [c.cat])[0]) + '</span><span><span class="mut">' +
      esc(c.board) + '</span> ' + esc(c.title) + '</span></div>'
  ).join('') ||
    '<div class="mut" style="font-size:11px">no blocked cards</div>';
  const more = cards.length - 12;
  return '<div class="sec">BLOCKED CARDS (' + cards.length + ')</div>' + rows +
    (more > 0 ? '<div class="mut" style="font-size:10px">+' + more + ' more</div>' : '');
}

function hostDetail(b) {
  document.getElementById('detail').innerHTML = '<div class="card remote st-' + esc(hostStatus(b).status) + '" data-remote-card="' +
    esc(b.id) + '"><span class="lv">' + Number(b.lvl) + '</span><div class="top"><div class="holder">' + sprite(b, 7) +
    bubble(b) + '</div><div style="flex:1;min-width:0"><h2>' + esc(botLabel(b)) + '</h2><div>' + hostBadges(b) +
    '</div><div class="mut" style="font-size:11px;margin-top:4px">' + esc(b.title) + ' · ' + esc(b.cls) +
    '</div><div style="margin-top:8px">' + hostBars(b) + '</div></div></div><div class="note hostnote" data-remote-hint>' +
    esc(hostHint(b)) + '</div><div class="sec">STATUS</div>' + hostFacts(b) + hostCardList(b) + '</div>';
}
