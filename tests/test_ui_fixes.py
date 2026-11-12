"""Regression probes for review findings in the page: settings, message order, round trips and the drag click."""
import pytest

from tests.test_host_ui_hardening import CLOCK
from tests.test_roster_ui import run_roster

SEND = "const send = data => listeners.get('message')({source:window.parent, data});\n"


@pytest.mark.parametrize("locale, zone", [("en_GB", "UTC"), ("en-GB", "Europe/Berlinn"), ("", ""), ("x-invalid-", "+99")])
def test_an_invalid_locale_or_timezone_falls_back_instead_of_blanking_the_page(tmp_path, locale, zone):
    run_roster(tmp_path, SEND + """
const data = JSON.parse(JSON.stringify(DATA));
data.cfg.locale = LOCALE_VALUE; data.cfg.timezone = ZONE_VALUE;
send({pixelhq:data});
const stand = document.getElementById('stand').textContent;
assert.ok(!stand.includes('render error'), stand);
assert.equal(fmtN(1234567), (1234567).toLocaleString(LOCALE_VALUE === 'en_GB' || LOCALE_VALUE === 'x-invalid-' ? 'en-GB' : LOCALE_VALUE || 'en-GB'));
assert.match(clock(1700000000), /\\d/);
assert.ok(document.getElementById('tb').innerHTML.length > 0, 'the leaderboard rendered');
""".replace("LOCALE_VALUE", repr(locale)).replace("ZONE_VALUE", repr(zone)), iframe=True)


def test_live_data_before_the_first_snapshot_is_kept_without_an_error(tmp_path):
    run_roster(tmp_path, SEND + """
const first = DATA;
DATA = null; LIVE = null;
const live = {generated: first.generated, bots: {}, warnings: [], unassignedTasks: {}};
send({pixelhqLive: live});
send({pixelhqLiveError: 'sample live failure'});
send({pixelhqLive: live});
assert.ok(!document.getElementById('stand').textContent.includes('error'), document.getElementById('stand').textContent);
assert.equal(LIVE, live, 'live data is kept for the snapshot');
send({pixelhq: first});
assert.ok(!document.getElementById('stand').textContent.includes('error'));
assert.ok(document.getElementById('livetab').textContent.startsWith('Live ('), 'rendered with the kept live data');
""", iframe=True)


def test_a_host_trip_still_expires_after_the_wall_clock_steps_back(tmp_path):
    run_roster(tmp_path, """
let now = 1000000, queue = [];
hostClock.now = () => now;
hostClock.later = (fn, ms) => { queue.push({fn, due: now + ms}); };
const run = () => { const due = queue.filter(t => t.due <= now); queue = queue.filter(t => t.due > now); due.forEach(t => t.fn()); };
const expired = [];
const trips = hostTrips(20000, key => expired.push(key));
trips.start('sample', {});
now -= 3600000;                       // the system clock is set back by an hour
queue.forEach(t => { t.due = now; });  // the timer itself still fires on time
run();
assert.deepEqual(expired, [], 'not due by the wall clock yet');
assert.ok(queue.length >= 1, 'the trip is checked again');
for (let i = 0; i < 5 && !expired.length; i++) { now += 20000; run(); }
assert.deepEqual(expired, ['sample']);
assert.equal(trips.result('sample').message, 'no answer from the host (timeout)');
""", iframe=True)


def test_a_late_roster_answer_does_not_finish_a_newer_save(tmp_path):
    run_roster(tmp_path, CLOCK + """
tab('roster');
const editor = document.getElementById('roster-editor');
const titleField = () => editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]');
const saves = () => messages.filter(m => m.pixelhqRoster).map(m => m.pixelhqRoster);
titleField().value = 'First save'; titleField().oninput();
editor.querySelector('[data-roster-save]').onclick();
advance(20000);                                   // save #1 times out in the UI
titleField().value = 'Second save'; titleField().oninput();
editor.querySelector('[data-roster-save]').onclick();
const [first, second] = saves();
assert.notEqual(first.rid, second.rid);
send({pixelhqRosterResult:{ok:true, message:'Roster saved.', rid:first.rid}});
assert.equal(rosterBusy(), true, 'the late answer of save #1 does not finish save #2');
assert.equal(rosterDirty, true);
send({pixelhqRosterResult:{ok:false, message:'Sample refusal', rid:second.rid}});
assert.equal(rosterBusy(), false);
assert.equal(rosterDirty, true, 'the edits of the failed save #2 are kept');
assert.equal(titleField().value, 'Second save');
""", iframe=True)


def test_a_roster_answer_without_a_request_id_is_still_accepted(tmp_path):
    """Compatibility with a bridge that does not echo the id yet."""
    run_roster(tmp_path, CLOCK + """
tab('roster');
const editor = document.getElementById('roster-editor');
const field = editor.querySelectorAll('[data-roster-bot]')[1].querySelector('[data-roster-field="title"]');
field.value = 'Saved title'; field.oninput();
editor.querySelector('[data-roster-save]').onclick();
send({pixelhqRosterResult:{ok:true, message:'Roster saved.'}});
assert.equal(rosterBusy(), false); assert.equal(rosterDirty, false);
""", iframe=True)
