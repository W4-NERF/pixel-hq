# Changelog

All notable changes to Pixel HQ are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version dates below come from git history;
verification limits are stated separately from implemented changes.

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
