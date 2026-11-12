/* ---- Layout edit mode of the Office floor, part 3: dragging a desk onto a department with pointer events (no browser
   drag-and-drop API). pointerdown on a desk arms the drag; a movement of more than DRAG_PX pixels starts it: a ghost of the
   sprite follows the pointer and the department under the pointer gets the class `drop`. pointerup over a department moves the
   bot there (the same operation as the "Move to…" select); pointerup elsewhere, Escape, pointercancel or a released button
   cancel. Less movement than that stays a click (the desk is selected as before). While a drag runs `dragging` holds the
   floor's render (20-render-guard.js); it runs when the drag ends, so snapshots, live data and theme changes that arrived
   meanwhile are applied after the drop. The pointer handlers sit on the document, never on a desk that a render removes. ---- */
const DRAG_PX = 4;
let drag = null;
let dragClickBlock = false;

function dragBegin(e, desk) {
  dragClickBlock = false;
  const plain = (e.button || 0) === 0 && !isField(e.target) && !e.target.closest('button');
  if (drag || !plain || !layoutEditing() || rosterBusy()) {
    return;
  }
  drag = { id: desk.dataset.id, desk, x: e.clientX, y: e.clientY, pointer: e.pointerId, started: false, over: '' };
  try {
    desk.setPointerCapture(e.pointerId);
  } catch (err) {
    drag.captured = false; // not capturable: the document listeners still see the pointer
  }
}

function dragLift() {
  const ghost = document.getElementById('drag-ghost');
  const bot = floorBots(true).find((b) => b.id === drag.id);
  drag.started = true;
  dragClickBlock = true;
  dragging = document.getElementById('floor');
  drag.desk.classList.add('dragging');
  dragging.classList.add('drag-active');
  ghost.innerHTML = '<div class="holder">' + (bot ? sprite(bot, 4) : '') + '</div><div class="nm">' + esc(drag.id) + '</div>';
  ghost.classList.add('on');
}

function dragZoneAt(x, y) {
  const hit = document.elementFromPoint(x, y);
  const box = hit && hit.closest('[data-dept]');
  return box ? box.dataset.dept : '';
}

function dragTrack(e) {
  document.getElementById('drag-ghost').style.transform = 'translate(' + (e.clientX + 10) + 'px,' + (e.clientY + 10) + 'px)';
  const over = dragZoneAt(e.clientX, e.clientY);
  if (over === drag.over) {
    return;
  }
  drag.over = over;
  document.getElementById('floor').querySelectorAll('.zone').forEach((zone) => {
    zone.classList.toggle('drop', !!over && zone.dataset.dept === over);
  });
}

/* Ends the drag and removes its marks; the held floor render is NOT started here (the caller decides). */
function dragEnd() {
  const ghost = document.getElementById('drag-ghost');
  const floor = document.getElementById('floor');
  const was = drag;
  drag = null;
  dragging = null;
  ghost.classList.remove('on');
  ghost.innerHTML = '';
  floor.classList.remove('drag-active');
  floor.querySelectorAll('.zone').forEach((zone) => zone.classList.remove('drop'));
  if (was && was.desk) {
    was.desk.classList.remove('dragging');
    try {
      was.desk.releasePointerCapture(was.pointer);
    } catch (err) {
      was.captured = false;
    }
  }
  return was;
}

const dragMine = (e) => !!drag && (e.pointerId === undefined || drag.pointer === undefined || e.pointerId === drag.pointer);

function dragCancel() {
  const was = dragEnd();
  if (was && was.started) {
    flushFloor();
  }
}

function dragMove(e) {
  if (!dragMine(e)) {
    return;
  }
  if (e.buttons === 0) {
    dragCancel();
    return;
  }
  if (!drag.started) {
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) <= DRAG_PX) {
      return;
    }
    dragLift();
  }
  dragTrack(e);
}

function dragUp(e) {
  if (!dragMine(e)) {
    return;
  }
  if (!drag.started) {
    drag = null;
    return;
  }
  const target = dragZoneAt(e.clientX, e.clientY);
  const was = dragEnd();
  if (target) {
    layoutMoveBot(was.id, target);
  } else {
    flushFloor();
  }
}

document.addEventListener('pointermove', dragMove);
document.addEventListener('pointerup', dragUp);
document.addEventListener('pointercancel', (e) => {
  if (dragMine(e)) {
    dragCancel();
  }
});
document.addEventListener('keydown', (e) => {
  if (drag && e.key === 'Escape') {
    dragCancel();
  }
});
