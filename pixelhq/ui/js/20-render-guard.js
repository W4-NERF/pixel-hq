/* ---- No re-render under the cursor (D8): a container that holds the focused input/textarea/select is not re-rendered by
   periodic renders; the render waits until the focus leaves the container and then reads the latest state.
   Render re-entrancy (D16): removing the focused element fires `focusout` synchronously in the middle of the removal, so
   the focusout listener only SCHEDULES one flush (hostClock, 0 ms, coalesced); the flush re-checks the focus. Every render
   of a container goes through renderDirect, which cancels the pending deferral of that container and of the containers
   inside it, and never starts while a render of a related container is running. `deferredRenders` holds the raw draw
   function per container. ---- */
const deferredRenders = new Map();
const rendering = new Set();
let flushScheduled = false;
const isField = (el) => !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || '');
const holdsField = (el, field) => isField(field) && el.contains(field);
const relatedBox = (a, b) => a.contains(b) || b.contains(a);
/* While a pointer drag is active (78-layout-drag.js) `dragging` is the floor: its render waits like a focused field and
   runs when the drag ends (no timer: a held render must not spin the flush loop). */
let dragging = null;
const dragHolds = (el) => !!dragging && relatedBox(dragging, el);
const renderRunning = (el) => [...rendering].some((running) => relatedBox(running, el));
const cancelDeferred = (el) => {
  for (const key of [...deferredRenders.keys()]) {
    if (el.contains(key)) {
      deferredRenders.delete(key);
    }
  }
};

function scheduleFlush() {
  if (flushScheduled || !deferredRenders.size) {
    return;
  }
  flushScheduled = true;
  hostClock.later(flushDeferred, 0);
}

function flushDeferred() {
  flushScheduled = false;
  for (const [el, render] of [...deferredRenders]) {
    if (deferredRenders.get(el) === render && !el.contains(document.activeElement)) {
      renderDirect(el, render);
    }
  }
}

function renderDirect(el, render) {
  cancelDeferred(el);
  if (dragHolds(el)) {
    deferredRenders.set(el, render);
    return false;
  }
  if (renderRunning(el)) {
    deferredRenders.set(el, render);
    scheduleFlush();
    return false;
  }
  rendering.add(el);
  try {
    render();
  } finally {
    rendering.delete(el);
  }
  return true;
}

function renderUnlessFocused(el, render) {
  if (holdsField(el, document.activeElement)) {
    deferredRenders.set(el, render);
    return false;
  }
  return renderDirect(el, render);
}

document.addEventListener('focusout', scheduleFlush);
