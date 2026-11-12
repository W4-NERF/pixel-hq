# Changelog

All notable changes to Pixel HQ are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version dates below come from git history;
verification limits are stated separately from implemented changes.

## [Unreleased]

### Fixed

- **Reactor**: Prometheus reports `NaN` for an idle server (0/0 ratios, empty histograms); such a sample made the
  whole snapshot fail. Non-finite or malformed samples now show as unknown, an idle KV cache reading of 0 is kept, and
  an unreachable Prometheus is asked once per snapshot instead of up to 15 times with a 4-second timeout each.
- **Blocked**: `needs_input_keywords` match whole words or phrases. The defaults `go` and `gate` matched inside words
  such as *good*, *Django* or *investigate*, which filed technical cards as *waiting for you* and refused **Retry**.
  An archived parent card no longer keeps its child in *waiting upstream* (Hermes releases a child once every parent
  is done or archived).
- **Comment**: the comment text is passed after `--`, so text such as `--help` (which made the CLI print its help and
  report success without posting) or `--author=…` stays the comment body.
- A Kanban action whose follow-up snapshot refresh failed was reported as failed after it had run, inviting a
  duplicate comment or retry. A failed audit-log write after the CLI ran is now a warning instead of an error, and a
  snapshot collected while an action ran is no longer cached as fresh afterwards.
- A roster answer that arrives after the page's timeout no longer completes a newer save (which could mark unsaved
  edits as saved and drop them).
- An invalid `locale` or `timezone` setting (e.g. `en_GB`) no longer blanks the page or fails triage runs; the page
  falls back to `en-GB` / `UTC`.
- **Reload** no longer stays on “loading …” when the snapshot is unchanged; live data that arrives before the first
  snapshot no longer shows a render error; the leaderboard status follows live data; the first desk click after a drag
  and drop is no longer ignored; a request whose timer fires while the system clock was set back still times out.
- Standalone page: card text such as `<!--<script>` can no longer leave the rendered page blank (the embedded data now
  escapes every `<`, `>` and `&`).
- A malformed `hermes_home` in `config.json` falls back to the Hermes home with a warning instead of failing every route.

### Changed

- `POST /soul-history` accepts `application/json` bodies only (415 otherwise), like the other write routes.
- `dashboard/manifest.json` carries the plugin version (it still said 1.0.0).

### Added

- Development tooling: GitHub Actions CI (Ruff, the JS and function-length gates, the test suite on Python 3.11–3.13
  and a demo render on Windows and macOS), Dependabot, pre-commit hooks, `pyproject.toml` (pytest and Ruff settings),
  `requirements-dev.txt`, `.editorconfig` and `.gitattributes`.
- `CONTRIBUTING.md`, `SECURITY.md` (private vulnerability reports), issue forms and a pull request template;
  `docs/ledger.md` describes the current review ledger fields.

### Verification

- Offline test suite: 2154 Python tests, including new regression tests for each fix above; each was checked to fail
  without its fix. The standalone page was rendered in Chromium with a hostile card title.
- The Kanban comment change was checked against the argument parser of `hermes kanban comment` in Hermes 0.19.0
  (argparse, `text nargs="+"`).
- **Not verified:** a real Hermes gateway, the Desktop app, Windows and macOS beyond the CI demo render.

## [1.3.0] - 2026-11-12

### Added

- **Config** section on every character card (collapsed by default): read-only profile facts — model pin,
  description, skills, toolsets, MCP servers — read through Hermes' own `profiles.describe`, with **Reload**.
  Raw `config.yaml`, `.env`, `auth.json` and memory files are not shown.
- **SOUL editor** with a line-diff preview and a second confirming click (**Preview changes** → **Confirm
  save**), a 64 KiB limit with inline messages, a warning when the Bot Mode `## Messaging other agents`
  section is removed, and a save that re-reads, backs up, writes through `profiles.configure` and reads back
  (results: saved, read-back differs, conflict, not written, error, unsupported). One save gives one final
  answer: a retry with the same request id joins the running save or gets the kept answer (last 20, 10 minutes,
  no second write), a late answer after the page's timeout is still applied, and a reply of the profile read
  never replaces the editor you are typing in (the draft is kept; the next preview diffs against the new version).
- **SOUL history**: the previous SOUL is stored before every write under `plugin-data/pixel-hq/soul-history/`
  (newest 10 per bot, mode 0600, atomic writes, one file per request id named with the time and the full id; the
  `soul-history/` directories and files must not be symlinks), listed in the backend's newest-first order with
  **Preview** and **Confirm restore**.
  New backend routes `GET /soul-history`, `GET /soul-history/item` and `POST /soul-history`.
- Bots on other hosts are included when the Desktop app has exactly one connection to them; otherwise the
  card says “Not reachable from this Desktop” (or that more than one connection offers the bot).
- **Update available** button in the header with an info panel (installed and available version, the two update
  steps, **Open Plugins** where the Desktop supports navigation, **Esc** closes) and a quiet footer line in
  every other state. The plugin list is read through `plugins.manage`, at page load and at most every 6 hours (every
  outcome, an error or a missing method included, is kept for those 6 hours);
  the plugin never updates itself. Nothing of this appears on the standalone page.
- Synthetic profile data in the demo snapshot so the standalone demo shows a filled, read-only Config section.

### Changed

- README: new “Bot configuration” section; “What it reads and writes” and “Updating” describe the profile
  calls, the SOUL writes, the history directory and the update check.
- `plugin.yaml` version is 1.3.0; `requires_hermes` stays `>=0.22.2`. The three Hermes calls used
  (`profiles.describe`, `profiles.configure`, `plugins.manage`) are checked at run time: a Hermes version
  without them gives the “no profile editor API” state or “not available” footer line instead of an error.

### Verification

- Offline test suite: 2090 Python tests, including the Node DOM harness and the bridge tests with a simulated
  Desktop host: the SOUL history store and its routes, the four save steps in order with conflict, backup
  failure, `applied.soul` false, read-back mismatch and timeouts, local and remote routing, the diff algorithm,
  the Config panel states, the editor and history flows, the update-notice states and the 6-hour cadence on a
  fake clock. An independent review added ten executable probes; all pass. A contract test runs the version ids
  the backend lists through the bridge and the page.
- By hand in Chromium, with the real `desktop/plugin.js` and the page in a `sandbox="allow-scripts"` iframe
  against a simulated Hermes host: edit, preview (with the Bot Mode section warning) and save, the call order
  re-read, backup, write, read-back, typing while snapshots and theme messages arrive (focus and caret kept),
  a conflict that writes nothing, Reload that keeps the draft, history and restore, a remote bot through a
  Desktop route and without one, the update panel with **Open Plugins** and **Esc**, and the standalone page.
- `requires_hermes` checked against the Hermes release tags: `profiles.describe`, `profiles.configure` and the
  `update_available` field of `plugins.manage` exist in 0.22.2; `update_target` appears in 0.22.3.
- **Not verified:** a run against a real Hermes gateway, the Desktop app, a real remote connection or the plugin
  catalog; touch input; Windows and macOS.

## [1.2.0] - 2026-11-10

### Added

- Rooms and departments are fully editable in the Roster tab (add, rename, move, reorder, main room, remove
  when empty; limits of 8 rooms, 24 departments and 200 bots). Roster messages say "department".
- **Edit layout** on the Office floor: drag and drop of bots between departments with pointer events, a
  **Move to…** select, in-place room and department controls, and a shared **Unsaved layout changes** bar
  with **Save** / **Discard** on the floor and in the Roster tab.
- Department headers show members, active members, blocked cards, average HP and summed XP; room headers show
  the totals of their departments. In edit mode the numbers follow the unsaved draft.
- A stale-backend banner with **Dismiss** next to the existing footer line.
- Generated README settings table from `plugin.yaml`, with a regression test for documentation drift.
- Version history in this changelog.
- Session **Open**, **Talk to this bot** and stale-session **Ask for status** actions. The status action
  prepares a draft without submitting it or replacing an existing draft; unsupported Desktop APIs
  return an inline result.
- Eight class-based sprite variants, explicit roster sprite overrides and a stable-id fallback; leader
  crowns override headgear.
- `appearance` setting (`auto`, `dark`, `light`), host-theme following and palette contrast checks;
  the settings schema now has 19 keys.
- First-run generated-roster guidance and a Roster editor with atomic Save, one-generation backup and
  two-click **Reset to generated**. Validation covers identifiers, text, colour, placement and profiles.
- Installed-versus-running version notice explaining that updates require a gateway restart.

### Changed

- The backend loads one package version per process, publishes its loader atomically and pins the served
  page assets to that version until the gateway restarts.
- Settings and roster files are read only from the root Hermes home's `plugin-data/pixel-hq/` directory,
  not from in-repository fallback files. Supported roster fields survive an unmodified editor save.
- Periodic renders defer while an input is focused; focus-out flushing is scheduled, render re-entry is
  prevented and host requests are posted before rendering.
- Host round trips time out with recoverable controls; late results replace the timeout message.
- The empty `provides_middleware` manifest key was removed for compatibility with older validators.
- The UI source is split into ordered files under `pixelhq/ui/js/` (no behaviour change) and checked by
  `tools/jslint.py`.
- README organised around installation, platform limits, XP sources, views, settings, roster (with a
  Departments section), disclosure, updating, troubleshooting and development.

### Fixed

- A profile that is not in the roster is placed in the first department of the main room, or in the first
  department in file order when the main room has none. The collector no longer falls back to a literal
  `ops` department that may not exist, so a roster without `ops` (for example after an empty main room was
  saved) keeps membership, department numbers and the next save consistent. A `roster.json` without any
  department is invalid: warning and the generated default.
- In edit mode, `pointercancel` is handled only for the pointer that started the drag, like `pointermove`
  and `pointerup`; a cancelled second touch no longer aborts the drag.
- The **Unsaved layout changes** bars compare the draft with the last loaded or saved roster after each
  change. The first keystroke in a bot field shows them on the Office floor and in the Roster tab, restoring
  the original value hides them, and the focused field is not re-rendered.
- The unsaved-layout bar has one fixed height in all its states (**No unsaved changes**, **Save** /
  **Discard**, **Saving roster …**, result line), on the Roster tab always and on the Office floor while edit
  mode is on, so the page no longer jumps when the first change is made, undone or saved.
- The **Move to…** select on each desk in edit mode is no longer cut off: a floor-wide rule had overridden its
  small font size.
- Triage scope is checked against the host's latest snapshot, and prompt values (remote bot ids, tools
  directory) are validated before the prompt is built.
- Roster saves, raw-id lookups, shared text validation and token-based sprite keyword matching.
- Composer-readiness retries for status drafts and feature detection for SDK/theme capabilities.
- Retried UI reviews reuse a request id and do not append again when the id is in the ledger's last
  64 KiB. The review writer refuses symlinked ledgers; roster Save/Reset refuse non-regular roster and
  backup files, including symlinks.
- Triage selection text is built by the host from validated filters, not page-supplied prose; action
  buttons are whitelisted and cannot re-submit while busy.
- The Windows-safe process probe and optional POSIX-only imports from 1.1.2 are retained.

**Verification:** in the Hermes Desktop app on Linux (2026-11-12) the page loaded with the installed
version and the layout editing worked: drag and drop between departments, two-click **Discard**, **Save**
and **Reload**, and the unsaved-layout bar. Before that, the department features were checked with offline
Python tests (1637), the Node DOM harness, a review with executable probes, and by hand in Chromium with the
page in a `sandbox="allow-scripts"` iframe and a simulated host. **Not verified:** touch input, macOS, and
1.2.0 on Windows (the clean-machine Windows test used 1.1.2).

Sources: [round-2 spec](docs/specs/round-2.md) (§0.1, §7–§8) and [round-3 spec](docs/specs/round-3.md)
(including the producer decisions in §9).

## [1.1.2] - 2026-11-10

### Fixed

- Gateway liveness checks use a read-only Windows `OpenProcess` / `WaitForSingleObject` probe, not
  `os.kill(pid, 0)`. The POSIX existence check stays on POSIX only.
- Review appends work without `fcntl` and use binary mode where available to keep JSONL newlines
  unchanged. POSIX-only imports are optional.

**Verification limits:** the original fix was tested on Linux with the Windows branch forced, not run
on Windows. A later platform report records 1.1.2 running on **one Windows machine with WSL already
installed**. On another machine, WSL was installed during Pixel HQ setup; the trigger is unknown and
Pixel HQ does not call WSL itself. The earlier Windows gateway-termination behaviour was not reproduced;
Windows without WSL is not generally verified. macOS is not tested. Later, on 2026-11-11, a clean
Windows 11 machine with WSL disabled ran Hermes 0.23.1 and Pixel HQ 1.1.2 without starting WSL
(process-creation audit); see the README's Platforms section.

Sources: `54847ec`, round-2 decision D24 and the README's Platforms section.

## [1.1.1] - 2026-11-10

### Fixed

- **Rate → Confirm** works through a plain button click handler, with Enter in the reference input
  taking the same path. The previous form submission was blocked before its handler in the Desktop's
  scripts-only iframe sandbox.

### Added

- Sandbox-contract tests rejecting forms, submit controls, browser storage, modal dialogs, popups and
  colour/file inputs in the embedded UI sources.

Source: `a5fdf25`; [round-2 §0.1 and §1](docs/specs/round-2.md).

## [1.1.0] - 2026-11-10

### Added

- Automatic Kanban outcome XP alongside optional review-ledger XP, with event deduplication, separate
  own/summon floors, signed source totals, level/HP calculation and Kanban-derived attribute fallback.
- UI ratings and the `pixelhq_review` tool, appending reviews to a plugin-data JSONL ledger while Hermes
  databases and optional legacy ledgers remain read-only.
- Desktop plugin settings with typed defaults/coercion and `config.json` as a headless alternative.
- Profile discovery from Hermes-home directories, generated rosters and warnings for malformed data
  or missing SQLite schema elements.
- Offline tests, JavaScript syntax and Python function-length gates.

### Changed

- Self-reviews compare reviewer to the rated agent before helper attribution and give no XP, HP or
  attribute input. An orchestrator may review its helper for summon XP.
- UI markup, styles and script were split into separate source files, still inlined without a build step.
- `provides_tools` is declared at the manifest's top level to match the validator format.

The UI review confirmation still used a form in this version; the sandbox correction shipped in 1.1.1.

Sources: `1df6847`, `d86f083` and [round-1 §1 and §8](docs/specs/round-1.md).

## [1.0.0] - 2026-11-08

### Added

- Pixel-art Office, Live, Leaderboard and Blocked views for Hermes profiles, with review-ledger XP,
  levels, HP, attributes, achievements and optional GPU/LLM reactor metrics.
- Confirmed Kanban actions through the official CLI, action audit logging and workspace backups before
  archiving.
- Standalone static rendering and synthetic demo data, screenshots, highlight GIF and 720p/1080p demo
  videos with a deterministic Playwright/ffmpeg renderer.

### Changed

- Project and plugin renamed from Bot-HQ to Pixel HQ (`pixel-hq`).

Sources: history from `712c909` through the 1.0.0 documentation commit `f059cae`.

[Unreleased]: https://github.com/W4-NERF/pixel-hq/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/W4-NERF/pixel-hq/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/W4-NERF/pixel-hq/compare/v1.0.0...v1.2.0
[1.0.0]: https://github.com/W4-NERF/pixel-hq/releases/tag/v1.0.0
