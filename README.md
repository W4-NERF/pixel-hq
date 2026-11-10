# Pixel HQ — a gamified HQ for your Hermes bot fleet

![Pixel HQ demo](docs/demo.gif)

*22-second highlight (synthetic data). Full 57-second demo: [1080p](https://github.com/W4-NERF/pixel-hq/releases/download/v1.0.0/pixel-hq-demo.mp4) · [720p](https://github.com/W4-NERF/pixel-hq/releases/download/v1.0.0/pixel-hq-demo-720p.mp4)*

Pixel HQ is a [Hermes Agent](https://github.com/NousResearch/hermes-agent) desktop plugin that turns your
fleet of Hermes profiles into a pixel-art headquarters: every bot is a sprite at a desk, earns **XP and
levels** from your quality reviews, keeps **HP** from its pass rate, and shows what it is doing **right
now**. Blocked Kanban cards get a triage board with one-click actions, and your GPU/LLM serving stack
shows up as the **reactor**.

It is a read-only mirror of data Hermes already has — sessions, the Kanban boards, a quality ledger,
Prometheus — rendered as a game. Writes require your explicit Kanban action or review confirmation.

## Views

| Office | Live |
|---|---|
| ![Office](docs/screens/office.png) | ![Live](docs/screens/live.png) |
| **Leaderboard** | **Blocked** |
| ![Leaderboard](docs/screens/leaderboard.png) | ![Blocked](docs/screens/blocked.png) |

- **Office** — rooms and zones from your roster (main host, outposts, quarantine for untrusted models), a
  sprite per profile with a speech bubble showing its current step, a character card (level, XP, HP,
  attributes, open quests, achievements) and the event log.
- **Live** — what every bot is doing *right now*: active sessions with the current step
  (`terminal command running (42s)`, `receiving stream response`, …), the last tool call and its
  argument, token/cost counters, sub-agents nested under their parent session, running Kanban cards with
  heartbeat age. Stuck steps (no progress for 5 min) turn red. Polled every 10 s while the page is open.
- **Leaderboard** — rank by level, XP, HP or blocked cards; pass/revise/fail record, status, current quest,
  model.
- **Blocked** — every blocked Kanban card across all boards, filed into *waiting for you*, *technically
  stuck*, *stale*, *no reason* and *waiting upstream*, with reason, age, last comment and upstream cards.
  Actions per category: **Answer & unblock** (your answer becomes the unblock reason the bot continues
  with), **Retry**, **Comment**, **Archive** (workspace backed up first). A **Triage run** button opens a
  new chat with your orchestrator profile that reviews the selected cards and hands you one decision
  package — nothing is changed without your go.
- **Reactor** — GPU utilisation/power per node (DCGM) and serving metrics (decode/prefill tok/s, running /
  waiting requests, KV-cache, speculative-decoding acceptance, TTFT) from any vLLM-style metric family.

## Demo video

The GIF above is a highlight cut; the full 57-second walkthrough (1080p and 720p, synthetic data) is attached to the
[latest release](https://github.com/W4-NERF/pixel-hq/releases/latest). Both are rendered deterministically from
the demo page — see [`docs/video/`](docs/video/README.md) to re-render them.

## Game rules

| | |
|---|---|
| XP | pass +10 · revise +3 · fail −5 (configurable) |
| Level | `1 + floor(sqrt(XP / 25))` |
| HP | pass rate over all reviews |
| Attributes | Precision / Stamina / Discipline / Wisdom = average correctness / completeness / format / safety |
| Summons | sub-agents and helpers count for the bot that spawned them (ledger field `parent`) |
| Achievements | Centurion (100+ passes), Clean record, Summoner, Mirage (hallucinated references), Gridlock, Battered |

XP comes from a **quality ledger**: one JSON line per reviewed delegated answer (`agent`, `verdict`
pass/revise/fail, `dims` correctness/completeness/format/safety 1–5, optional `parent`). If you do not keep
one yet, Pixel HQ still works — everyone starts at level 1 and the live, Kanban and reactor views carry the
page. See `docs/ledger.md` for the format.

## Install

```bash
hermes plugins install W4-NERF/pixel-hq      # or from the Hermes plugin catalog: hermes plugins install pixel-hq
hermes plugins enable pixel-hq
```

Then **restart the Hermes gateway once** (`hermes gateway restart`; the backend routes mount when the gateway starts) and open **Pixel HQ** in the
sidebar or via ⌘K → *Open Pixel HQ*. If you run Hermes with profiles, enable the plugin in the root home
(the desktop backend runs there) and in any profile that should see it:
`hermes -p <profile> plugins enable pixel-hq`.

### Platforms

| Platform | Status |
|---|---|
| Linux | Developed and tested here. |
| Windows (native Hermes) | Use **1.1.2 or later**: earlier versions check whether the gateway is alive with a call that, according to the Python documentation, terminates the process on Windows (not reproduced). Until the plugin catalog lists 1.1.2, install from this repository (`hermes plugins install W4-NERF/pixel-hq`), not from the catalog. 1.1.2 ran on one Windows machine that already had WSL installed. On one machine without WSL, WSL was installed while Pixel HQ was being set up (one report). Pixel HQ does not call WSL itself and we have not found what triggers this, so expect that it may happen. |
| macOS | Not tested. |

### Configure

Open **Settings → Plugins → Pixel HQ** in the Hermes Desktop app. The form exposes all 18 optional
settings declared in `plugin.yaml`; Hermes saves them under `plugins.entries.pixel-hq.settings` in its
`config.yaml`, outside the plugin so updates never overwrite them.

For headless setups, copy `pixelhq/config.example.json` to the optional `config.json` below and adjust
only the keys you need. The roster remains a separate, unchanged JSON file:

```
~/.hermes/plugin-data/pixel-hq/config.json   # optional headless settings
~/.hermes/plugin-data/pixel-hq/roster.json   # copy from pixelhq/roster.example.json
```

These paths are relative to the root Hermes home; a custom `HERMES_HOME` is respected, including when
it points to a profile under `profiles/`. A linked development checkout can also keep these files next
to `pixelhq/config.py` as a fallback.

Settings are applied in this order: **defaults < config.json < Hermes plugin settings**. Each explicitly
saved Hermes key replaces the file value, including `false`, `0`, empty strings, lists and dictionaries.
The snapshot's `cfg.settingsSource` reports `hermes` when non-empty Hermes settings are applied, otherwise
`file` for a successfully read settings file or `defaults` when neither source is available. Invalid JSON
falls back to defaults (still overridden by Hermes) and is reported as `cfg.configError`.

- Display and roles: `locale`, `timezone`, `theme_label`, `operator_name` (author of UI comments and
  reviews), and `orchestrator_profile` (receives unattributed helper XP and triage runs).
- Reviews and XP: `reviews_path` (empty uses `plugin-data/pixel-hq/reviews.jsonl` under the root home),
  `legacy_ledger_path` (optional read-only older ledger), `kanban_xp`, `xp_pass`, `xp_revise`, and `xp_fail`.
  Relative ledger paths resolve against `<root Hermes home>/plugin-data/pixel-hq/`, never the server's
  working directory. Absolute paths (including existing symlinks) are honoured as deliberate operator
  choices and may write outside plugin-data; only the default review path is confined there.
- Kanban: `exclude_boards`, `stale_days`, and `needs_input_keywords` for *waiting for you* classification.
- Reactor: the flat keys `prometheus_url`, `metrics_prefix` (`vllm|tensorfold|sglang`), `node_aliases`, and
  `model_endpoint`. Leave both endpoints empty to hide the reactor.
- `roster.json` — rooms, zones and one entry per bot (role, character class, colour, `leader`, `remote`).
  Profiles missing from the roster are added automatically as *Recruits*.

Existing `config.json` files with nested `xp` or `gpu` blocks still work; an explicit flat key wins over
its nested equivalent in the same file. The old `ledger_path` key is accepted as an alias for
`legacy_ledger_path`, unless that flat key is explicitly present.

Changes to settings, roster, collector or UI apply on the next uncached refresh — no restart.

### Try it without a fleet

```bash
python3 pixelhq/render.py --demo && xdg-open dist/pixel-hq.html   # synthetic data, every view
python3 pixelhq/render.py        && xdg-open dist/pixel-hq.html   # your real data as a static page
```

## What it reads and does (disclosure)

**Rate** on a Live session (not its sub-agents) or the Office character card: choose **pass**, **revise** or
**fail**, adjust the four 1–5 scores (default 4) and reference, then **Confirm** or **Cancel**. Only Confirm
appends a review. The reference starts with the session/current quest title (80 characters); edits may use
up to 200 characters. The result appears inline and a successful review refreshes XP and attributes.
Controls are available inside Desktop; `?actions=1` exposes them on the standalone page for demos only
(no backend host there). The footer reports signed raw Kanban/review XP and source warnings.

- **Reads** (read-only, local): each profile's `state.db` (sessions, last activity, last tool call),
  `~/.hermes/kanban/boards/*/kanban.db` (cards, events, comments), the quality ledger, `hermes profile list`.
- **Network**: only the Prometheus and model endpoints you configure (none by default).
- **Kanban writes**, only on your confirmed click, and only through the official CLI `hermes kanban --board … comment |
  unblock | archive`: never into the database, never `archive --rm`. Every action is appended to
  `var/actions.jsonl`; archiving copies the card's workspace to `var/archived-workspaces/` first.
- **Reviews**: confirmed ratings append to `reviews_path` (default
  `~/.hermes/plugin-data/pixel-hq/reviews.jsonl`, created when missing) with UTC time, `source: "ui"` and
  `operator_name` as reviewer. Hermes databases and the optional legacy ledger remain read-only.
- **Triage run**: creates a new chat session with your orchestrator profile and submits a briefing that
  contains only card keys (board/id) — never card text — so untrusted card content cannot steer the prompt.
- No telemetry, no self-update, no credentials. Untrusted text (card titles, session titles, tool
  arguments) is escaped before rendering; the UI runs in a sandboxed iframe.

## Layout

```
plugin.yaml           manifest (no tools/hooks)
__init__.py           no-op register()
dashboard/            backend: /api/plugins/pixel-hq/{snapshot,live,page,blocker/action,review}
desktop/plugin.js     desktop page /pixel-hq (SandboxedFrame + postMessage)
pixelhq/collect.py      snapshot collector (read-only)
pixelhq/live.py         "what is everyone doing" (10-s polling)
pixelhq/actions.py      Kanban actions via the hermes CLI (category whitelist, audit log)
pixelhq/blockers.py     blocked-card details for a triage chat
pixelhq/reviews.py      validated, append-only UI review records
pixelhq/ui/             index.html, style.css, app.js (inlined by page.py; no build step)
pixelhq/demo.py         synthetic data
docs/video/           demo-video renderer (Playwright + ffmpeg), not part of the plugin
```

## Development

Link a checkout and the desktop app hot-reloads the UI; only `dashboard/plugin_api.py` needs an app restart:

```bash
ln -s ~/src/pixel-hq ~/.hermes/plugins/pixel-hq
hermes plugins enable pixel-hq
hermes plugins validate ~/src/pixel-hq --install-deps   # the catalog check
```

Test Kanban actions only against a dedicated sandbox board whose cards have no assignee, and list it in
`exclude_boards`.

## License

MIT — see `LICENSE`. Bundled fonts IBM Plex Mono and Silkscreen are under the SIL Open Font License 1.1
(`pixelhq/fonts/OFL-*.txt`).
