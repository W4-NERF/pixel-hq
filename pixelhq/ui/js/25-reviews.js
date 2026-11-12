/* ---- UI reviews: drafts survive polling; only Confirm sends a host message ---- */
const reviewDrafts = new Map();
const reviewTrips = hostTrips(TRIP_MS.other, (key) => refreshReviewRows(key));
const reviewKey = (agent, sessionId) => JSON.stringify([agent, sessionId || null]);

/* Request id of a review draft (D21): 24 lowercase hex characters, created when the draft opens, kept for every retry. */
function fillRandom(bytes) {
  const api = typeof crypto !== 'undefined' ? crypto : null;
  if (api && typeof api.getRandomValues === 'function') {
    try {
      api.getRandomValues(bytes);
      return;
    } catch (e) {
      /* use the fallback */
    }
  }
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = Math.floor(Math.random() * 256);
  }
}

function newRid() {
  const bytes = new Uint8Array(12);
  fillRandom(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function reviewBody(key) {
  const d = reviewDrafts.get(key);
  const pending = reviewTrips.busy(key);
  const r = reviewTrips.result(key);
  let h = '<div class="acts"><span class="mut">Rate:</span>' +
    ['pass', 'revise', 'fail'].map((v) =>
      '<button type="button" data-rate="' + v + '"' + (d && d.verdict === v ? ' class="on"' : '') +
        (pending ? ' disabled' : '') + '>' + v + '</button>'
    ).join('') +
    '</div>';
  if (d) {
    h += '<div data-review-form><fieldset' + (pending ? ' disabled' : '') + '><div class="review-dims">' +
      ATTR_T.map((name) =>
        '<label>' + esc(name) + '<select data-review-dim="' + name + '">' +
          [1, 2, 3, 4, 5].map((v) =>
            '<option value="' + v + '"' + (v === d.dims[name] ? ' selected' : '') + '>' + v + '</option>'
          ).join('') +
          '</select></label>'
      ).join('') +
      '</div>' + '<label class="review-ref">Ref<input data-review-ref type="text" maxlength="200" value="' +
      esc(d.ref) +
      '"></label><div class="acts"><button type="button" data-review-confirm>Confirm</button>' +
      '<button type="button" data-review-cancel>Cancel</button></div></fieldset></div>';
  }
  if (pending) {
    h += '<div class="res" role="status">Saving review …</div>';
  }
  if (r) {
    h += '<div class="res ' + (r.ok ? 'ok' : 'bad') + '" role="status">' +
      esc(r.message || r.error || 'No review result received.') + '</div>';
  }
  return h;
}

function reviewHtml(agent, sessionId, ref) {
  if (!EMBED) {
    return '';
  }
  const key = reviewKey(agent, sessionId);
  return '<div class="review" data-review="' + esc(key) + '" data-agent="' + esc(agent) + '" data-session="' +
    esc(sessionId || '') + '" data-ref="' + esc(String(ref || '').slice(0, 80)) + '">' + reviewBody(key) + '</div>';
}

function refreshReview(el) {
  renderDirect(el, () => {
    el.innerHTML = reviewBody(el.dataset.review);
    bindReview(el);
  });
}

function bindReview(el) {
  const key = el.dataset.review;
  el.querySelectorAll('[data-rate]').forEach((btn) =>
    (btn.onclick = () => {
      if (reviewTrips.busy(key)) {
        return;
      }
      const previous = reviewDrafts.get(key);
      reviewDrafts.set(
        key,
        {
          agent: el.dataset.agent,
          sessionId: el.dataset.session || null,
          verdict: btn.dataset.rate,
          dims: previous ? previous.dims : Object.fromEntries(ATTR_T.map((name) => [name, 4])),
          ref: previous ? previous.ref : el.dataset.ref,
          rid: previous ? previous.rid : newRid()
        }
      );
      reviewTrips.forget(key);
      refreshReview(el);
    })
  );
  const d = reviewDrafts.get(key);
  const form = el.querySelector('[data-review-form]');
  if (!d || !form) {
    return;
  }
  el.querySelectorAll('[data-review-dim]').forEach((input) =>
    (input.onchange = () => {
      d.dims[input.dataset.reviewDim] = Number(input.value);
    })
  );
  const ref = el.querySelector('[data-review-ref]');
  ref.oninput = () => {
    d.ref = ref.value.slice(0, 200);
  };
  el.querySelector('[data-review-cancel]').onclick = () => {
    if (reviewTrips.busy(key)) {
      return;
    }
    reviewDrafts.delete(key);
    reviewTrips.forget(key);
    refreshReview(el);
  };
  const confirm = el.querySelector('[data-review-confirm]');
  confirm.onclick = () => {
    if (reviewTrips.busy(key)) {
      return;
    }
    const body = {
      agent: d.agent,
      verdict: d.verdict,
      dims: { ...d.dims },
      ref: d.ref,
      sessionId: d.sessionId,
      rid: d.rid
    };
    roundTrip(
      reviewTrips,
      key,
      undefined,
      { pixelhqReview: body },
      (r) => onReviewResult({ ...r, agent: body.agent, sessionId: body.sessionId }),
      () => refreshReview(el)
    );
  };
  ref.onkeydown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      confirm.onclick();
    }
  };
}

function bindReviews(root) {
  root.querySelectorAll('[data-review]').forEach(bindReview);
}

const refreshReviewRows = (key) =>
  document.querySelectorAll('[data-review]').forEach((el) => {
    if (el.dataset.review === key) {
      refreshReview(el);
    }
  });

function onReviewResult(r) {
  const key = reviewKey(r.agent, r.sessionId);
  if (!reviewTrips.finish(key, r)) {
    return;
  }
  if (r.ok) {
    reviewDrafts.delete(key);
  }
  refreshReviewRows(key);
}
