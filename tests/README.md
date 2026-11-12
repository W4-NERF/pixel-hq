# Test suite
Run from the repository root with Python 3.11+, Node 22+ and `requirements-dev.txt` installed.
`pyproject.toml` puts the repository root on `sys.path`; add a supplied Python toolchain to `PYTHONPATH` if needed.
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
`tests/test_soul_diff.py` covers the pure SOUL helpers of the Config section (`37-soul-diff.js`: line diff with context collapse and the 400-line cap, validation, messaging-section rule); `tests/test_config_ui.py` drives the Config section of the character card (`36-config.js`, `38-soul-editor.js`, `39-soul-history.js`) in the DOM harness with the host simulated: panel states, facts, editor/preview/confirm, every save state, history and restore, focus rules and escaping. The harness gained `Element.replaceWith` for the held draft panel.

`tests/test_update_ui.py` drives the update notice (`35-update-notice.js`, header button, panel and footer line in `index.html`) in the DOM harness with a fake `hostClock.now`: button/panel/footer states, Esc and focus, `Open Plugins` only with the bridge flag, escaping, the 6-hour cadence and the standalone page. `tests/test_update_bridge.py` covers the bridge side with the simulated Desktop host: the `canNavigate` flag and the fixed `Open Plugins` route.
