/* ---- Session jumps: last result and pending state survive polling ---- */
const jumpTrips = hostTrips(TRIP_MS.other, (key) => refreshJumpRows(key));
const jumpKey = (profile, sessionId) => JSON.stringify([profile, sessionId || null]);

function jumpBody(el) {
  const key = el.dataset.jumpRow;
  const pending = jumpTrips.busy(key);
  const r = jumpTrips.result(key);
  const kinds = el.dataset.session ? ['Open', ...el.dataset.stale === '1' ? ['Nudge'] : []] : ['Chat'];
  let h = '<div class="acts">' +
    kinds.map((kind) =>
      '<button type="button" data-jump="' + esc(kind) + '"' + (pending ? ' disabled' : '') + '>' +
        esc({ Open: 'Open', Chat: 'Talk to this bot', Nudge: 'Ask for status' }[kind]) + '</button>'
    ).join('') +
    '</div>';
  if (pending) {
    h += '<div class="res" role="status">Opening …</div>';
  }
  if (r) {
    h += '<div class="res ' + (r.ok ? 'ok' : 'bad') + '" role="status">' +
      esc(r.message || 'No jump result received.') + '</div>';
  }
  return h;
}

function jumpHtml(profile, sessionId, stale = false) {
  if (!EMBED) {
    return '';
  }
  const key = jumpKey(profile, sessionId);
  const el = { dataset: { jumpRow: key, session: sessionId || '', stale: stale === true ? '1' : '0' } };
  return '<div class="jump" data-jump-row="' + esc(key) + '" data-profile="' + esc(profile) + '" data-session="' +
    esc(sessionId || '') + '" data-stale="' + esc(el.dataset.stale) + '">' + jumpBody(el) + '</div>';
}

function chatHtml(bot) {
  if (!EMBED) {
    return '';
  }
  return bot.remote === true
    ? '<div class="acts"><span class="mut">runs on another host</span></div>'
    : jumpHtml(bot.id, null);
}

function refreshJump(el) {
  renderDirect(el, () => {
    el.innerHTML = jumpBody(el);
    bindJump(el);
  });
}

function bindJump(el) {
  el.querySelectorAll('[data-jump]').forEach((btn) =>
    (btn.onclick = () => {
      const key = el.dataset.jumpRow;
      if (jumpTrips.busy(key)) {
        return;
      }
      const kind = btn.dataset.jump;
      const body = { profile: el.dataset.profile };
      if (kind !== 'Chat') {
        body.sessionId = el.dataset.session;
      }
      roundTrip(
        jumpTrips,
        key,
        { kind, ...body },
        { ['pixelhq' + kind]: body },
        (r) => onJumpResult(kind, { ...r, ...body }),
        () => refreshJump(el)
      );
    })
  );
}

function bindJumps(root) {
  root.querySelectorAll('[data-jump-row]').forEach(bindJump);
}

const refreshJumpRows = (key) =>
  document.querySelectorAll('[data-jump-row]').forEach((el) => {
    if (el.dataset.jumpRow === key) {
      refreshJump(el);
    }
  });

function onJumpResult(kind, r) {
  for (const [key, p] of jumpTrips.waiting()) {
    if (p.kind !== kind || (kind === 'Chat' ? p.profile !== r.profile : p.sessionId !== r.sessionId)) {
      continue;
    }
    jumpTrips.finish(key, r);
    refreshJumpRows(key);
  }
}
