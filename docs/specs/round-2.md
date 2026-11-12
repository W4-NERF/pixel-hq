# Pixel HQ — Round 2 spec: Cockpit

Status: binding for cards R2-00 … R2-03 (branch `round-2`). Round 1 (`docs/specs/round-1.md`, incl. §8 decisions)
stays in force. Producer decisions are final; a builder who finds a contradiction blocks with
`kanban_block --kind needs_input` and names the two places instead of guessing.

## 0. Non-negotiables (in addition to round-1 §0)

- **No autonomous prompts.** The plugin never submits text into an existing session. The triage run stays the only
  `prompt.submit` and it creates its own new session. Round 2 only opens sessions and prepares drafts.
- **Write paths** stay explicit: Kanban actions via the CLI, `reviews.jsonl`, and (new) `roster.json` — the last two
  always under `<root>/plugin-data/pixel-hq/`. A request body can never choose a path.
- Every host capability is feature-detected (`typeof host.x === 'function'`); a missing one yields a result line
  "not supported by this Hermes Desktop version", never an exception.

### 0.1 Sandbox contract (the UI runs in `<iframe sandbox="allow-scripts">`, opaque origin)

Verified in Chromium: inside this sandbox click handlers fire, but **form submission is blocked before the `submit`
event** — an `onsubmit` handler never runs. Therefore `pixelhq/ui/app.js` and `pixelhq/ui/index.html` must not contain:

`<form`, `type="submit"`, `onsubmit`, `requestSubmit`, `.submit(` · `localStorage`, `sessionStorage`,
`document.cookie` · calls to the global `alert(` / `confirm(` / `prompt(` · `window.open` · `<input type="color">`,
`<input type="file">` · `download=` attributes.

All interaction is plain buttons/inputs with click/keydown/change handlers; state lives in memory for the page load;
confirmation is the existing two-click "armed button" pattern. `tests/test_sandbox_contract.py` enforces the list
(regexes on both files, comments excluded).

## 1. Hotfix: Rate → Confirm (card R2-00, ships alone as 1.1.1)

The review form's Confirm is a `<button type="submit">` inside a `<form>` with `form.onsubmit` — dead inside the
Desktop app (§0.1). Replace the `<form>` with a `<div data-review-form>`, Confirm becomes
`<button type="button" data-review-confirm>` with a click handler doing exactly what `onsubmit` did; Enter inside the
`ref` input triggers the same handler. No behaviour change otherwise. Version → 1.1.1. One commit, nothing else in it.

## 2. Jump actions (card R2-01)

Frame → host messages (all validated in `desktop/plugin.js`; `profile` must match `^[A-Za-z0-9._-]{1,64}$`,
`sessionId` must match `^[A-Za-z0-9_.:-]{1,128}$`; invalid → result `ok:false`, nothing called):

| UI | Message | Host action | Result message |
|---|---|---|---|
| **Open** on every session row in Live (also sub-agent rows; profile = the bot the row belongs to) | `{pixelhqOpen:{profile,sessionId}}` | `host.openSession(sessionId,{profile,intent:'tab'})`; if that rejects, retry once without `intent` | `{pixelhqOpenResult:{ok,message,sessionId}}` |
| **Talk to this bot** on the character card (not for roster `remote:true` bots — show muted "runs on another host") | `{pixelhqChat:{profile}}` | `host.newChat(profile)` | `{pixelhqChatResult:{ok,message,profile}}` |
| **Ask for status** on session rows with `stale:true` only | `{pixelhqNudge:{profile,sessionId}}` | open as above, then read the composer draft of that session; if it is empty set the draft to `NUDGE_TEXT` and focus the composer; if not empty leave it untouched. **Never** `host.composer.submit`, never `prompt.submit`. | `{pixelhqNudgeResult:{ok,message,sessionId}}` — "Session opened — status question is in the composer, press Enter to send" or "Session opened — your existing draft was left untouched" |

`NUDGE_TEXT` = `Status check: what are you working on right now, what is blocking you, and what do you need from me? Answer in three short lines.`

Composer API: use `host.composer.getDraft / setDraft / focus` exactly as documented in the "Composer draft API"
section of the Desktop plugin SDK reference (in the Hermes source snapshot named in the card). The handoff cites the
doc lines that define which session id those calls take; if the reference only supports the focused composer
(`null`), use `null` after `openSession` resolved.

UI: buttons use the existing `.acts` styling; each row shows its last result line (`.res ok|bad`, via `esc()`).
Standalone page: buttons only with `?actions=1`, resolved by the existing standalone message.

Tests: Node DOM harness (`tests/ui_dom.cjs`) — buttons present on session rows / sub-agent rows, nudge button only
when stale, no chat button for remote bots, exact message payloads. Bridge tests with a fake `host` in the style of
`tests/test_review_bridge.py` — `openSession` called with the validated args and the retry path; nudge sets the draft
only when empty and never calls `submit`; invalid ids call nothing; missing capability → "not supported…".

## 3. Sprites by class + appearance (card R2-02)

### 3.1 Sprite variants

Variants: `default`, `wizard` (pointed hat), `knight` (helmet with visor), `engineer` (hard hat), `scout` (hood),
`medic` (headband with cross), `scribe` (flat cap), `rogue` (hood + mask). Same 8-wide box-shadow technique; a
variant replaces only the top rows (and at most two accent pixels on the face); the body rows are shared. The leader
crown replaces any headgear. Quarantine eyes stay.

`spriteVariant(bot)` in `app.js` (pure, exported for the harness), first match wins:
1. roster field `sprite` when it is one of the eight names;
2. keyword on `(cls + ' ' + title + ' ' + id).toLowerCase()`, in this order —
   knight `secur|soc|defen|blue|audit|guard|warden` · rogue `red|pentest|offens|attack` ·
   scout `net|firewall|rout|vpn|ranger` · engineer `ops|deploy|docker|ci/cd|build|infra|sysadmin|linux|smith` ·
   wizard `dev|code|coding|program|mage` · scribe `data|db|sql|doc|writ|research|librar|scribe` ·
   medic `help|support|desk|medic`;
3. stable hash of `id` over the eight variants (a fresh fleet of "Recruits" still looks varied).

Server: `config.py` keeps a roster `sprite` value only when valid (else drops it with a warning).
`roster.example.json` documents the field.

### 3.2 Appearance

- New setting `appearance` ∈ `auto | dark | light`, default `auto` (`config_schema` now has 19 keys; invalid → `auto`
  + warning). Exposed as `cfg.appearance`.
- Host: `useTheme().resolvedMode` → `{pixelhqTheme:{mode:'light'|'dark'}}` on ready and whenever it changes.
- Frame: effective mode = setting unless `auto`, else host mode, else `dark`; applied as `data-mode` on `<html>`.
  Standalone: `?mode=light|dark` overrides.
- `style.css`: every colour through custom properties; palettes in exactly two blocks, `:root` (dark, unchanged
  values) and `:root[data-mode="light"]`:
  `--bg:#F4F6F8; --bg2:#E9EDF1; --card:#FFFFFF; --card2:#F0F3F6; --fg:#17202A; --mut:#5B6875; --mut2:#46525E;
  --line:rgba(23,32,42,.16); --olive:#5F7A3A; --rust:#A8521F; --amber:#8A6A12; --green:#3F7F4B`.
- `app.js`: sprite/fixed colours come from one `PALETTE = {dark:{…}, light:{…}}` constant; no other hex literals in
  `app.js`, none in `style.css` outside the two palette blocks (roster colours are data, not literals).
- `tools/contrast.py`: parses both palettes, prints the WCAG contrast of `--fg`, `--mut`, `--mut2`, `--olive`, `--rust`,
  `--amber`, `--green` on `--bg` and `--card`; exits 1 if any is < 4.5 for fg/mut/mut2 or < 3.0 for the accent colours.
  If a given value fails, darken/lighten that value minimally and state the change in the handoff.

Tests: `spriteVariant` table (explicit field, each keyword group, `devops` → engineer, hash stability, crown
override), palette-literal test, appearance precedence (setting > host > default), contrast tool as a test.

## 4. First run + roster editor (card R2-03)

- **Banner** on the Office tab while `cfg.rosterSource === 'generated'`: "Roster generated from your N profiles. Give
  your bots roles, colours and rooms." + button "Customise roster" (opens the Roster tab) + "Dismiss" (hidden for this
  page load only). Standalone demo: `?firstrun=1` forces the banner.
- **Roster tab** (embed mode; standalone only with `?actions=1`): one row per bot — `id` (read-only), `title`, `cls`
  (role), colour (12 swatch buttons + a `#rrggbb` text field), `sprite` (select: auto + eight variants), `zone`
  (select), `leader` (radio, at most one), remove button for remote entries; "Add remote bot" (id field); zones list
  with label edit, "Add zone" (to the main room) and remove for empty zones. Buttons: **Save**, **Reset to generated**
  (two-click armed), result line.
- Messages: `{pixelhqRoster:{roster}}` / `{pixelhqRoster:{reset:true}}` → host `POST /roster` →
  `{pixelhqRosterResult:{ok,message}}`, then a fresh snapshot.
- Backend `pixelhq/roster.py` — `save(body, cfg, profiles) -> {ok, message}`:
  - shape: `rooms[]` `{id,label,main?,zones[]{id,label,quarantine?}}`, `bots[]`
    `{id,cls,title,zone,loc?,color,leader?,remote?,sprite?}`; unknown keys dropped;
  - limits: ids `^[A-Za-z0-9._-]{1,64}$`, labels/`cls`/`title`/`loc` ≤ 40 chars (control characters rejected),
    `color` `^#[0-9a-fA-F]{6}$`, `sprite` one of the eight, ≤ 200 bots, ≤ 6 rooms, ≤ 12 zones in total, exactly one
    `main` room, every bot zone exists, at most one leader, a non-`remote` bot must be an existing profile;
  - any violation → `{ok:false, message}` naming the first problem, nothing written;
  - write: temp file in the same directory + `os.replace` to `<root>/plugin-data/pixel-hq/roster.json`; the previous
    file is kept as `roster.json.bak` (one generation); `reset:true` moves `roster.json` to `roster.json.bak`;
  - the snapshot cache is invalidated on success.
- Route `POST /roster` in `dashboard/plugin_api.py`; `desktop/plugin.js` forwards like `pixelhqReview`.

Tests: validation matrix (each limit), atomic write + backup + reset, the path cannot be influenced by the body,
harness (banner iff generated, editor rows, payload shape, labels escaped), route test in the style of
`tests/test_review_api.py`.

## 5. Gates (every card)

`python3 -m pytest -q` all green · `python3 tools/jscheck.py` · `python3 tools/funclen.py` prints nothing ·
`python3 pixelhq/render.py --demo` writes a page containing `"demo": true` · from R2-02 on `python3 tools/contrast.py`
exits 0. `demo.py` gains what the new UI needs to be visible in the demo (one stale session, mixed sprite classes).

## 6. Out of scope

README/FAQ/CHANGELOG rewrite, screenshots, video (Round 3). New data sources. Image-based avatars. Do not start them.

## 7. Producer decisions after review R2-R (binding)

- **D1 Recruit role length.** The auto-recruit `cls` (profile description) is clipped to 40 characters (ellipsis
  included) so an unedited generated roster always saves. Every `roster.py` error names the entry by id when it has
  one: `bots[1] (id "ops-bot").cls: …`.
- **D2 Lossless save.** A Save of an unmodified roster must not lose anything the schema allows. Rooms gain the
  optional key `note` (≤ 80 characters). The editor builds its payload from the complete roster object, never from a
  reduced projection; keys it does not edit (`note`, `quarantine`, `loc`, `remote`) pass through unchanged.
- **D3 One roster location.** The roster and config are read from `<root>/plugin-data/pixel-hq/` only; the in-repo
  fallbacks `pixelhq/roster.json` / `pixelhq/config.json` are removed. "Reset to generated" therefore always yields the
  generated roster.
- **D4 Ids.** Room and zone ids: `^[A-Za-z0-9_-]{1,64}$` (no dot). Bot ids keep the dot. The UI never compares or keys
  by a transformed id: filters and lookups use the raw id (escaped when written into attributes).
- **D5 Text rule.** Labels reject control characters (Cc), surrogates, unassigned/private-use code points and the
  bidi overrides U+202A–U+202E and U+2066–U+2069; other format characters (ZWJ/ZWNJ, emoji sequences) are allowed.
  One shared definition drives the server check and the UI pre-check; the message says "control or bidi-override
  characters".
- **D6 Sprite keywords (replaces the §3.1 keyword step).** Tokens = `(cls + ' ' + title + ' ' + id).toLowerCase()`
  split on `[^a-z0-9]+`. A keyword marked *exact* must equal a token; the others match as a token prefix. Order:
  knight — `secur defen audit guard warden blueteam`, exact `soc blue` ·
  rogue — `redteam pentest offens attack`, exact `red` ·
  scout — `network netadmin netops firewall rout ranger`, exact `net vpn` ·
  engineer — `devops deploy docker build infra sysadmin linux smith platform kube`, exact `ops ci cd sre k8s` ·
  wizard — `develop code coding program mage`, exact `dev` ·
  scribe — `data sql docs document writ research librar scribe dbadmin`, exact `db doc` ·
  medic — `help support desk medic`.
  Must hold: `Shared credentials` falls through to the hash (no `red` substring match); `Kubernetes notes` →
  engineer via the `kube` prefix (and no longer scout via a `net` substring); `devops` → engineer;
  `CI/CD, Reverse Proxy` → engineer; `Network / Firewall` → scout; `SOC, Audits` → knight; `dev-a` → wizard.
- **D7 Nudge against the documented composer contract.** `getDraft` may return `null` (no composer holds the session
  yet) and `setDraft` may return `false` (not mounted). After `openSession`: up to 10 attempts, 300 ms apart —
  read the draft; a non-empty string (after trim) ends with "existing draft was left untouched"; otherwise call
  `setDraft(sessionId, NUDGE_TEXT)`; `true` → `focus`, done; `false` → next attempt. Exhausted →
  `{ok:false, message:"Session opened, but the composer did not become ready — nothing was placed"}`. Never submit.
- **D8 No re-render under the cursor.** A container is not re-rendered while it holds the focused
  `input`/`textarea`/`select`; the render is deferred to `focusout`. Applies to every periodic render (snapshot, live,
  theme): Live rows with an open review form, the Blocked tab text areas, the Roster tab.
- **D9 Roster editor base.** After a successful Save the saved payload becomes the editor's base and the editor is
  clean. A later snapshot replaces the base only while the editor is clean.
- **D10 Pending timeouts.** Every host round trip has a UI timeout: 75 s for Kanban actions, 20 s for all others.
  On timeout the row shows "no answer from the host (timeout)" and its controls are enabled again. One shared helper
  for pending/result state and one for the two-click armed button replace the three copies.
- **D11 SDK imports.** Read the plugin loader in the Hermes source snapshot and state (file:line) how imports of
  `@hermes/plugin-sdk` are resolved. If a namespace import is supported, import the SDK as a namespace and
  feature-detect `useTheme` (fallback: no host theme → dark unless the setting says otherwise). If it is not
  supported, keep the named import and say so in the handoff. Remove the redundant `[\r\n]` test in `validJumpId`.
- **D12 One consistent version per backend process.** The backend loads the `pixelhq` directory exactly once, as a
  package named `pixelhq_plugin` (`importlib.util.spec_from_file_location` with `submodule_search_locations`), and
  never re-executes modules per request. Inside `pixelhq/` all sibling imports are relative; every top-level
  fallback (`import config`, `import dbutil`, …) and every `sys.path` mutation is removed. Scripts meant to be run
  directly (`render.py`, `blockers.py`, `demo.py`) add the repository root to `sys.path` only under
  `if __name__ == "__main__"` and then import `pixelhq.<module>`. The root `__init__.py` uses the same loader.
  Loading the plugin must not add any of the names `config common profiles scoring dbutil collect live reviews roster
  actions page demo blockers` to `sys.modules` and must not change `sys.path` (test).
- **D13 Stale-backend notice.** `cfg.version` = version from `plugin.yaml` at load time; `cfg.diskVersion` = version
  read from `plugin.yaml` on each snapshot. When they differ the footer shows: "Pixel HQ <disk> is installed but
  <loaded> is still running — restart the Hermes gateway (`hermes gateway restart`) to finish the update."
  `restartHint` in `desktop/plugin.js` says "restart the Hermes gateway (`hermes gateway restart`)" — backend routes
  mount when the gateway starts, not when the Desktop app starts. Docstrings and README wording follow.
- **D14 Manifest.** Drop the empty `provides_middleware` key from `plugin.yaml` (older Hermes versions warn about it;
  absent means empty for the validator). `provides_tools` and `provides_hooks` stay.
- **D15 Commit identity** is fixed by the producer at squash-merge time; builders do not rewrite history.
- **D16 Render re-entrancy (found in producer acceptance, real Chromium, sandboxed frame).** Removing the focused
  element — e.g. by assigning `innerHTML` — dispatches `blur`/`focusout` synchronously while the DOM is being changed.
  With a deferred render (D8) pending for the same container, the `focusout` flush re-rendered that container inside
  the running render; the outer `innerHTML` assignment then threw `NotFoundError: … The node to be removed is no
  longer a child of this node. Perhaps it was moved in a 'blur' event handler?` and the click handler stopped before
  `submitToHost`: Save showed "Saving roster …", nothing reached the host, the trip timed out. Rules:
  (a) the `focusout` flush never renders synchronously — it is scheduled (`setTimeout(…, 0)`), coalesced, and
  re-checks the focus when it runs (still inside the container → stays deferred);
  (b) a direct render of a container cancels the pending deferred render of that container and of every container
  inside it;
  (c) every host round trip posts its message before any re-render (`start` → `submitToHost` → render), so a render
  problem can never swallow a request;
  (d) the DOM harness models the browser: removing a focused element dispatches `focusout` (`relatedTarget` null)
  synchronously, and replacing a container's children during that dispatch makes the outer `innerHTML` setter throw.

## 8. Producer decisions after the second review pass (binding)

- **D17 Loader publication is atomic.** Entry points (`__init__.py`, `dashboard/plugin_api.py`) build the loader module
  completely (`exec_module`) before publishing it and publish with `sys.modules.setdefault(name, candidate)`, using the
  returned object — concurrent first imports end up with one loader instance and therefore one lock. `load()` holds
  that lock for the whole load, marks the package as ready only after every module is imported, and never returns a
  package without the marker (a leftover without marker is discarded and loaded again). Test: two threads, one per
  entry point, 50 fresh runs — both receive the same package object with all modules, exactly one loader module.
- **D18 The triage prompt carries no frame-supplied prose.** The frame sends
  `{pixelhqTriage:{keys, filter:{category, board, stale}}}`. The host accepts `category` ∈
  `all|you|technical|stale|unknown|upstream`, `board` = `all` or `^[A-Za-z0-9_-]{1,64}$`, `stale` boolean, and builds
  the scope sentence itself from fixed strings plus the validated board id (stale threshold from the host-side
  snapshot, integer 1–3650). Anything else → `ok:false`, nothing is called. The orchestrator profile is validated
  against `^[A-Za-z0-9._-]{1,64}$` (no stripping); invalid → `ok:false` "invalid orchestrator profile", nothing called.
- **D19 Symlinks are refused.** `roster.py`: when `roster.json` or `roster.json.bak` exists and is not a regular file
  (symlink included) → `{ok:false, message:"roster.json is not a regular file"}`, nothing is read or written.
  `reviews.py`: the ledger is opened with `O_NOFOLLOW` where the platform has it and checked with `lstat` otherwise; a
  symlinked ledger → `{ok:false, message:"The review ledger is a symlink; set reviews_path to the real file."}`.
- **D20 Action buttons.** `app.js` renders only actions that are keys of its own label table and escapes them;
  `bindActions` returns early while the card's trip is busy (no reliance on the `disabled` attribute).
- **D21 Late results and review idempotency.** A result that arrives after the UI timeout replaces the timeout line
  (all trip types). Every review draft carries a request id `rid` (16–32 lowercase hex characters, created when the
  form opens, reused for every retry of that draft; `crypto.getRandomValues` with a `Math.random` fallback). The
  backend accepts an optional `rid` (`^[0-9a-f]{16,32}$`, else rejected), stores it in the record and, before
  appending, looks for the same `rid` in the last 64 KiB of the ledger (inside the same lock where one exists): found
  → `{ok:true, message:"Review already recorded."}`, nothing written. The agent tool sends no `rid`.
- **D22 The served page belongs to the loaded version.** `page.py` reads `ui/index.html`, `ui/style.css`, `ui/app.js`
  and the fonts once at import; `/page` serves that copy. Files updated later take effect after the gateway restart,
  like the Python modules (D12).
- **D23 Accepted without change.** (a) A module that fails during the eager load makes the whole backend fail to mount —
  fail-fast is intended; Hermes logs "Failed to load plugin pixel-hq API routes". (b) The host posts to the frame with
  target origin `*`: the frame has an opaque origin, so no narrower target exists.
- **D24 Platform safety (done by the producer, commit "Pixel HQ 1.1.2").** No code path signals a process: the
  gateway probe uses a read-only OpenProcess check on Windows and `os.kill(pid, 0)` only on POSIX; POSIX-only modules
  are imported inside `try/except ImportError`. `tests/test_windows_safety.py` enforces both — keep it green and
  extend its source list when you add a module outside `pixelhq/` and `dashboard/`.
