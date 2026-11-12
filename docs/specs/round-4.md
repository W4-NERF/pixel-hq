# Round 4 — Bot configuration and update notice (spec, binding)

Base: `round-3` at the 1.2.0 tree (`108ac01` on public `main`). Target version **1.3.0**.
Rounds 1–3 stay in force, in particular the sandbox contract (round-2 §0.1), the render rules (D8/D16), the
write-path rule (a request body never chooses a path) and "no autonomous prompts".

## 0. What the operator asked for

1. Every bot has its own configuration (SOUL.md and more). Show it at the bot and edit it easily.
   Decisions: **edit SOUL.md**; **show** model pin, skills, toolsets and MCP servers (read-only; switching stays in
   Hermes' own profile editor). Raw `config.yaml`, `.env`, `auth.json` and memory files are **not** shown.
2. An **"Update available"** info button — for **Pixel HQ itself** only.
3. Bots on other hosts are included **when the Desktop app has a connection to them**; otherwise the card says so.
4. Saving a SOUL: a **diff preview with a second confirming click**, and the **previous version stays restorable**.

## 1. Data sources (no new file reads of other profiles' secrets, no new network calls by the plugin)

- **Profile data** comes from Hermes' own profile-editor RPC, the same one Hermes Desktop's Bot Mode editor uses:
  `profiles.describe {name}` → `{name, description, soul, model{provider, default}, skills[], toolsets[],
  toolsets_pinned, mcp_servers[]}` and `profiles.configure {name, soul}` → `{ok, applied{soul}}`.
  Read the contracts in the Hermes source snapshot
  (`tui_gateway/contracts/profiles_vault_complete_foreign_subagents.py`, `tui_gateway/methods_profiles.py`).
- **Routing.** Local profiles: `host.request('profiles.describe', {name})` on the active gateway (root home).
  Remote bots (`remote: true` in the roster): find exactly one descriptor in `host.profileRoutes()` whose
  `profile` or `targetProfile` equals the bot id and use `host.requestProfile(route, method, params)`. None found →
  state `unreachable` ("Not reachable from this Desktop"). More than one → state `ambiguous`, nothing is called.
- **Feature detection.** Missing `host.request` / `host.requestProfile` / `host.profileRoutes`, or a gateway that
  answers "unknown method" → state `unsupported` ("This Hermes version has no profile editor API"). No fallback
  that reads or writes profile files directly.
- **Update check** uses Hermes' own plugin list: `plugins.manage {action: "list"}` (contract `AgentPluginRow` in
  `tui_gateway/contracts/tools_mcp_plugins.py`: `version`, `catalog_name`, `installed_sha`, `catalog_sha`,
  `catalog_version`, `update_available`, `update_target`). The row for this plugin is the one whose `key` or
  `name` is `pixel-hq`. Hermes runs its own update check (default every 24 h); the plugin asks at page load and
  at most every 6 h, never per snapshot.

## 2. Configuration panel on the character card (card R4-03, bridge R4-02)

- A **Config** section on the bot's character card, collapsed by default; opening it loads `profiles.describe`
  once (cached for the page until Save or an explicit **Reload**). States: loading · ready · unreachable ·
  ambiguous · unsupported · error (message clipped to 200 characters, escaped).
- **Read-only facts:** model `provider / default`; description; skills (enabled count of total, list of disabled
  names); toolsets (enabled names, pinned yes/no); MCP servers (name, transport, enabled). Long lists collapse
  after 12 entries ("+N more"). A hint names where to change them: "Change model, skills and toolsets in Hermes
  (Bot Mode → Edit)". No deep link unless the SDK documents one.
- **SOUL editor:** monospace textarea with the current SOUL; **Edit** → editing; **Preview changes** shows a
  line diff (added/removed lines, unchanged context collapsed to 3 lines around changes; at most 400 diff lines
  rendered, then "diff truncated"). From the preview: **Confirm save** (armed button, second click; same
  `armedButton` as Discard) or **Back to editing**. **Cancel** drops the draft. Unchanged text → no Save.
- **Limits:** SOUL ≤ 64 KiB UTF-8 after normalisation of line endings to `\n`; NUL and other C0 controls except
  `\t` `\n` are rejected with an inline message. The text is otherwise stored verbatim (no trimming, no
  re-formatting). If the loaded SOUL contains a `## Messaging other agents` heading and the draft does not, the
  preview shows a warning line ("The Bot Mode messaging section was removed") — saving stays possible.
- **Render rules:** the textarea is never re-rendered while focused or while a draft exists (D8/D16); snapshot and
  live refreshes do not touch the panel's draft.

## 3. Save protocol (bridge R4-02, backend R4-01)

Every save — edit or restore — runs these steps in `desktop/plugin.js`, in this order, with one request id:

1. **Re-read:** `profiles.describe` again. If `sha256(soul)` differs from the hash the editor was opened with →
   result `conflict` ("The SOUL changed since you opened it. Reload to see the current version."); nothing is
   written.
2. **Backup:** POST the *current* SOUL to the backend route `/soul-history` with `{bot, sourceKey, text, rid}`.
   The backend writes it (§4). Backup failure → stop, nothing is written to the profile.
3. **Write:** `profiles.configure {name, soul: draft}`. `ok:false` or `applied.soul !== true` → result `failed`.
4. **Read-back:** `profiles.describe` once more; `sha256(soul) === sha256(draft)` → `saved`, else
   `unverified` ("Saved, but the read-back differs").
- Round trips use the existing trip/timeout machinery (TRIP_MS, late results replace the timeout message,
  recoverable controls). A save never submits a prompt and never touches any other profile section.

## 4. SOUL history (backend R4-01) — the only new write path of the plugin

- Location: `<root>/plugin-data/pixel-hq/soul-history/<key>/` where `<key>` is derived by the backend from
  `sourceKey` + bot id: `[a-z0-9][a-z0-9._-]{0,63}` after lower-casing; anything else is refused (400). Local
  bots use `sourceKey = "local"`; remote bots use the route's `connectionId` (validated the same way). The
  request never contains a path.
- Files: `<UTC yyyymmddThhmmssZ>-<rid>.md` (full rid, see R4-D1) (UTF-8, the previous SOUL verbatim), written atomically
  (temp file + `os.replace`), mode 0600, directories 0700. Same symlink / non-regular-file refusals as
  `roster.json`. Size limit 64 KiB per file. Retention: the newest **10** per key; older ones are deleted by the
  backend after a successful write. Same `rid` twice → no second file (idempotent retry).
- `GET /soul-history?bot=…&sourceKey=…` → newest first: `[{id, savedAt, bytes, firstLine}]` (firstLine ≤ 80
  characters). `GET /soul-history/item?bot=…&sourceKey=…&id=…` → `{text}`; `id` must match one listed file name
  exactly.
- **Restore** in the UI: the history list in the Config panel (newest first); **Preview** shows the diff from the
  current SOUL to the chosen version; **Confirm restore** runs the same save protocol (§3), so the replaced
  version is itself backed up.

## 5. "Update available" (card R4-04)

- When the Pixel HQ row reports `update_available: true`, the header shows a small **Update available** button
  (accent colour, keyboard focusable). Click → an info panel: installed version (+ short sha), available version
  (`catalog_version` or `update_target`, short sha), the two steps "Update in Hermes (Capabilities → Plugins) or
  run `hermes plugins update pixel-hq`" and "then restart the gateway", and an **Open Plugins** button
  (`host.navigate('/capabilities?tab=plugins')`, feature-detected). The plugin never updates itself.
- No row, `update_available` false/null, or an install that is not from the catalog and has no `update_target`
  → no button; the footer keeps one quiet line, e.g. "Update check: up to date (catalog 1.3.0)" or "Update check:
  not available for this installation". Errors → footer line only, never a toast.
- Standalone page: no button (no host).

## 6. Disclosure and documentation (card R4-05)

- README "What it reads and writes": profile data through Hermes' `profiles.describe` (SOUL, model pin, skills,
  toolsets, MCP server names); SOUL writes only through `profiles.configure`, only after preview and a second
  click; the SOUL history in `plugin-data/pixel-hq/soul-history/` (10 versions per bot, previous SOULs verbatim);
  the plugin list read through `plugins.manage list` for the update notice. Remote bots only through Desktop
  connections.
- CHANGELOG `[1.3.0]`; `plugin.yaml` version 1.3.0; `requires_hermes` stays unless a used method needs more —
  then state the measured floor.
- Catalog description text for the later SHA-bump PR in `var/` (not in the repository).

## 7. Tests and gates (every card)

- Python: history store (key validation, atomic write, 0600, retention 10, idempotent rid, symlink refusal,
  size limit, list/item round trip, path traversal attempts), route tests with the existing TestClient setup.
- Bridge (Node harness, host simulated): local vs. remote routing, unreachable/ambiguous/unsupported, the four
  save steps in order, conflict, backup failure stops the write, `applied.soul` false, read-back mismatch,
  timeout + late result, update-check caching (≤ 1 call per 6 h) and row selection.
- DOM: panel states, editor not re-rendered while focused, diff preview, armed confirm, Messaging-section
  warning, history list + restore preview, update button/info panel, no button on the standalone page.
- Gates as in round 3 §7 (pytest, jscheck, jslint, funclen, contrast, render --demo). Demo data gets synthetic
  `profiles.describe` answers so the standalone demo shows a filled read-only panel (editing disabled there).
- **Never** run anything against real profiles: no test, probe or harness may call a real gateway.

## 8. Out of scope

Editing model/skills/toolsets/MCP, memory files, raw config files, `.env`; creating or deleting profiles;
self-update; update notices for other plugins or Hermes itself; avatars.

## 9. Producer decisions after review R4-R (binding)

- **R4-D1 — idempotency uses the full request id.** History file names carry the full validated rid
  (`[a-z0-9]{8,32}`): `<UTC yyyymmddThhmmssZ>-<rid>.md`. Two different rids never count as one save, whatever
  their prefix. The listed `id` is the file name.
- **R4-D2 — one save, one final answer.** The bridge keeps saves in flight by rid: a repeated `pixelhqSoulSave` with
  the rid of a save that is still running gets **no** reply of its own (it is attached to the running save); a
  repeat after the save finished gets the cached final result again (last 20 results, 10 minutes). The page
  applies the final result of the rid it is waiting for whenever it arrives, also after its own timeout; a
  timeout is never final for `saved` / `unverified`. If the panel has moved on (another save started, the bot
  changed, the panel was closed), a late result is shown as a note only.
- **R4-D3 — replies never replace a focused or drafted editor.** A describe reply that arrives while a draft
  exists or the textarea has focus updates the base (SOUL text and hash) without re-rendering the textarea and
  shows "Current version loaded — your draft is kept". The next preview diffs against the new base. Everything
  else in the panel renders through `renderUnlessFocused`.
- **R4-D4 — symlink policy as for the roster.** The files of the history and the directories the plugin creates
  for it (`soul-history/`, `soul-history/<key>/`) must not be symlinks or other non-regular entries; the
  user-managed locations `plugin-data/` and `plugin-data/pixel-hq/` may be symlinks (same rule as `roster.json`,
  whose directory may live on another disk). The reviewer's probe `test_history_store_refuses_symlinked_parent_
  not_only_leaf` is adjusted accordingly (it links `soul-history/` instead of `plugin-data/pixel-hq`).
- **R4-D5 — the history order is the backend's.** The page shows the list in the order the backend returns it
  (newest first by write time) and never re-sorts it.
- **R4-D6 — every update-check outcome is cached.** The bridge caches `available`, `current`, `unavailable` and
  `error` alike for 6 h per plugin process; reopening the page does not trigger a new `plugins.manage` call.
- **Contract note.** `AgentPluginRow.update_target` exists from Hermes 0.22.3 as `str | None` ("a commit or a feed
  version"); 0.22.2 has `update_available` without it. Keep the defensive string handling; `requires_hermes`
  stays `>=0.22.2` because every new feature degrades to `unsupported` / "not available" on older gateways
  (`profiles.describe` exists in 0.22.2).
