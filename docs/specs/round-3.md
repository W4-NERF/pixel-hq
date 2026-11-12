# Pixel HQ — Round 3 spec: Departments

Status: binding for cards R3-01 … R3-05 (branch `round-3`) and R3-D (branch `round-3-docs`). Everything in
`docs/specs/round-1.md` and `docs/specs/round-2.md` (sandbox contract §0.1, decisions §7 and §8) stays in force.
A builder who finds a contradiction blocks with `kanban_block --kind needs_input` and names the two places.

## 0. What the operator asked for

- A **department** is a zone. Rooms stay as the level above (the location). Both are fully editable in the UI.
- Bots are assigned to a department by **drag & drop on the Office floor** in an edit mode; the select in the Roster
  tab stays as the alternative.
- A bot belongs to exactly one department.
- Each department shows its **numbers on the floor**: members, active, blocked, average HP, XP.
- Not wanted: department ranking in the leaderboard, department colour or emblem, department lead, tags.

File format keys stay `rooms` / `zones` (existing rosters keep working). In the UI a zone is called "department".

## 1. UI source layout (card R3-01, no behaviour change)

- `pixelhq/ui/app.js` is replaced by ordered files in `pixelhq/ui/js/` (`NN-name.js`, e.g. `00-core.js`,
  `10-host-trips.js`, `20-render-guard.js`, `30-office.js`, `40-live.js`, `50-leaderboard.js`, `60-blocked.js`,
  `70-roster.js`, `90-boot.js`). `page.py` concatenates them in file-name order into the one inline script (still no
  build step, one shared scope). `page.bundle_js()` returns that text; tests, `tools/jscheck.py` and the sandbox and
  platform tests use it instead of reading a file path.
- Formatting: one statement per line, lines ≤ 140 characters, functions ≤ 80 lines. Pure data tables (sprite bitmaps,
  palettes, label tables) may sit on long lines only when the line ends with `/* table */`. The same rules apply to
  `desktop/plugin.js` (long prompt lines become arrays of short strings joined at runtime; the text stays identical).
- `tools/jslint.py` enforces line and function length for `pixelhq/ui/js/*.js` and `desktop/plugin.js`; it becomes a gate.
- The rendered page behaves exactly as before: every existing test passes with at most a changed source path.

## 2. Rooms and departments in the roster (card R3-02)

Limits (`roster.py`, replaces the round-2 numbers): ≤ 8 rooms, ≤ 24 zones in total, ≤ 200 bots; exactly one main room;
ids and text rules unchanged.

Editor (Roster tab), all on the single shared roster draft:
- **Rooms:** add (id + label), rename, reorder (up/down), set main (radio, exactly one), remove (only when it has no
  departments and is not the main room), optional note (≤ 80).
- **Departments:** add to any room (id + label), rename, move to another room (select), reorder inside the room
  (up/down), quarantine flag (checkbox), remove (only when it has no bots).
- **Bots:** as today; the department select is grouped by room (`optgroup`).
- Layout: one compact row per bot (grid: id · title · role · sprite · department · colour · leader · remove); the colour
  swatches open inline below the row only for the row being edited. The page must stay usable at 1100 px width
  without horizontal scrolling.
- The generated roster (no `roster.json`) is editable the same way; the first Save writes the file.

## 3. Edit mode on the Office floor (card R3-03)

- Button **Edit layout** on the Office tab (embedded page; standalone only with `?actions=1`). Edit mode works on the
  same roster draft as the Roster tab; switching tabs keeps the draft.
- In edit mode the floor is drawn from the draft (placement) and from the snapshot (status, stats).
- **Drag & drop with pointer events** (no HTML5 `draggable`, no new dependency): `pointerdown` on a desk, movement of
  more than 4 px starts the drag, a ghost of the sprite follows the pointer, departments under the pointer are
  highlighted, `pointerup` over a department sets `bot.zone`; `pointerup` elsewhere or `Escape` cancels. The page does
  not scroll or select text while dragging (`touch-action: none`, `user-select: none` on desks in edit mode).
- **Without dragging:** every desk in edit mode has a "Move to…" select (grouped by room) that does the same.
- Department header in edit mode: rename inline, ◀ ▶ reorder, "Move to room…" select, remove (when empty). Room header:
  rename, ▲ ▼ reorder, **＋ Department**, main radio, remove (when empty). Below the floor: **＋ Room**.
- A bar at the top of the floor while the draft differs from the saved roster: "Unsaved layout changes" · **Save** ·
  **Discard** · result line. Save is the existing roster round trip (`roundTrip`, post first); Discard returns to the
  saved roster (two-click armed button). The same bar state is visible on the Roster tab.
- Periodic renders never interrupt the operator: while a drag is active the floor is not re-rendered (deferred like a
  focused field, D8/D16), and no render is started from inside a pointer handler of the element being removed.
- Leaving edit mode keeps unsaved changes and keeps the bar visible.

## 4. Department numbers on the floor (card R3-04)

Every department header (normal and edit mode) shows `members · active · blocked · Ø HP · XP`:
- members = bots whose `zone` is the department;
- active = members that are working right now (same rule as the desk bubble: live data when present, else snapshot status);
- blocked = blocked Kanban cards assigned to a member (same source as the Blocked tab);
- Ø HP = rounded mean of the members' HP values that exist, `–` when none; XP = sum of the members' XP.
Each room header shows the totals of its departments (Ø HP over all members of the room). One pure function
`zoneStats(zoneId)` / `roomStats(roomId)` feeds both; numbers are formatted compactly (`1.2k`), every number has a
`title` tooltip saying what it counts, and the header never wraps into the desks at 1100 px width.
`demo.py` gets data that makes all five numbers non-trivial in at least two departments.

## 5. Hardening and notices (card R3-05)

- Triage: the host accepts a card key only when the same key is in the blockers of its own latest snapshot, and a
  board only when a blocker of that snapshot has it; otherwise `ok:false`, nothing is called.
- Triage prompt: entries of `remoteBots` are included only when they match the profile pattern; `toolsDir` is rejected
  (no prompt, `ok:false`) when it contains control characters or a line break.
- Stale backend: in addition to the footer line, a banner at the top of the page with the D13 text; "Dismiss" hides it
  for this page load.
- Roster errors that name a room or department use the word "department" for zones in the message text.

## 6. Documentation (card R3-D, branch `round-3-docs`, documentation files only)

- `README.md` restructured: what it is · install (gateway restart) · platforms (the catalog lists 1.1.2 since
  2026-11-11; the WSL report stays) · how XP is earned (table: Kanban event or review → verdict → XP; self-review;
  where attributes come from) · the views · settings (table of all 19 keys with type, default, meaning, taken from
  `plugin.yaml`) · roster (rooms, departments, bots, sprites; a short "Departments" paragraph marked
  `<!-- producer: finalise after R3-04 -->`) · what it reads and writes (disclosure) · updating (restart the gateway;
  stale-backend notice) · troubleshooting (blank page or 502, no bots, no XP, review ledger is a symlink, roster is not
  a regular file, WSL offered on Windows) · development (tests and gates).
- `CHANGELOG.md` (Keep a Changelog layout): 1.0.0, 1.1.0, 1.1.1, 1.1.2, 1.2.0 and "Unreleased", each from the git
  history and the specs of that version, with "not verified" notes where the specs say so. No invented facts, dates
  from `git log`.
- The settings table in the README is generated: `tools/settings_table.py` prints it from `plugin.yaml` and
  `tests/test_readme_settings.py` fails when the README differs. Apart from these two files no code, test or spec
  file is changed on this branch. The cards of branch `round-3` do not touch `README.md` or `CHANGELOG.md`.

## 7. Gates (every card on `round-3`)

`python3 -m pytest -q` green · `python3 tools/jscheck.py` · `python3 tools/jslint.py` (from R3-01) ·
`python3 tools/funclen.py` · `python3 tools/contrast.py` · `python3 pixelhq/render.py --demo` writes a page with
`"demo": true`. The DOM harness (`tests/ui_dom.cjs`) models pointer events for R3-03 (pointerdown/move/up with
coordinates, `elementFromPoint`, `setPointerCapture` as a no-op) — a drag that is only tested by calling the drop
function directly does not count.

## 8. Out of scope

Leaderboard changes, department colours/emblems/leads/tags, image avatars, new data sources, screenshots and video.

## 9. Producer decisions after review R3-R (binding)

- **R3-D1 — recruit fallback never names a missing department.** A profile that is not in the roster is placed in
  the first department of the main room. If the main room has no department: the first department in file order
  (rooms in order, departments in order). The literal fallback id `ops` is removed. Collector and UI use the same
  rule; an empty main room stays allowed. A roster without any department is invalid as before (warning + default).
- **R3-D2 — a drag belongs to one pointer.** `pointercancel` is handled only for the pointer that started the drag,
  exactly like `pointermove` and `pointerup`.
- **R3-D3 — "unsaved changes" is a comparison, not a flag.** Both bars (Office floor and Roster tab) show exactly
  when the draft differs from the last loaded or saved roster. The check runs after the mutation; undoing a change
  by hand hides the bars again. Updating the bars never re-renders the field that has the focus (round-2 D8/D16).
- **R3-D4 — one public release.** 1.2.0 has not been published; the department features ship in it. The plugin
  version stays `1.2.0`; `CHANGELOG.md` has no `[Unreleased]` section at release.
