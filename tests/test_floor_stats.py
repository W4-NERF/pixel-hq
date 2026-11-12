"""Round 3, section 4: department numbers on the floor (members · active · blocked · Ø HP · XP in every department header,
the totals in every room header).

`zoneStats` / `roomStats` / `compactN` run in the plain-Node DOM harness against the demo snapshot (invented data) with
edits made in the probe. The rendered header text is read back from the floor markup. No browser was used.
"""
from pixelhq.demo import snapshot
from tests.test_roster_ui import run_roster

PRELUDE = """
const send = data => listeners.get('message')({source: window.parent, data});
const floor = document.getElementById('floor');
const toggle = () => document.getElementById('edit-layout').onclick();
const decode = s => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
// The five numbers of the header that follows `marker` in the floor markup: text as shown and the title of each number.
const header = marker => {
  const html = floor.innerHTML, from = html.indexOf(marker);
  assert.ok(from >= 0, 'header of ' + marker);
  const block = html.slice(from).match(/<div class="stats">(.*?)<\\/div>/)[1];
  const parts = [...block.matchAll(/<span class="stat([^"]*)" title="([^"]*)">([^<]*)<\\/span>/g)];
  return {text: parts.map(p => decode(p[3])).join(' · '), titles: parts.map(p => decode(p[2])), classes: parts.map(p => p[1].trim())};
};
const zoneHead = id => header('data-dept="' + id + '"');
const roomHead = id => header('data-room="' + id + '"');
const bot = id => DATA.bots.find(b => b.id === id);
const out = (name, value) => console.log(name + ':' + JSON.stringify(value));
renderAll();
"""


def run_stats(tmp_path, probe, **kwargs):
    return run_roster(tmp_path, PRELUDE + probe, iframe=True, **kwargs)


def test_compact_numbers(tmp_path):
    run_stats(tmp_path, """
const table = [[0, '0'], [7, '7'], [999, '999'], [1000, '1k'], [1234, '1.2k'], [1250, '1.3k'], [9949, '9.9k'], [9950, '10k'],
  [12345, '12k'], [99999, '100k'], [999499, '999k'], [999500, '1M'], [1500000, '1.5M'], [12000000, '12M'], [2500000000, '2.5G'],
  [null, '0'], [undefined, '0'], ['x', '0'], [-5, '0'], ['1234', '1.2k'], [1233.6, '1.2k']];
for (const [value, want] of table) assert.equal(compactN(value), want, String(value));
""")


def test_demo_departments_as_rendered(tmp_path):
    out = run_stats(tmp_path, """
const rows = {};
for (const id of ['command', 'ops', 'lab', 'quarantine', 'remote']) rows[id] = zoneHead(id).text;
for (const id of ['hq', 'outpost']) rows[id] = roomHead(id).text;
out('ROWS', rows);
// one stats block per department and per room, none for the reactor room
assert.equal([...floor.innerHTML.matchAll(/<div class="stats">/g)].length, 5 + 2);
const ops = zoneHead('ops');
assert.equal(ops.titles.length, 5);
assert.ok(ops.titles.every(t => t.length > 10), 'every number has a tooltip');
assert.ok(/^Members: /.test(ops.titles[0]) && /^Active: /.test(ops.titles[1]) && /^Blocked: /.test(ops.titles[2]));
assert.ok(/^Average HP: /.test(ops.titles[3]) && /^XP: /.test(ops.titles[4]));
assert.ok(ops.titles[4].includes('1,426'), 'the tooltip carries the exact XP: ' + ops.titles[4]);
assert.deepEqual(ops.classes, ['m', 'a', 'b hot', 'h', 'x']);
assert.deepEqual(zoneHead('lab').classes, ['m', 'a', 'b hot', 'h', 'x']);
assert.deepEqual(zoneHead('command').classes, ['m', 'a', 'b', 'h', 'x'], 'no blocked card: no highlight');
""")
    rows = next(line for line in out.splitlines() if line.startswith("ROWS:"))
    assert rows == ("ROWS:" + '{"command":"1 · 1 · 0 · Ø 99% · 2.4k XP","ops":"4 · 1 · 1 · Ø 85% · 1.4k XP",'
                    '"lab":"2 · 1 · 1 · Ø 34% · 175 XP","quarantine":"1 · 1 · 0 · Ø 73% · 228 XP",'
                    '"remote":"1 · 0 · 0 · Ø 92% · 349 XP","hq":"8 · 4 · 2 · Ø 72% · 4.2k XP",'
                    '"outpost":"1 · 0 · 0 · Ø 92% · 349 XP"}')


def test_stats_are_pure_and_an_empty_department_is_all_zero(tmp_path):
    run_stats(tmp_path, """
DATA.cfg.rooms[0].zones.push({id: 'annex', label: 'ANNEX'});
const before = JSON.stringify([DATA, LIVE]);
const ops = zoneStats('ops', false);
assert.deepEqual(ops, {members: 4, active: 1, blocked: 1, hp: 85, hpCount: 4, xp: 1426});
assert.deepEqual(zoneStats('ops', false), ops, 'same input, same output');
assert.deepEqual(zoneStats('annex', false), {members: 0, active: 0, blocked: 0, hp: null, hpCount: 0, xp: 0});
assert.deepEqual(zoneStats('no-such-department', false), zoneStats('annex', false));
assert.deepEqual(roomStats('no-such-room', false), zoneStats('annex', false));
roomStats('hq', false);
assert.equal(JSON.stringify([DATA, LIVE]), before, 'nothing was changed');
renderAll();
assert.equal(zoneHead('annex').text, '0 · 0 · 0 · Ø – · 0 XP');
assert.ok(/none of the members/.test(zoneHead('annex').titles[3]), zoneHead('annex').titles[3]);
assert.ok(/^Members: 0 bots/.test(zoneHead('annex').titles[0]));
""")


def test_average_hp_counts_only_members_that_have_one(tmp_path):
    run_stats(tmp_path, """
bot('dev-a').hp = null;                       // lab: one HP value left (68)
assert.equal(zoneStats('lab', false).hp, 68);
assert.equal(zoneStats('lab', false).hpCount, 1);
bot('dev-a').hp = 0;                          // 0 is a value, not a missing one
bot('dev-b').hp = null;
assert.equal(zoneStats('lab', false).hp, 0);
bot('dev-b').hp = 1; bot('dev-a').hp = 2;     // 1.5 rounds up
assert.equal(zoneStats('lab', false).hp, 2);
bot('dev-b').hp = null; bot('dev-a').hp = null;
assert.deepEqual(zoneStats('lab', false), {members: 2, active: 1, blocked: 1, hp: null, hpCount: 0, xp: 175});
renderAll();
assert.equal(zoneHead('lab').text, '2 · 1 · 1 · Ø – · 175 XP');
assert.ok(zoneHead('lab').titles[3].startsWith('Average HP'));
bot('dev-b').hp = 'x'; bot('dev-a').hp = undefined;   // unusable values are missing values
assert.equal(zoneStats('lab', false).hp, null);
""")


def test_active_follows_live_data_when_present_else_the_snapshot(tmp_path):
    run_stats(tmp_path, """
// lab in the snapshot: dev-a working (and owns a blocked card), dev-b idle
assert.equal(zoneStats('lab', false).active, 1);
LIVE = {generated: 10, bots: {'dev-a': {active: false, sessions: [], tasks: []}}};
assert.equal(zoneStats('lab', false).active, 0, 'live data says dev-a is not active; dev-b has no live entry: snapshot');
LIVE.bots['dev-b'] = {active: true, sessions: [], tasks: []};
assert.equal(zoneStats('lab', false).active, 1, 'live data says dev-b is working');
LIVE.bots['dev-a'] = {active: true, sessions: [], tasks: []};
assert.equal(zoneStats('lab', false).active, 2);
assert.equal(zoneStats('lab', false).blocked, 1, 'the blocked card does not depend on the live status');
LIVE = null;
assert.equal(zoneStats('lab', false).active, 1, 'no live data at all: the snapshot');
// the desk bubble and the header use the same rule
for (const id of ['dev-a', 'dev-b', 'sysadmin', 'devops']) {
  LIVE = {generated: 10, bots: {[id]: {active: true, sessions: [], tasks: []}}};
  assert.equal(liveStatus(bot(id)).status, 'running');
}
// a live message re-draws the header
LIVE = null; renderAll();
assert.equal(zoneHead('ops').text.split(' · ')[1], '1');
send({pixelhqLive: {generated: 20, bots: {sysadmin: {active: true, sessions: [], tasks: []},
  devops: {active: false, sessions: [], tasks: []}, security: {active: true, sessions: [], tasks: []}}}});
assert.equal(zoneHead('ops').text.split(' · ')[1], '2', 'sysadmin and security working, devops live-idle: ' + zoneHead('ops').text);
assert.equal(roomHead('hq').text.split(' · ')[1], '5');
""")


def test_blocked_counts_cards_of_members_only(tmp_path):
    run_stats(tmp_path, """
const card = (assignee, id) => ({board: 'platform', id, title: 'Sample card', assignee, cat: 'you', openParents: [], ageDays: 1});
assert.equal(DATA.blockers.length, 2);
assert.equal(zoneStats('ops', false).blocked, 1);
assert.equal(zoneStats('lab', false).blocked, 1);
assert.equal(zoneStats('command', false).blocked, 0);
DATA.blockers.push(card('netadmin', 't_a1'), card('netadmin', 't_a2'), card('default', 't_a3'));   // two more for netadmin, one for default
DATA.blockers.push(card('someone-else', 't_a4'), card(undefined, 't_a5'), card('', 't_a6'));       // not members of anything
assert.equal(zoneStats('ops', false).blocked, 3, 'every card of a member counts');
assert.equal(zoneStats('command', false).blocked, 1);
assert.equal(zoneStats('lab', false).blocked, 1);
assert.equal(zoneStats('quarantine', false).blocked, 0);
assert.equal(roomStats('hq', false).blocked, 5);
assert.equal(roomStats('outpost', false).blocked, 0, 'cards of an unknown assignee belong to no room');
// the bot field "blocked" (a counter on the bot) is not the source: the cards are
bot('security').blocked = 9; bot('remote-ops').blocked = 4;
assert.equal(zoneStats('ops', false).blocked, 3);
assert.equal(zoneStats('remote', false).blocked, 0);
DATA.blockers = undefined;
assert.equal(zoneStats('ops', false).blocked, 0, 'a snapshot without cards');
renderAll();
assert.equal(zoneHead('ops').text.split(' · ')[2], '0');
""")


def test_room_totals_are_over_all_members_not_a_mean_of_means(tmp_path):
    run_stats(tmp_path, """
const hq = roomStats('hq', false);
assert.deepEqual(hq, {members: 8, active: 4, blocked: 2, hp: 72, hpCount: 8, xp: 4187});   // 579 / 8 = 72.4; mean of the means: 73
const parts = ['command', 'ops', 'lab', 'quarantine'].map(id => zoneStats(id, false));
assert.equal(parts.reduce((s, p) => s + p.members, 0), hq.members);
assert.equal(parts.reduce((s, p) => s + p.active, 0), hq.active);
assert.equal(parts.reduce((s, p) => s + p.blocked, 0), hq.blocked);
assert.equal(parts.reduce((s, p) => s + p.xp, 0), hq.xp);
assert.equal(Math.round(parts.reduce((s, p) => s + p.hp, 0) / parts.length), 73, 'the wrong way to do it gives another number');
// a room without a department, and bots without HP do not dilute the room's Ø HP
DATA.cfg.rooms.push({id: 'annex-room', label: 'ANNEX ROOM', zones: []});
assert.deepEqual(roomStats('annex-room', false), {members: 0, active: 0, blocked: 0, hp: null, hpCount: 0, xp: 0});
bot('default').hp = null; bot('sysadmin').hp = null;
assert.equal(roomStats('hq', false).hp, Math.round((81 + 89 + 79 + 0 + 68 + 73) / 6));
assert.equal(roomStats('hq', false).hpCount, 6);
renderAll();
assert.equal(roomHead('annex-room').text, '0 · 0 · 0 · Ø – · 0 XP');
assert.ok(/this room/.test(roomHead('annex-room').titles[0]) && /this department/.test(zoneHead('ops').titles[0]));
bot('security').xp = 12345; renderAll();
assert.ok(roomHead('hq').text.endsWith(' XP') && /· \\d+(\\.\\d)?k XP$/.test(roomHead('hq').text), roomHead('hq').text);
""")


def test_edit_mode_takes_membership_from_the_draft_and_values_from_the_snapshot(tmp_path):
    run_stats(tmp_path, """
toggle();
assert.ok(floor.classList.contains('editing'));
assert.equal(zoneHead('ops').text, '4 · 1 · 1 · Ø 85% · 1.4k XP', 'edit mode shows the numbers too');
assert.equal(zoneHead('lab').text, '2 · 1 · 1 · Ø 34% · 175 XP');
assert.equal(roomHead('hq').text, '8 · 4 · 2 · Ø 72% · 4.2k XP');
// move devops (working, HP 89, XP 593) to lab with "Move to…"
const select = floor.querySelectorAll('select').find(s => s.dataset.moveTo === 'devops');
select.value = 'lab'; select.onchange();
assert.equal(rosterDraft.bots.find(b => b.id === 'devops').zone, 'lab');
assert.equal(bot('devops').zone, 'ops', 'the snapshot keeps its department');
assert.deepEqual(zoneStats('ops', true), {members: 3, active: 0, blocked: 1, hp: 83, hpCount: 3, xp: 833});
assert.deepEqual(zoneStats('lab', true), {members: 3, active: 2, blocked: 1, hp: 52, hpCount: 3, xp: 768});
assert.deepEqual(zoneStats('ops', false), {members: 4, active: 1, blocked: 1, hp: 85, hpCount: 4, xp: 1426}, 'outside edit mode: the snapshot');
assert.equal(zoneHead('ops').text, '3 · 0 · 1 · Ø 83% · 833 XP');
assert.equal(zoneHead('lab').text, '3 · 2 · 1 · Ø 52% · 768 XP');
assert.equal(roomHead('hq').text, '8 · 4 · 2 · Ø 72% · 4.2k XP', 'the room total does not change when a bot moves inside it');
// a bot that is only in the draft: no HP, no XP, idle; a snapshot value change shows in edit mode (values come from the snapshot)
rosterDraft.bots.push({id: 'draft-only', zone: 'lab', color: '#778899'});
assert.deepEqual(zoneStats('lab', true), {members: 4, active: 2, blocked: 1, hp: 52, hpCount: 3, xp: 768});
bot('dev-b').xp = 1163; bot('dev-b').hp = 100;
assert.deepEqual(zoneStats('lab', true), {members: 4, active: 2, blocked: 1, hp: 63, hpCount: 3, xp: 1768});
// the room of a moved department: membership from the draft's rooms
const lab = rosterDraft.rooms[0].zones.splice(rosterDraft.rooms[0].zones.findIndex(z => z.id === 'lab'), 1)[0];
rosterDraft.rooms[1].zones.push(lab);
assert.equal(roomStats('hq', true).members, 5, 'hq lost lab (3 members and the draft-only bot)');
assert.equal(roomStats('outpost', true).members, 1 + 4);
// leaving edit mode: snapshot membership and rooms again
toggle();
assert.equal(zoneHead('ops').text, '4 · 1 · 1 · Ø 85% · 1.4k XP');
assert.equal(roomHead('hq').text.split(' · ')[0], '8');
""")


def test_demo_has_non_trivial_numbers_in_at_least_two_departments_for_any_seed():
    for seed in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        snap = snapshot(seed)
        zones = {}
        for b in snap["bots"]:
            zones.setdefault(b["zone"], []).append(b)
        cards = [c["assignee"] for c in snap["blockers"]]
        rich = []
        for zone, members in zones.items():
            ids = {b["id"] for b in members}
            active = [b for b in members if snap["live"]["bots"][b["id"]]["active"]]
            blocked = [a for a in cards if a in ids]
            hps = [b["hp"] for b in members if b["hp"] is not None]
            if len(members) >= 2 and active and blocked and hps and sum(b["xp"] for b in members) > 0:
                rich.append(zone)
        assert len(rich) >= 2, (seed, rich)
        # the live rule and the snapshot status agree in the demo, and every card belongs to a bot of the roster
        assert all((b["status"] == "running") == snap["live"]["bots"][b["id"]]["active"] for b in snap["bots"])
        assert set(cards) <= {b["id"] for b in snap["bots"]}
        assert all(b["blocked"] == sum(1 for a in cards if a == b["id"]) or b["status"] != "blocked" for b in snap["bots"])
