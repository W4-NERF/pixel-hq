# Test suite
Run from the repository root with Python 3, pytest, PyYAML, FastAPI, httpx and Node installed.
Set `PYTHONPATH` to include the supplied Python toolchain (if needed) and the repository root.
Choose a writable disk-backed `TMPDIR`, then run `pytest -q --basetemp=$TMPDIR/bt`.
If no pytest launcher is installed, use `python3 -m pytest` with the same arguments.
Run `python3 tools/jscheck.py` and `python3 pixelhq/render.py --demo` for the other gates.
`fixtures.py` builds temporary homes: default/ops-bot locally, remote-bot in the roster only.
Both platform/website boards are real SQLite fixtures; website omits optional task columns.
Each local profile has a state.db; JSONL reviews/config/rosters use invented data under tmp_path.
`conftest.py` denies sockets and real CLIs; actions fake subprocess.run, UI probes use local Node stubs.
