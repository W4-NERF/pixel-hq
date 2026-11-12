/* ---- Host round trips (D10): one pending/result helper and one armed-button helper; every trip has a UI timeout ---- */
const TRIP_MS = { action: 75000, other: 20000 };
const TIMEOUT_TEXT = 'no answer from the host (timeout)';
const ARM_MS = 6000;
const hostClock = { now: () => Date.now(), later: (fn, ms) => setTimeout(fn, ms) };

/* A trip that timed out stays in `late` (key -> trip) until it is started again or finished: its answer may still arrive and then
   replaces the timeout line (D21). An answer for a key that never timed out and has no open trip is rejected (`finish` -> false). */
function hostTrips(limitMs, onExpire) {
  const open = new Map();
  const late = new Map();
  const done = new Map();
  const waiting = () => [...open, ...late].map(([key, trip]) => [key, trip.info]);
  const trips = {
    busy: (key) => open.has(key),
    entries: () => [...open].map(([key, trip]) => [key, trip.info]),
    waiting,
    info: (key) => (open.get(key) || late.get(key) || {}).info,
    start(key, info) {
      open.set(key, { info, at: hostClock.now() });
      late.delete(key);
      done.delete(key);
      hostClock.later(trips.expire, limitMs);
    },
    finish(key, result) {
      const trip = open.get(key) || late.get(key);
      if (!trip) {
        return false;
      }
      open.delete(key);
      late.delete(key);
      done.set(key, result);
      return true;
    },
    put: (key, result) => done.set(key, result),
    result: (key) => done.get(key),
    forget: (key) => done.delete(key),
    expire() {
      const now = hostClock.now();
      for (const [key, trip] of [...open]) {
        if (now - trip.at >= limitMs) {
          open.delete(key);
          late.set(key, trip);
          done.set(key, { ok: false, message: TIMEOUT_TEXT });
          onExpire(key, trip.info);
        }
      }
    }
  };
  return trips;
}

function disarm(btn) {
  btn.dataset.armed = '';
  btn.classList.remove('armed');
}

/* First click arms the button (label changes, auto-disarms after ARM_MS); the second click runs `confirmed`. */
function armedButton(btn, restoreLabel, armedLabel, confirmed) {
  if (btn.dataset.armed === '1') {
    disarm(btn);
    confirmed();
    return;
  }
  btn.dataset.armed = '1';
  btn.classList.add('armed');
  btn.textContent = armedLabel;
  hostClock.later(
    () => {
      if (btn.isConnected && btn.dataset.armed === '1') {
        disarm(btn);
        btn.textContent = restoreLabel();
      }
    },
    ARM_MS
  );
}

/* Every host round trip posts first and renders second (D16c): a render problem can never swallow the request. */
function roundTrip(trips, key, info, message, onResult, render) {
  trips.start(key, info);
  submitToHost(message, onResult);
  render();
}
