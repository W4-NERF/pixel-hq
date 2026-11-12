/* Tabs, filter and sort handlers, renderAll, the host message listener and the first render. */
function tab(t) {
  if (t === 'roster' && !EMBED) {
    return;
  }
  if (t === 'roster') {
    renderRoster();
  }
  document.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x.dataset.tab === t));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('on', v.id === t));
  if (t === 'office') {
    renderFloorEdit();
    select(sel);
  }
}

document.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => tab(b.dataset.tab)));
document.getElementById('edit-layout').onclick = toggleLayoutEdit;
document.querySelectorAll('[data-f]').forEach((b) =>
  (b.onclick = () => {
    ofilter = b.dataset.f;
    document.querySelectorAll('[data-f]').forEach((x) => x.classList.toggle('on', x === b));
    office();
  })
);
document.querySelectorAll('th[data-k]').forEach((th) =>
  (th.onclick = () => {
    bsort = th.dataset.k;
    document.querySelectorAll('th[data-k]').forEach((x) => x.classList.toggle('on', x === th));
    board();
  })
);

/* The Roster editor goes before the floor: a clean draft follows the new snapshot first, the edit-mode floor draws from it. */
function renderAll() {
  applyAppearance();
  hud();
  updateTick();
  renderRosterPeriodic();
  office();
  board();
  blk();
  liveTab();
}

window.addEventListener('message', (e) => {
  if (e.source !== window.parent) {
    return;
  }
  const m = e.data || {};
  if (m.pixelhqTheme && validMode(m.pixelhqTheme.mode)) {
    hostMode = m.pixelhqTheme.mode;
    applyAppearance();
    if (DATA) {
      renderAll();
    }
    return;
  }
  if (m.pixelhqOpenResult) {
    onJumpResult('Open', m.pixelhqOpenResult);
    return;
  }
  if (m.pixelhqChatResult) {
    onJumpResult('Chat', m.pixelhqChatResult);
    return;
  }
  if (m.pixelhqNudgeResult) {
    onJumpResult('Nudge', m.pixelhqNudgeResult);
    return;
  }
  if (m.pixelhqActionResult) {
    onActionResult(m.pixelhqActionResult);
    return;
  }
  if (m.pixelhqReviewResult) {
    onReviewResult(m.pixelhqReviewResult);
    return;
  }
  if (m.pixelhqRosterResult) {
    onRosterResult(m.pixelhqRosterResult);
    return;
  }
  if (onConfigMessage(m)) {
    return;
  }
  if (m.pixelhqLive) {
    LIVE = m.pixelhqLive;
    LIVE_ERR = null;
    liveRender();
    return;
  }
  if (m.pixelhqLiveError) {
    LIVE_ERR = String(m.pixelhqLiveError).slice(0, 160);
    liveTab();
    return;
  }
  if (m.pixelhqTriageResult) {
    triageTrips.finish('triage', m.pixelhqTriageResult);
    const r = m.pixelhqTriageResult;
    pushRes(!!r.ok, r.message || r.error || '?');
    blk();
    return;
  }
  if (m.pixelhq && Array.isArray(m.pixelhq.bots)) {
    DATA = m.pixelhq;
    if (!rosterDirty && !rosterBusy()) {
      rosterSaved = null;
    }
    try {
      renderAll();
      window.parent.postMessage({ pixelhqRendered: DATA.bots.length }, '*');
    } catch (err) {
      setStand('render error: ' + err);
      window.parent.postMessage({ pixelhqRenderError: String(err) }, '*');
    }
  } else if (m.pixelhqError) {
    setStand('error: ' + String(m.pixelhqError).slice(0, 120));
  } else if (m.pixelhqLoading) {
    setStand('loading …');
  }
});
document.getElementById('reload').onclick = () => {
  if (EMBED) {
    window.parent.postMessage({ pixelhqReload: true }, '*');
    setStand('loading …');
  } else {
    location.reload();
  }
};
if (DATA && DATA.live) {
  LIVE = DATA.live;
}
applyAppearance();
if (DATA) {
  renderAll();
} else {
  setStand(EMBED ? 'loading …' : 'no data – run render.py');
  if (EMBED) {
    window.parent.postMessage({ pixelhqReady: true }, '*');
  }
}
