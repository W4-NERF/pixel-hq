# Test suite
Run from the repository root with Python 3, pytest, PyYAML, FastAPI, httpx and Node installed.
Set `PYTHONPATH` to include the supplied Python toolchain (if needed) and the repository root.
Choose a writable disk-backed `TMPDIR`, then run `pytest -q --basetemp=$TMPDIR/bt`.
If no pytest launcher is installed, use `python3 -m pytest` with the same arguments.
Run `python3 tools/jscheck.py`, `python3 tools/jslint.py` (line and function length of the UI sources) and
`python3 pixelhq/render.py --demo` for the other gates.
`fixtures.py` builds temporary homes: default/ops-bot locally, remote-bot in the roster only.
Both platform/website boards are real SQLite fixtures; website omits optional task columns.
Each local profile has a state.db; JSONL reviews/config/rosters use invented data under tmp_path.
`conftest.py` denies sockets and real CLIs; actions fake subprocess.run, UI probes use local Node stubs.
The DOM harness `ui_dom.cjs` also models pointer input for the Office floor edit mode (`tests/test_floor_edit.py`): `pointer.down/move/up/cancel/click(x, y)` bubble through `on<type>` properties to the document listeners, `document.elementFromPoint` hits elements that have a box (`el.rect` or the test's `document.layout` hook), `setPointerCapture` is a no-op. Geometry is otherwise not modelled.
`tests/test_floor_stats.py` covers the department and room numbers of the Office floor (`28-stats.js`: `zoneStats`, `roomStats`, `compactN`) in the same harness; `demo.py` pins a few bots so that two departments always show non-trivial numbers.
