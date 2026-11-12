/* ---- Roster drafts are page-local and never contain snapshot counters ---- */
/* D9: `rosterSaved` is the payload of the last successful Save; it is the editor's base until a new snapshot
   arrives while the editor is clean. Rooms and departments (zones) are edited in 72-roster-groups.js on the same draft. */
let rosterDraft = null;
let rosterDirty = false;
let rosterSaved = null;
let rosterEditing = '';
const rosterTrips = hostTrips(TRIP_MS.other, () => renderRoster());
const rosterBusy = () => rosterTrips.busy('roster');
const rosterResult = () => rosterTrips.result('roster');
const rosterNew = { bot: '', zone: '', label: '', zoneRoom: '', room: '', roomLabel: '' };
const ROSTER_BOT_KEYS = ['id', 'cls', 'title', 'zone', 'loc', 'color', 'leader', 'remote', 'sprite'];
const rosterPick = (value, keys) =>
  Object.fromEntries(keys.filter((key) => Object.hasOwn(value, key)).map((key) => [key, value[key]]));
const rosterClone = (value) => JSON.parse(JSON.stringify(value));

/* Rooms come over complete (keys the editor never touches pass through unchanged; a room without a zone list gets an
   empty one); bots are the roster's schema keys only, because snapshot bots also carry counters. */
function rosterFromSnapshot() {
  const rooms = rosterClone(CFG().rooms).map((room) => Object.assign({}, room, { zones: room.zones || [] }));
  return { rooms, bots: DATA.bots.map((bot) => rosterPick(bot, ROSTER_BOT_KEYS)) };
}

function rosterInput(label, field, value) {
  return '<input type="text" data-roster-field="' + esc(field) + '" value="' + esc(value) + '" maxlength="40" aria-label="' +
    esc(label) + '">';
}

const rosterOption = (id, text, value) =>
  '<option value="' + esc(id) + '"' + (id === value ? ' selected' : '') + '>' + esc(text) + '</option>';

function rosterSelect(label, field, options, value) {
  return '<select data-roster-field="' + esc(field) + '" aria-label="' + esc(label) + '">' +
    options.map(([id, text]) => rosterOption(id, text, value)).join('') + '</select>';
}

/* Department options grouped by room (the Roster tab's select and the floor's "Move to…" select). */
const rosterZoneGroups = (value) =>
  rosterDraft.rooms.map((room) =>
    '<optgroup label="' + esc(room.label || room.id) + '">' +
      room.zones.map((zone) => rosterOption(zone.id, zone.label || zone.id, value)).join('') + '</optgroup>'
  ).join('');

/* The department select is grouped by room; a bot whose department does not exist yet shows an empty choice. */
function rosterZoneSelect(bot) {
  const known = rosterDraft.rooms.some((room) => room.zones.some((zone) => zone.id === bot.zone));
  const groups = rosterZoneGroups(bot.zone);
  return '<select data-roster-field="zone" aria-label="Department">' +
    (known ? '' : '<option value="" selected>– choose –</option>') + groups + '</select>';
}

function rosterColourCell(bot, open) {
  return '<div class="roster-color">' + rosterInput('Colour in hex (#rrggbb)', 'color', bot.color) +
    '<button type="button" data-roster-edit aria-expanded="' + (open ? 'true' : 'false') + '" aria-label="' +
    esc('Colour swatches and location for ' + bot.id) + '" title="Swatches and location">' + (open ? '▴' : '▾') + '</button></div>';
}

/* Opens below the row being edited only: the location field and the colour swatches. */
function rosterMoreHtml(bot) {
  return '<div class="roster-more"><label>Location' + rosterInput('Location', 'loc', bot.loc) + '</label>' +
    '<div class="swatches">' +
    palette().swatches.map((color) =>
      '<button type="button" data-roster-swatch="' + esc(color) + '" title="' + esc(color) + '" aria-label="' +
        esc('Use colour ' + color) + '" style="background:' + safeColor(color) + '"></button>'
    ).join('') +
    '</div></div>';
}

function rosterHeadHtml() {
  return '<div class="roster-head" aria-hidden="true">' +
    ['ID', 'Title', 'Role', 'Sprite', 'Department', 'Colour', 'Leader', ''].map((text) => '<span>' + esc(text) + '</span>').join('') +
    '</div>';
}

function rosterBotHtml(bot, index) {
  const open = rosterEditing === bot.id;
  return '<div class="roster-bot' + (open ? ' open' : '') + '" data-roster-bot="' + Number(index) + '"><div class="roster-row">' +
    '<input type="text" data-roster-id value="' + esc(bot.id) + '" readonly aria-label="ID">' +
    rosterInput('Title', 'title', bot.title) + rosterInput('Role', 'cls', bot.cls) +
    rosterSelect('Sprite', 'sprite', [['', 'auto'], ...SPRITE_VARIANTS.map((name) => [name, name])], bot.sprite || '') +
    rosterZoneSelect(bot) + rosterColourCell(bot, open) +
    '<label class="roster-leader"><input type="radio" name="pixelhq-leader" data-roster-leader aria-label="Leader"' +
    (bot.leader ? ' checked' : '') + '></label>' +
    '<span class="roster-end">' + (bot.remote === true ? '<button type="button" data-roster-remove-bot>Remove</button>' : '') +
    '</span></div>' + (open ? rosterMoreHtml(bot) : '') + '</div>';
}

function rosterChanged() {
  rosterDirty = true;
  rosterTrips.forget('roster');
  renderLayoutBar();
}

function bindRosterField(input, bot) {
  const update = () => {
    if (rosterBusy()) {
      return;
    }
    if (input.dataset.rosterField === 'sprite' && !input.value) {
      delete bot.sprite;
    } else {
      bot[input.dataset.rosterField] = input.value;
    }
    rosterChanged();
    if (input.dataset.rosterField === 'zone') {
      renderRoster();
    }
  };
  if (input.tagName === 'SELECT') {
    input.onchange = update;
  } else {
    input.oninput = update;
  }
}

function bindRosterRows(root) {
  root.querySelectorAll('[data-roster-bot]').forEach((row) => {
    const index = Number(row.dataset.rosterBot);
    const bot = rosterDraft.bots[index];
    row.querySelectorAll('[data-roster-field]').forEach((input) => bindRosterField(input, bot));
    row.querySelector('[data-roster-edit]').onclick = () => {
      rosterEditing = rosterEditing === bot.id ? '' : bot.id;
      renderRoster();
    };
    row.querySelectorAll('[data-roster-swatch]').forEach((btn) =>
      (btn.onclick = () => {
        if (rosterBusy()) {
          return;
        }
        bot.color = btn.dataset.rosterSwatch;
        rosterChanged();
        renderRoster();
      })
    );
    row.querySelector('[data-roster-leader]').onchange = () => {
      if (rosterBusy()) {
        return;
      }
      rosterDraft.bots.forEach((b, i) => {
        b.leader = i === index;
      });
      rosterChanged();
      renderRoster();
    };
    const remove = row.querySelector('[data-roster-remove-bot]');
    if (remove) {
      remove.onclick = () => {
        if (rosterBusy() || bot.remote !== true) {
          return;
        }
        rosterDraft.bots.splice(index, 1);
        rosterChanged();
        renderRoster();
      };
    }
  });
}

function rosterBotAddHtml() {
  return '<div class="acts roster-add"><label>Remote bot ID<input type="text" data-roster-new-bot maxlength="64" value="' +
    esc(rosterNew.bot) + '"></label><button type="button" data-roster-add-bot>Add remote bot</button></div>';
}

function rosterProblem(message) {
  if (rosterBusy()) {
    return false;
  }
  rosterTrips.put('roster', { ok: false, message });
  renderRoster();
  return false;
}

const validBotId = (value) => /^[A-Za-z0-9._-]{1,64}$/.test(value);
const validGroupId = (value) => /^[A-Za-z0-9_-]{1,64}$/.test(value);

/* Shared text rule: the host sends it as cfg.textRule (defined once in config.py); the server stays authoritative. */
function rosterTextTest() {
  const rule = CFG().textRule;
  if (!rule) {
    return null;
  }
  const re = new RegExp(
    '[' + rule.categories.map((name) => '\\p{' + name + '}').join('') +
      rule.ranges.map(([lo, hi]) => '\\u{' + lo.toString(16) + '}-\\u{' + hi.toString(16) + '}').join('') + ']',
    'u'
  );
  return (value, limit) => typeof value === 'string' && [...value].length <= limit && !re.test(value);
}

function rosterTextMessage(where, limit) {
  return where + ': use at most ' + limit + ' characters without ' + CFG().textRule.message + '.';
}

function rosterTextProblem() {
  const ok = rosterTextTest();
  if (!ok) {
    return null;
  }
  const named = (kind, index, entry) => kind + '[' + index + '] (id ' + JSON.stringify(entry.id) + ')';
  for (const [ri, room] of rosterDraft.rooms.entries()) {
    const rp = named('rooms', ri, room);
    if (!ok(room.label, 40)) {
      return rosterTextMessage(rp + '.label', 40);
    }
    if (room.note !== undefined && !ok(room.note, 80)) {
      return rosterTextMessage(rp + '.note', 80);
    }
    for (const [zi, zone] of (room.zones || []).entries()) {
      if (!ok(zone.label, 40)) {
        return rosterTextMessage(rp + '.zones' + named('', zi, zone) + '.label', 40);
      }
    }
  }
  for (const [bi, bot] of rosterDraft.bots.entries()) {
    for (const field of ['cls', 'title', 'loc']) {
      if ((field !== 'loc' || bot.loc !== undefined) && !ok(bot[field], 40)) {
        return rosterTextMessage(named('bots', bi, bot) + '.' + field, 40);
      }
    }
  }
}

function addRosterBot() {
  if (rosterBusy()) {
    return false;
  }
  const id = rosterNew.bot;
  if (!validBotId(id)) {
    return rosterProblem('Bot id: use 1–64 ASCII letters, digits or ._- only.');
  }
  if (rosterDraft.bots.some((bot) => bot.id === id)) {
    return rosterProblem('Bot id already exists.');
  }
  if (rosterDraft.bots.length >= 200) {
    return rosterProblem('At most 200 bots are allowed.');
  }
  const main = rosterDraft.rooms.find((room) => room.main);
  const zone = main && main.zones[0] || rosterDraft.rooms.flatMap((room) => room.zones)[0];
  if (!zone) {
    return rosterProblem('Add a department first.');
  }
  rosterDraft.bots.push(
    { id, title: 'Recruit', cls: 'Hermes profile', zone: zone.id, color: palette().swatches[0], remote: true }
  );
  rosterNew.bot = '';
  rosterChanged();
  renderRoster();
  return true;
}

/* One table drives the "add" inputs of bots, rooms and departments: `rosterNew` keeps what was typed across renders. */
const ROSTER_NEW_FIELDS = [
  ['[data-roster-new-bot]', 'bot'],
  ['[data-roster-new-room]', 'room'],
  ['[data-roster-new-room-label]', 'roomLabel'],
  ['[data-roster-new-zone]', 'zone'],
  ['[data-roster-new-zone-label]', 'label'],
  ['[data-roster-new-zone-room]', 'zoneRoom']
];

function bindRosterAdds(root) {
  const read = () => ROSTER_NEW_FIELDS.forEach(([selector, key]) => {
    rosterNew[key] = root.querySelector(selector).value;
  });
  for (const [selector, key] of ROSTER_NEW_FIELDS) {
    const input = root.querySelector(selector);
    input.oninput = () => {
      if (!rosterBusy()) {
        rosterNew[key] = input.value;
      }
    };
    input.onchange = input.oninput;
  }
  for (const [selector, action] of [
    ['[data-roster-add-bot]', addRosterBot],
    ['[data-roster-add-room]', addRosterRoom],
    ['[data-roster-add-zone]', addRosterZone]
  ]) {
    root.querySelector(selector).onclick = () => {
      read();
      action();
    };
  }
}

function submitRoster(body) {
  if (!EMBED || rosterBusy()) {
    return;
  }
  roundTrip(
    rosterTrips,
    'roster',
    { saving: body.roster || null },
    { pixelhqRoster: body },
    onRosterResult,
    renderRoster
  );
}

/* The saved payload travels with the trip, so an answer after the UI timeout (D21) updates the base like an in-time one;
   a draft edited since then is kept when it differs from what was saved. */
function onRosterResult(result) {
  if (!result || typeof result.ok !== 'boolean' || !rosterTrips.waiting().length) {
    return;
  }
  const saving = (rosterTrips.info('roster') || {}).saving || null;
  const inTime = rosterBusy();
  rosterTrips.finish(
    'roster',
    { ok: result.ok, message: String(result.message || 'No roster result received.').slice(0, 200) }
  );
  if (result.ok) {
    if (inTime || !rosterDirty || JSON.stringify(rosterDraft) === JSON.stringify(saving)) {
      rosterDirty = false;
      rosterDraft = null;
    }
    rosterSaved = saving;
  }
  renderRoster();
}

/* Save of the Roster tab and of the layout bar: the same checks, the same round trip (post first). */
function saveRoster() {
  const problem = rosterDraftProblem() || rosterTextProblem();
  if (problem) {
    return rosterProblem(problem);
  }
  submitRoster({ roster: rosterClone(rosterDraft) });
}

function bindRosterSubmit(root) {
  root.querySelector('[data-roster-save]').onclick = saveRoster;
  const reset = root.querySelector('[data-roster-reset]');
  reset.onclick = () => {
    if (rosterBusy()) {
      return;
    }
    armedButton(reset, () => 'Reset to generated', 'Confirm: reset to generated?', () => submitRoster({ reset: true }));
  };
}

/* The draft is the saved roster (or the snapshot's) until the operator changes it; a clean draft follows new snapshots. */
function rosterEnsureDraft(rebase) {
  if (!rosterDraft || rebase && !rosterDirty && !rosterBusy()) {
    rosterDraft = rosterSaved ? rosterClone(rosterSaved) : rosterFromSnapshot();
  }
}

/* Every draft change renders the editor, the layout bar and (in edit mode) the floor from the same draft. */
function renderRoster() {
  const drawn = renderDirect(document.getElementById('roster-editor'), drawRoster);
  renderLayoutBar();
  renderFloorEdit();
  return drawn;
}

function drawRoster() {
  if (!EMBED) {
    return;
  }
  rosterEnsureDraft(true);
  const root = document.getElementById('roster-editor');
  const note = rosterResult();
  root.innerHTML = '<fieldset data-roster-controls' + (rosterBusy() ? ' disabled' : '') + '><legend>Roster</legend>' +
    '<div class="roster-bots">' + rosterHeadHtml() + rosterDraft.bots.map(rosterBotHtml).join('') + '</div>' +
    rosterBotAddHtml() + rosterGroupsHtml() +
    '<div class="acts"><button type="button" data-roster-save>Save</button>' +
    '<button type="button" data-roster-reset>Reset to generated</button></div></fieldset>' +
    (rosterBusy() ? '<div class="res" role="status">Saving roster …</div>' : '') +
    (note ? '<div class="res ' + (note.ok ? 'ok' : 'bad') + '" role="status">' + esc(note.message) + '</div>' : '');
  bindRosterRows(root);
  bindRosterGroups(root);
  bindRosterAdds(root);
  bindRosterSubmit(root);
}

const renderRosterPeriodic = () => {
  if (rosterDraft) {
    renderUnlessFocused(document.getElementById('roster-editor'), drawRoster);
  }
};
