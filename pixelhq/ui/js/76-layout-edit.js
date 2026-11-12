/* ---- Layout edit mode of the Office floor, part 2: the in-place controls. Every operation is a draft operation of
   72-roster-groups.js (opRoom…, opZone…, opBotZone) called by id when the control fires, so the floor and the Roster tab
   change the draft in exactly the same way.
   Hooks for browser tests (edit mode only): #floor.editing · .room[data-room] · .zone[data-dept] · .desk[data-id] ·
   select[data-move-to] · [data-edit-room-label|up|down|main|remove] · [data-edit-open-zone] · [data-edit-zone-label|left|right|
   room|remove] · [data-edit-open-room] · [data-edit-form] with [data-edit-new-id], [data-edit-new-label], [data-edit-submit],
   [data-edit-cancel]. ---- */
const layoutOff = () => rosterBusy() ? ' disabled' : '';

const editInput = (attr, label, value, max) =>
  '<input type="text" ' + attr + ' maxlength="' + max + '" value="' + esc(value) + '" aria-label="' + esc(label) + '"' +
    layoutOff() + '>';

const editButton = (attr, label, disabled, text) => rosterButton(attr, label, disabled || rosterBusy(), text);

function roomHeadEditHtml(room, at) {
  const last = rosterDraft.rooms.length - 1;
  return '<div class="room-edit">' + editInput('data-edit-room-label', 'Room name', room.label, 40) +
    editButton('data-edit-room-up', 'Move room up', at === 0, '▲') +
    editButton('data-edit-room-down', 'Move room down', at === last, '▼') +
    '<label class="edit-flag"><input type="radio" name="pixelhq-floor-main-room" data-edit-room-main' +
    (room.main === true ? ' checked' : '') + layoutOff() + '>Main</label>' +
    editButton('data-edit-open-zone', 'Add a department to this room', false, '＋ Department') +
    editButton('data-edit-room-remove', 'Remove room', room.main === true || room.zones.length > 0, 'Remove') + '</div>' +
    (layoutAdding === 'zone:' + room.id ? editFormHtml('Department ID', 'Department name', rosterNew.zone, rosterNew.label) : '');
}

function zoneHeadEditHtml(zone, room, at) {
  const others = rosterDraft.rooms.filter((other) => other !== room);
  return '<div class="zone-edit">' + editInput('data-edit-zone-label', 'Department name', zone.label, 40) +
    editButton('data-edit-zone-left', 'Move department earlier', at === 0, '◀') +
    editButton('data-edit-zone-right', 'Move department later', at === room.zones.length - 1, '▶') +
    '<select data-edit-zone-room aria-label="Move department to room"' + layoutOff() +
    '><option value="" selected>Move to room…</option>' +
    others.map((other) => rosterOption(other.id, rosterName(other), '')).join('') + '</select>' +
    editButton('data-edit-zone-remove', 'Remove department', rosterZoneUsed(zone.id), 'Remove') + '</div>';
}

function editFormHtml(idLabel, nameLabel, id, label) {
  return '<div class="edit-add" data-edit-form><label>' + esc(idLabel) +
    '<input type="text" data-edit-new-id maxlength="64" value="' + esc(id) + '"></label><label>' + esc(nameLabel) +
    '<input type="text" data-edit-new-label maxlength="40" value="' + esc(label) + '"></label>' +
    editButton('data-edit-submit', 'Add', false, 'Add') + editButton('data-edit-cancel', 'Cancel', false, 'Cancel') + '</div>';
}

function roomAddHtml() {
  return '<div class="room-add">' + editButton('data-edit-open-room', 'Add a room', false, '＋ Room') +
    (layoutAdding === 'room' ? editFormHtml('Room ID', 'Room name', rosterNew.room, rosterNew.roomLabel) : '') + '</div>';
}

function moveToHtml(b) {
  return '<select data-move-to="' + esc(b.id) + '" aria-label="' + esc('Move ' + b.id + ' to department') + '"' + layoutOff() +
    '><option value="" selected>Move to…</option>' + rosterZoneGroups('') + '</select>';
}

/* "Move to…" and the drag end in the same operation. */
function layoutMoveBot(id, zone) {
  rosterEdit(() => opBotZone(id, zone));
  flushFloor();
}

/* A render that waited for a drag (or a refused move) still has to happen. */
function flushFloor() {
  const floor = document.getElementById('floor');
  if (deferredRenders.has(floor)) {
    renderDirect(floor, deferredRenders.get(floor));
  }
}

function openEditForm(key) {
  layoutAdding = layoutAdding === key ? '' : key;
  renderRoster();
  const input = document.getElementById('floor').querySelector('[data-edit-new-id]');
  if (input) {
    input.focus();
  }
}

/* The form's values live in `rosterNew`, the same state as the inputs of the Roster tab. */
function readEditForm(form, kind, roomId) {
  const id = form.querySelector('[data-edit-new-id]').value;
  const label = form.querySelector('[data-edit-new-label]').value;
  if (kind === 'room') {
    rosterNew.room = id;
    rosterNew.roomLabel = label;
  } else {
    rosterNew.zone = id;
    rosterNew.label = label;
    rosterNew.zoneRoom = roomId;
  }
}

function submitEditForm(form, kind, roomId) {
  if (rosterBusy()) {
    return;
  }
  readEditForm(form, kind, roomId);
  const kept = layoutAdding;
  layoutAdding = '';
  if (!(kind === 'room' ? addRosterRoom() : addRosterZone())) {
    layoutAdding = kept;
    renderRoster();
  }
}

function bindEditForm(scope, kind, roomId) {
  const form = scope.querySelector('[data-edit-form]');
  if (!form) {
    return;
  }
  for (const input of [form.querySelector('[data-edit-new-id]'), form.querySelector('[data-edit-new-label]')]) {
    input.oninput = () => {
      if (!rosterBusy()) {
        readEditForm(form, kind, roomId);
      }
    };
  }
  form.querySelector('[data-edit-submit]').onclick = () => submitEditForm(form, kind, roomId);
  form.querySelector('[data-edit-cancel]').onclick = () => {
    layoutAdding = '';
    renderRoster();
  };
}

function bindFloorRoom(el) {
  const id = el.dataset.room;
  const label = el.querySelector('[data-edit-room-label]');
  label.oninput = () => rosterLive(() => opRoomLabel(id, label.value));
  el.querySelector('[data-edit-room-main]').onchange = () => rosterEdit(() => opRoomMain(id));
  el.querySelector('[data-edit-room-up]').onclick = () => rosterEdit(() => opRoomMove(id, -1));
  el.querySelector('[data-edit-room-down]').onclick = () => rosterEdit(() => opRoomMove(id, 1));
  el.querySelector('[data-edit-room-remove]').onclick = () => rosterEdit(() => opRoomRemove(id));
  el.querySelector('[data-edit-open-zone]').onclick = () => openEditForm('zone:' + id);
  bindEditForm(el, 'zone', id);
}

function bindFloorZone(el) {
  const id = el.dataset.dept;
  const label = el.querySelector('[data-edit-zone-label]');
  const target = el.querySelector('[data-edit-zone-room]');
  label.oninput = () => rosterLive(() => opZoneLabel(id, label.value));
  el.querySelector('[data-edit-zone-left]').onclick = () => rosterEdit(() => opZoneMove(id, -1));
  el.querySelector('[data-edit-zone-right]').onclick = () => rosterEdit(() => opZoneMove(id, 1));
  target.onchange = () => rosterEdit(() => target.value ? opZoneRoom(id, target.value) : false);
  el.querySelector('[data-edit-zone-remove]').onclick = () => rosterEdit(() => opZoneRemove(id));
}

function bindFloorEdit(floor) {
  floor.querySelectorAll('.room[data-room]').forEach(bindFloorRoom);
  floor.querySelectorAll('.zone[data-dept]').forEach(bindFloorZone);
  floor.querySelectorAll('[data-move-to]').forEach((select) => {
    select.onchange = () => select.value && layoutMoveBot(select.dataset.moveTo, select.value);
  });
  floor.querySelectorAll('.desk').forEach((desk) => {
    desk.onpointerdown = (e) => dragBegin(e, desk);
  });
  floor.querySelector('[data-edit-open-room]').onclick = () => openEditForm('room');
  bindEditForm(floor.querySelector('.room-add'), 'room', '');
}
