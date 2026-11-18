/* ---- Blocked tab, cards of other hosts (round 5 §3): one read-only section per source. No action buttons, no text areas,
   and none of these cards is part of the triage selection (which is built from DATA.blockers, the local cards, only).
   The category and age filters apply here too; the board filter does not (its chips name the local boards). ---- */
const remoteCardShown = (c) => (bcat === 'all' || c.cat === bcat) && (!bstale || c.stale);

function remoteCardHtml(c) {
  const bot = DATA.bots.find((x) => x.id === c.bot) || { id: c.assignee, color: palette().fallback, zone: '' };
  return '<div class="bi rbi c-' + esc(c.cat) + '" data-remote-card="' + esc(c.key) + '"><div class="bh"><span><span class="ctag">' +
    esc((CAT[c.cat] || [c.cat])[0]) + '</span></span><span class="t" title="' + esc(c.title) + '">' + esc(c.title) +
    '</span><span class="who"><span style="position:relative;display:inline-block">' + sprite(bot, 2) + '</span>' + esc(c.assignee) +
    '</span><span class="' + (c.stale ? 'old' : 'mut') + '" style="font-size:11px;text-align:right">' + Number(c.ageDays) + ' d' +
    (c.sourceStale === true ? '<span class="host stale" title="' + esc('Stale data, ' + asOfText(c.asOf)) + '">stale</span>' : '') +
    '</span></div><div class="br"><span class="mut">' + esc(c.board) + ' · ' + esc(c.id) + ' —</span> ' +
    (esc(c.reason) || '<span class="mut">no reason recorded</span>') + '</div></div>';
}

function remoteSectionHtml(src, all) {
  const name = src.source || src.name;
  const mine = all.filter((c) => c.source === name);
  const shown = mine.filter(remoteCardShown);
  const rows = shown.map(remoteCardHtml).join('') ||
    '<div class="mut">' + (mine.length ? 'no cards in this selection' : 'no blocked cards (or no data)') + '</div>';
  return '<div class="rsrc" data-remote-section="' + esc(name) + '"><div class="rsh"><span class="host">' + esc(name) + '</span> ' +
    '<span class="mut">' + esc(src.text) + ' · ' + shown.length + ' of ' + mine.length + ' blocked · read-only · ' +
    esc(hostHint({ remote: true, source: name })) + '</span></div>' + rows + '</div>';
}

function renderRemoteBlocked() {
  const all = Array.isArray(DATA.remoteBlockers) ? DATA.remoteBlockers : [];
  const sources = Array.isArray(DATA.remoteSources) ? DATA.remoteSources : [];
  document.getElementById('rlist').innerHTML = sources.map((src) => remoteSectionHtml(src, all)).join('');
}
