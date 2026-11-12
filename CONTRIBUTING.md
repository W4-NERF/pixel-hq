# Contributing to Pixel HQ

Thanks for helping! Bug reports, fixes and focused improvements are welcome. For larger changes, please
open an issue first so the approach can be agreed before you invest time.

## Development setup

You need Python 3.11 or later and Node 22 or later (Node runs the UI syntax checks and DOM tests).

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

To try the plugin in Hermes Desktop, link the checkout as described in the README's
[Development](README.md#development) section. The UI is plain HTML/CSS/JS inlined by `pixelhq/page.py`;
there is no build step.

## Checks

CI runs all of these on every pull request; run them locally before you push:

```bash
python -m ruff check .
python -m pytest -q
python tools/jscheck.py
python tools/jslint.py
python tools/funclen.py
python tools/contrast.py
python pixelhq/render.py --demo
```

`pre-commit install` (after `pip install pre-commit`) runs the fast checks on every commit.
See [`tests/README.md`](tests/README.md) for how the offline test suite and the Node DOM harness work.

## Conventions

- **No runtime dependencies** beyond what the Hermes gateway already provides (FastAPI, PyYAML).
- **Cross-platform**: no POSIX-only modules at import time, and the plugin never signals a process.
- **Offline tests**: tests must not open sockets or call the real `hermes` CLI; `tests/conftest.py` enforces it.
- **Size limits**: functions stay within 80 lines and lines within 140 characters (`tools/funclen.py`,
  `tools/jslint.py`, Ruff); pure data tables in JS may end with `/* table */`.
- **Escaping**: every value placed into HTML in the UI goes through the existing escape helpers.
- **Read-only by default**: anything that writes (Kanban actions, reviews, roster, SOUL) needs an explicit
  user confirmation and must be described in the README's disclosure section.

## Documentation and versions

- Add an entry under `## [Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for user-visible changes.
- After changing `config_schema` in `plugin.yaml`, regenerate the README settings table with
  `python tools/settings_table.py` (`tests/test_readme_settings.py` fails on drift).
- A release bumps `version` in `plugin.yaml` and `dashboard/manifest.json` together
  (`tests/test_versions.py` checks that they match the newest changelog entry).

## Reporting security issues

Please follow [`SECURITY.md`](SECURITY.md) instead of opening a public issue.
