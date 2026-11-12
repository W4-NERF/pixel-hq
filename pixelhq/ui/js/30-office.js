/* Event log, desk selection, rooms with their zones, first-run banner and the Office floor. */
function evk(kind) {
  const x = CFG().xp;
  const sg = (n) => (n > 0 ? '+' : '') + n;
  return {
    'qc-pass': [sg(x.pass) + ' XP · QC pass', 'ok'],
    'qc-revise': [sg(x.revise) + ' XP · revision', 'warn'],
    'qc-fail': [sg(x.fail) + ' XP · QC fail', 'bad'],
    completed: ['quest completed', 'ok'],
    blocked: ['quest blocked', 'bad'],
    changes_requested: ['changes requested', 'warn'],
    gave_up: ['gave up', 'bad'],
    timed_out: ['timed out', 'bad'],
    protocol_violation: ['protocol violation', 'warn'],
    suspected_hallucinated_references: ['mirage: hallucinated reference', 'bad'],
    created: ['new quest', '']
  }[kind] ||
    [kind, ''];
}

function logHtml() {
  return DATA.events.map((e) => {
    const k = e.selfReview ? ['self-review · no XP', ''] : evk(e.kind);
    return '<div class="ev ' + k[1] + '"><span class="t">' + clock(e.ts) + '</span> <b>' + esc(e.bot) + '</b>' +
      (e.summon ? ' <span class="mut">(summon)</span>' : '') + ' · ' + esc(k[0]) + '<div class="mut2">' + esc(e.text) +
      '</div></div>';
  }).join('') ||
    '<div class="ev">no events</div>';
}

function select(id) {
  sel = id;
  document.querySelectorAll('.desk').forEach((d) => d.classList.toggle('sel', d.dataset.id === id));
  renderUnlessFocused(document.getElementById('detail'), showDetail);
}

/* `edit` draws the rooms of the roster draft with the in-place controls of 76-layout-edit.js; otherwise the snapshot's rooms. */
function roomsHtml(edit) {
  const rooms = edit ? rosterDraft.rooms : CFG().rooms || [];
  const main = rooms.find((r) => r.main) || rooms[0];
  const zoneHtml = (z, room, at) =>
    '<div class="zone' + (z.quarantine ? ' q' : '') + '" data-dept="' + esc(z.id) + '">' +
      (edit ? zoneHeadEditHtml(z, room, at) : '<h4>' + esc(z.label || z.id) + '</h4>') +
      statsHtml(zoneStats(z.id, edit), 'department') + '<div class="desks" data-zone="' + esc(z.id) + '"></div></div>';
  const roomHtml = (r, at) =>
    '<div class="room' + (r === main ? ' main' : '') + '" data-room="' + esc(r.id) + '">' +
      (edit ? roomHeadEditHtml(r, at) : '<h3>' + esc(r.label || r.id) + '</h3>') +
      statsHtml(roomStats(r.id, edit), 'room') +
      (r.zones || []).map((z, i) => zoneHtml(z, r, i)).join('') +
      (r.note ? '<div class="mut" style="font-size:10px;margin-top:8px">' + esc(r.note) + '</div>' : '') + '</div>';
  return rooms.map(roomHtml).join('') + '<div class="room"><h3>REACTOR</h3><div id="rack"></div></div>' +
    (edit ? roomAddHtml() : '');
}

/* One desk. In edit mode the bot's department comes from the draft (`zone`), everything else from the snapshot. */
function deskHtml(b, edit) {
  const lst = liveStatus(b).status;
  return '<div class="desk st-' + esc(lst) + (ofilter !== 'all' && lst !== ofilter ? ' dim' : '') +
    '" tabindex="0" data-id="' + esc(b.id) + '" title="' + esc(b.id) + ' – ' + esc(ST[lst]) +
    (b.quest ? ': ' + esc(b.quest) : '') + '"><div class="holder">' + sprite(b, 4) + bubble(b) +
    '</div><div class="tbl"></div><div class="nm">' + esc(b.id) +
    '</div><div class="mut" style="font-size:9px">LVL ' + Number(b.lvl) + ' · HP ' + hpTxt(b) + '</div>' +
    (edit ? moveToHtml(b) : '') + '</div>';
}

/* The bots on the floor: the snapshot's, or in edit mode the draft's bots (placement) joined with their snapshot data. */
function floorBots(edit) {
  if (!edit) {
    return DATA.bots;
  }
  return rosterDraft.bots.map((draftBot) => {
    const shown = DATA.bots.find((b) => b.id === draftBot.id) ||
      { lvl: 1, hp: null, status: 'idle', quest: '', blocked: 0, ...draftBot };
    return { ...shown, zone: draftBot.zone };
  });
}

function drawFloor() {
  const edit = layoutEditing();
  if (edit) {
    rosterEnsureDraft();
  }
  const floor = document.getElementById('floor');
  floor.innerHTML = roomsHtml(edit);
  floor.classList.toggle('editing', edit);
  floor.style.setProperty('--side', Math.max(1, (edit ? rosterDraft.rooms : CFG().rooms || []).length));
  const zones = new Map();
  floor.querySelectorAll('[data-zone]').forEach((el) => {
    zones.set(el.dataset.zone, el);
  });
  const fallback = zones.values().next().value;
  floorBots(edit).forEach((b) => {
    const el = zones.get(b.zone) || fallback;
    if (el) {
      el.insertAdjacentHTML('beforeend', deskHtml(b, edit));
    }
  });
  floor.querySelectorAll('.desk').forEach((d) => {
    d.onclick = () => deskClick(d.dataset.id);
    d.onkeydown = (e) => {
      if (e.key === 'Enter') {
        select(d.dataset.id);
      }
    };
  });
  document.getElementById('rack').innerHTML = reactorHtml(DATA.reactor);
  document.querySelectorAll('.desk').forEach((d) => d.classList.toggle('sel', d.dataset.id === sel));
  if (edit) {
    bindFloorEdit(floor);
  }
}

/* A click after a drag (the browser sends one on the desk the pointer is released over) is not a selection. */
function deskClick(id) {
  if (dragClickBlock) {
    dragClickBlock = false;
    return;
  }
  select(id);
}

/* ---- First-run guidance; dismiss is intentionally page-local ---- */
let firstRunDismissed = false;

function renderBanner() {
  const el = document.getElementById('first-run');
  document.getElementById('rostertab').style.display = EMBED ? '' : 'none';
  const forced = window.parent === window && DATA.demo && new URLSearchParams(location.search).get('firstrun') === '1';
  const visible = !firstRunDismissed && (CFG().rosterSource === 'generated' || forced);
  el.style.display = visible ? '' : 'none';
  if (!visible) {
    return;
  }
  const count = DATA.bots.filter((bot) => !bot.remote).length;
  el.innerHTML = esc('Roster generated from your ' + count + ' profiles. Give your bots roles, colours and rooms.') +
    '<div class="acts"><button type="button" data-roster-customise' +
    (EMBED ? '' : ' disabled title="Add ?actions=1 to enable the standalone editor"') +
    '>Customise roster</button><button type="button" data-roster-dismiss>Dismiss</button></div>';
  el.querySelector('[data-roster-customise]').onclick = () => tab('roster');
  el.querySelector('[data-roster-dismiss]').onclick = () => {
    firstRunDismissed = true;
    el.style.display = 'none';
  };
}

function office() {
  renderBanner();
  renderLayoutBar();
  renderUnlessFocused(document.getElementById('floor'), drawFloor);
  if (!sel || !DATA.bots.find((b) => b.id === sel)) {
    sel = (DATA.bots.find((b) => b.leader) || DATA.bots[0] || {}).id;
  }
  select(sel);
  document.getElementById('log1').innerHTML = logHtml();
}
