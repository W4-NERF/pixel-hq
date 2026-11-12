/* Leaderboard tab: zone filter chips and the ranking table. */
function zoneFilters() {
  const zones = CFG().rooms.flatMap((r) => r.zones || []);
  document.getElementById('bfilter').innerHTML = [
    '<button class="' + (bzone === 'all' ? 'on' : '') + '" data-z="all">All</button>'
  ].concat(
    zones.map((z) =>
      '<button class="' + (bzone === z.id ? 'on' : '') + '" data-z="' + esc(z.id) + '">' + esc(z.label || z.id) +
        '</button>'
    )
  ).join('');
  document.querySelectorAll('[data-z]').forEach((b) =>
    (b.onclick = () => {
      bzone = b.dataset.z;
      board();
    })
  );
}

function board() {
  zoneFilters();
  const rows = DATA.bots.filter((b) => bzone === 'all' || b.zone === bzone).sort((x, y) =>
    bsort === 'id' ? x.id.localeCompare(y.id) : (y[bsort] ?? -1) - (x[bsort] ?? -1) || y.xp - x.xp
  );
  document.getElementById('tb').innerHTML = rows.map((b, i) =>
    '<tr data-id="' + esc(b.id) + '"><td class="rk">' + (i + 1) +
      '</td><td><span style="position:relative;display:inline-block">' + sprite(b, 3) + '</span></td><td><b>' +
      esc(b.id) + '</b><div class="mut" style="font-size:10px">' + esc(b.title) + '</div></td><td class="px">' +
      Number(b.lvl) + '</td><td><span class="mini"><span class="bar xp" style="display:block"><b style="width:' +
      Number(b.xpPct) + '%"></b></span></span>' + fmtN(b.xp) + '</td><td><span class="mini"><span class="bar hp' +
      (b.hp != null && b.hp < 75 ? ' low' : '') + '" style="display:block"><b style="width:' + Number(b.hp ?? 0) +
      '%"></b></span></span>' + hpTxt(b) + '</td><td>' + Number(b.p) + '/' + Number(b.r) + '/' + Number(b.f) +
      '</td><td>' + (b.blocked ? Number(b.blocked) : '<span class="mut">0</span>') +
      '</td><td style="white-space:nowrap"><span class="dot d-' + esc(liveStatus(b).status) + '"></span>' +
      esc(ST[liveStatus(b).status]) + '</td><td class="qcell" title="' + esc(b.quest) + '">' +
      (esc(b.quest) || '<span class="mut">–</span>') + '</td><td class="mut">' + esc(b.model) + '</td></tr>'
  ).join('');
  document.querySelectorAll('#tb tr').forEach((tr) =>
    (tr.onclick = () => {
      sel = tr.dataset.id;
      tab('office');
    })
  );
  document.getElementById('log2').innerHTML = logHtml();
}
