/* ---- Rooms and departments (zones) of the roster draft. Every operation keeps the draft valid: exactly one main room,
   every bot in an existing department, unique ids, at most 8 rooms and 24 departments. File keys stay rooms/zones. ---- */
const ROSTER_MAX_ROOMS = 8;
const ROSTER_MAX_ZONES = 24;
const rosterRoomById = (id) => rosterDraft.rooms.find((room) => room.id === id);
const rosterZoneTotal = () => rosterDraft.rooms.reduce((sum, room) => sum + room.zones.length, 0);
const rosterZoneUsed = (id) => rosterDraft.bots.some((bot) => bot.zone === id);
const rosterMainRoom = () => rosterDraft.rooms.find((room) => room.main === true);
const rosterName = (entry) => entry.label || entry.id;

/* Moves one entry of a list by `step`; false at the edges (nothing to do). */
function rosterSwap(list, index, step) {
  const other = index + step;
  if (other < 0 || other >= list.length) {
    return false;
  }
  [list[index], list[other]] = [list[other], list[index]];
  return true;
}

/* Text fields change the draft only (no render under the cursor, D8); structural changes render after the edit. */
function rosterLive(change) {
  if (rosterBusy()) {
    return;
  }
  change();
  rosterChanged();
}

function rosterEdit(change) {
  if (rosterBusy() || change() === false) {
    return;
  }
  rosterChanged();
  renderRoster();
}

/* The draft operations. The Roster tab and the Office floor's edit mode both call these (by id, resolved when the operation
   runs); a refused operation returns false and changes nothing. */
const rosterZoneRoom = (id) => rosterDraft.rooms.find((room) => room.zones.some((zone) => zone.id === id));
const rosterZoneById = (id) => (rosterZoneRoom(id) || { zones: [] }).zones.find((zone) => zone.id === id);

function opRoomLabel(id, value) {
  const room = rosterRoomById(id);
  if (!room) {
    return false;
  }
  room.label = value;
}

function opRoomNote(id, value) {
  const room = rosterRoomById(id);
  if (!room) {
    return false;
  }
  if (value) {
    room.note = value;
  } else {
    delete room.note;
  }
}

function opRoomMain(id) {
  if (!rosterRoomById(id)) {
    return false;
  }
  rosterDraft.rooms.forEach((other) => {
    if (other.id === id) {
      other.main = true;
    } else {
      delete other.main;
    }
  });
}

function opRoomMove(id, step) {
  const room = rosterRoomById(id);
  return !!room && rosterSwap(rosterDraft.rooms, rosterDraft.rooms.indexOf(room), step);
}

function opRoomRemove(id) {
  const room = rosterRoomById(id);
  if (!room || room.main === true || room.zones.length) {
    return false;
  }
  rosterDraft.rooms.splice(rosterDraft.rooms.indexOf(room), 1);
}

function opZoneLabel(id, value) {
  const zone = rosterZoneById(id);
  if (!zone) {
    return false;
  }
  zone.label = value;
}

function opZoneQuarantine(id, on) {
  const zone = rosterZoneById(id);
  if (!zone) {
    return false;
  }
  if (on) {
    zone.quarantine = true;
  } else {
    delete zone.quarantine;
  }
}

function opZoneRoom(id, roomId) {
  const from = rosterZoneRoom(id);
  const to = rosterRoomById(roomId);
  if (!from || !to || to === from) {
    return false;
  }
  const zone = from.zones.find((candidate) => candidate.id === id);
  from.zones.splice(from.zones.indexOf(zone), 1);
  to.zones.push(zone);
}

function opZoneMove(id, step) {
  const room = rosterZoneRoom(id);
  return !!room && rosterSwap(room.zones, room.zones.findIndex((zone) => zone.id === id), step);
}

function opZoneRemove(id) {
  const room = rosterZoneRoom(id);
  if (!room || rosterZoneUsed(id)) {
    return false;
  }
  room.zones.splice(room.zones.findIndex((zone) => zone.id === id), 1);
}

/* A bot moves to another existing department: the Office floor's drag and its "Move to…" select. */
function opBotZone(botId, zoneId) {
  const bot = rosterDraft.bots.find((candidate) => candidate.id === botId);
  if (!bot || !rosterZoneById(zoneId) || bot.zone === zoneId) {
    return false;
  }
  bot.zone = zoneId;
}

function rosterDraftProblem() {
  if (rosterDraft.rooms.filter((room) => room.main === true).length !== 1) {
    return 'Exactly one main room is required.';
  }
  const zones = new Set(rosterDraft.rooms.flatMap((room) => room.zones.map((zone) => zone.id)));
  const lost = rosterDraft.bots.find((bot) => !zones.has(bot.zone));
  return lost ? 'Bot ' + lost.id + ' needs a department.' : null;
}

const rosterButton = (attr, label, disabled, text) =>
  '<button type="button" ' + attr + ' aria-label="' + esc(label) + '"' + (disabled ? ' disabled' : '') + '>' + text + '</button>';

function rosterZoneHtml(zone, room, at) {
  const rooms = rosterDraft.rooms.map((other) => rosterOption(other.id, rosterName(other), room.id)).join('');
  return '<div class="roster-zone" data-roster-zone="' + esc(zone.id) + '"><span class="roster-id">' + esc(zone.id) + '</span>' +
    '<input type="text" data-roster-zone-label maxlength="40" value="' + esc(zone.label) + '" aria-label="Department name">' +
    '<select data-roster-zone-room aria-label="Room">' + rooms + '</select>' +
    '<label class="roster-flag"><input type="checkbox" data-roster-zone-quarantine' + (zone.quarantine === true ? ' checked' : '') +
    '>Quarantine</label>' +
    rosterButton('data-roster-zone-up', 'Move department up', at === 0, '↑') +
    rosterButton('data-roster-zone-down', 'Move department down', at === room.zones.length - 1, '↓') +
    rosterButton('data-roster-remove-zone', 'Remove department', rosterZoneUsed(zone.id), 'Remove') + '</div>';
}

function rosterRoomHtml(room, at) {
  const last = rosterDraft.rooms.length - 1;
  return '<div class="roster-room" data-roster-room="' + esc(room.id) + '"><div class="roster-room-head">' +
    '<span class="roster-id">' + esc(room.id) + '</span>' +
    '<input type="text" data-roster-room-label maxlength="40" value="' + esc(room.label) + '" aria-label="Room name">' +
    '<input type="text" data-roster-room-note maxlength="80" value="' + esc(room.note) + '" placeholder="Note" aria-label="Room note">' +
    '<label class="roster-flag"><input type="radio" name="pixelhq-main-room" data-roster-room-main' +
    (room.main === true ? ' checked' : '') + '>Main</label>' +
    rosterButton('data-roster-room-up', 'Move room up', at === 0, '↑') +
    rosterButton('data-roster-room-down', 'Move room down', at === last, '↓') +
    rosterButton('data-roster-remove-room', 'Remove room', room.main === true || room.zones.length > 0, 'Remove') + '</div>' +
    room.zones.map((zone, index) => rosterZoneHtml(zone, room, index)).join('') + '</div>';
}

function rosterGroupAddHtml() {
  const target = rosterRoomById(rosterNew.zoneRoom) ? rosterNew.zoneRoom : (rosterMainRoom() || rosterDraft.rooms[0] || {}).id;
  const rooms = rosterDraft.rooms.map((room) => rosterOption(room.id, rosterName(room), target)).join('');
  return '<div class="acts roster-add"><label>Room ID<input type="text" data-roster-new-room maxlength="64" value="' +
    esc(rosterNew.room) + '"></label><label>Room name<input type="text" data-roster-new-room-label maxlength="40" value="' +
    esc(rosterNew.roomLabel) + '"></label><button type="button" data-roster-add-room>Add room</button>' +
    '<span class="mut">Up to ' + ROSTER_MAX_ROOMS + ' rooms.</span></div>' +
    '<div class="acts roster-add"><label>Department ID<input type="text" data-roster-new-zone maxlength="64" value="' +
    esc(rosterNew.zone) + '"></label><label>Department name<input type="text" data-roster-new-zone-label maxlength="40" value="' +
    esc(rosterNew.label) + '"></label><label>In room<select data-roster-new-zone-room>' + rooms + '</select></label>' +
    '<button type="button" data-roster-add-zone>Add department</button>' +
    '<span class="mut">Up to ' + ROSTER_MAX_ZONES + ' departments in total.</span></div>';
}

function rosterGroupsHtml() {
  return '<h2>Rooms and departments</h2>' + rosterDraft.rooms.map(rosterRoomHtml).join('') + rosterGroupAddHtml();
}

function addRosterRoom() {
  if (rosterBusy()) {
    return false;
  }
  const id = rosterNew.room;
  if (!validGroupId(id)) {
    return rosterProblem('Room id: use 1–64 ASCII letters, digits or _- only.');
  }
  if (rosterRoomById(id)) {
    return rosterProblem('Room id already exists.');
  }
  if (rosterDraft.rooms.length >= ROSTER_MAX_ROOMS) {
    return rosterProblem('At most ' + ROSTER_MAX_ROOMS + ' rooms are allowed.');
  }
  const label = rosterNew.roomLabel || id;
  const ok = rosterTextTest();
  if (ok && !ok(label, 40)) {
    return rosterProblem(rosterTextMessage('Room name', 40));
  }
  rosterDraft.rooms.push({ id, label, zones: [] });
  rosterNew.room = '';
  rosterNew.roomLabel = '';
  rosterChanged();
  renderRoster();
  return true;
}

function addRosterZone() {
  if (rosterBusy()) {
    return false;
  }
  const id = rosterNew.zone;
  if (!validGroupId(id)) {
    return rosterProblem('Department id: use 1–64 ASCII letters, digits or _- only.');
  }
  if (rosterDraft.rooms.some((room) => room.zones.some((zone) => zone.id === id))) {
    return rosterProblem('Department id already exists.');
  }
  if (rosterZoneTotal() >= ROSTER_MAX_ZONES) {
    return rosterProblem('At most ' + ROSTER_MAX_ZONES + ' departments are allowed.');
  }
  const label = rosterNew.label || id;
  const room = rosterRoomById(rosterNew.zoneRoom) || rosterMainRoom() || rosterDraft.rooms[0];
  if (!room) {
    return rosterProblem('Add a room first.');
  }
  const ok = rosterTextTest();
  if (ok && !ok(label, 40)) {
    return rosterProblem(rosterTextMessage('Department name', 40));
  }
  room.zones.push({ id, label });
  rosterNew.zone = '';
  rosterNew.label = '';
  rosterChanged();
  renderRoster();
  return true;
}

function bindRosterRoom(row) {
  const id = row.dataset.rosterRoom;
  const label = row.querySelector('[data-roster-room-label]');
  const note = row.querySelector('[data-roster-room-note]');
  label.oninput = () => rosterLive(() => opRoomLabel(id, label.value));
  note.oninput = () => rosterLive(() => opRoomNote(id, note.value));
  row.querySelector('[data-roster-room-main]').onchange = () => rosterEdit(() => opRoomMain(id));
  row.querySelector('[data-roster-room-up]').onclick = () => rosterEdit(() => opRoomMove(id, -1));
  row.querySelector('[data-roster-room-down]').onclick = () => rosterEdit(() => opRoomMove(id, 1));
  row.querySelector('[data-roster-remove-room]').onclick = () => rosterEdit(() => opRoomRemove(id));
}

function bindRosterZone(row) {
  const id = row.dataset.rosterZone;
  const label = row.querySelector('[data-roster-zone-label]');
  const quarantine = row.querySelector('[data-roster-zone-quarantine]');
  const target = row.querySelector('[data-roster-zone-room]');
  label.oninput = () => rosterLive(() => opZoneLabel(id, label.value));
  target.onchange = () => rosterEdit(() => opZoneRoom(id, target.value));
  quarantine.onchange = () => rosterEdit(() => opZoneQuarantine(id, quarantine.checked));
  row.querySelector('[data-roster-zone-up]').onclick = () => rosterEdit(() => opZoneMove(id, -1));
  row.querySelector('[data-roster-zone-down]').onclick = () => rosterEdit(() => opZoneMove(id, 1));
  row.querySelector('[data-roster-remove-zone]').onclick = () => rosterEdit(() => opZoneRemove(id));
}

function bindRosterGroups(root) {
  root.querySelectorAll('[data-roster-room]').forEach(bindRosterRoom);
  root.querySelectorAll('[data-roster-zone]').forEach(bindRosterZone);
}
