# Round 5 — Several hosts in one Pixel HQ (spec, binding)

Base: `round-5` at the 1.3.1 tree (`650b257`). Target version **1.4.0**. Rounds 1–4 stay in force: the sandbox
contract (round-2 §0.1), render rules (D8/D16), "a request body never chooses a path", "no autonomous prompts", and the
round-4 rule that the plugin never writes another profile's files itself.

## 0. What the operator asked for (decisions)

1. One overview over bots on **several hosts**: an operator runs Hermes bots on more than one machine (e.g. a
   workstation and a server). Pixel HQ shows the other hosts' bots, their activity and their blocked Kanban cards next to
   the local ones. **Read-only** in this round: no Kanban actions, no triage, no ratings and no SOUL editing for bots of
   another host — the card says where to act instead.
2. **Transport is SSH with a fixed command**, opt-in. The remote host restricts the key with a forced command that runs
   the Pixel HQ exporter (§1). A source can also be a JSON file the operator syncs by other means.
3. **Pull only while the page is used**: remote data is fetched as part of the normal snapshot collection (existing TTL
   cache), never by a background loop or timer of the plugin.
4. **Remote data is untrusted input**: schema-validated, size-limited, clipped, escaped, and never used to build a prompt.
5. The exporter is **conservative by default**: no tool-call arguments, no reviews ledger content, no SOUL, no config.

## 1. The exporter (card R5-01) — runs on the remote host

- `python3 -m pixelhq.export` (also `python3 pixelhq/export.py`) prints **one JSON document** to stdout and exits 0;
  errors go to stderr with exit 1. It writes nothing (no plugin-data, no cache files, no logs).
- Inputs: `--home PATH` (repeatable; default: the usual root Hermes home), `--kanban-db PATH` (repeatable; extra board
  databases, e.g. a shared board outside the homes), `--label NAME` (source label shown to the reader; default the short
  host name), `--include-tool-args` (off by default). Profiles are read from every home; a profile name that appears in
  two homes is kept once (first home) and listed in `warnings`.
- It reuses the collector's read paths (profiles, `state.db`, Kanban boards, XP scoring with the settings found in each
  home) in read-only mode.
- Document (`schema: "pixelhq-remote/1"`):
  ```
  { "schema", "source", "generated" (ISO-8601 UTC), "pixelhq" (version),
    "bots": [ { "id", "model", "status": running|idle|blocked|unknown, "lastActive" (unix s or null),
               "currentStep" (≤ 160 chars, optional), "quest" (session title ≤ 80, optional),
               "lastTool" (tool name only unless --include-tool-args; ≤ 160), "xp", "level", "hp" (0–100 or null),
               "cls" (≤ 40, optional) } ],
    "blockers": [ { "board", "id" (t_<hex>), "title" (≤ 120), "category", "assignee", "ageDays", "reason" (≤ 160) } ],
    "boards": [ { "slug", "ready", "running", "blocked", "todo", "done24h" } ],
    "warnings": [ "…" (≤ 160 each, ≤ 20) ] }
  ```
  Limits: ≤ 200 bots, ≤ 500 blockers, ≤ 64 boards, whole document ≤ 1 MiB (truncate lists with a warning, never fail).

## 2. Remote sources in the collector (card R5-02) — runs on the operator's host

- New settings in `plugin.yaml` `config_schema` (flat):
  - `remote_sources` (list, default `[]`): each entry `ssh:<dest>` or `file:<name>`. `<dest>` is an SSH destination or
    alias (`[user@]host`), matched against `^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$` (no leading `-`, no spaces, no `:`
    after the scheme). `<name>` matches `^[a-z0-9][a-z0-9._-]{0,31}$` and is read from
    `<root>/plugin-data/pixel-hq/remote/<name>.json` (regular file, no symlink, ≤ 1 MiB).
  - `remote_timeout_s` (int, default 8, clamped 2–30), `remote_stale_after_s` (int, default 300).
- SSH call: `subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-T", dest, "pixelhq-export"],
  shell=False, timeout=remote_timeout_s, capture_output=True)`. Nothing else is ever executed. The remote side's forced
  command decides what runs; the trailing word only documents intent. stdout > 1 MiB → refused.
- Fetches run in parallel (thread pool), inside the existing snapshot collection and its TTL cache; the snapshot never
  waits longer than `remote_timeout_s` + 1 s for all sources together.
- Validation: `schema` must equal `pixelhq-remote/1`; every field type-checked, clipped, enums enforced, unknown fields
  dropped; ids must match the existing bot-id rule; card ids `t_<hex>`. A failed source keeps its **last good document**
  (in memory only) with its age; the footer shows per source: `ok · 35 s` / `stale · 12 min` / `unreachable (timeout)` /
  `invalid (reason ≤ 80)`.
- Source label = the document's `source` when it matches the name rule, else the configured name. Remote bots are keyed
  **`<source>/<id>`** everywhere (snapshot, roster matching, UI), so a remote `default` never collides with a local one.
- Roster: an entry with `remote: true` may carry `source` (new optional field, same name rule). Match order: `source/id`
  exact; else an entry with `remote: true`, no `source`, and an id that exists in exactly one source. Remote bots without
  a roster entry are placed by the existing recruit rule (round-3 R3-D1) and flagged `auto`, as local recruits are.

## 3. UI (card R5-03)

- Remote bots render like local ones plus a **host badge** (source label) on desk, character card, leaderboard row and
  live row. Their data shows its age ("as of 40 s ago") on the character card and in the live row.
- Character card of a remote bot: no Talk / Open / Ask for status / Rate / Config SOUL editing; one line: "Runs on
  <source> — actions are available on that host." The read-only facts that exist in the document are shown.
- Blocked tab: remote cards in their own section per source, read-only (no action buttons, no triage selection), with
  the same title/reason escaping.
- Live tab: remote bots with `currentStep` / `lastTool` / `lastActive` from the document; never "running" when the
  document is stale (`stale` badge instead).
- Footer: one line per configured source (§2). Office stats (department numbers) include remote members; "blocked"
  counts remote blockers of that member.
- Standalone demo: two synthetic sources (one ok, one stale) so the screenshots show the feature.

## 4. Documentation and version (card R5-04)

- README: new section "Several hosts" with the operator recipe: (1) install Pixel HQ (or only its repository) on the
  remote host; (2) a dedicated SSH key with `command="python3 /path/to/pixelhq/export.py --label <name>",no-pty,
  no-port-forwarding,no-agent-forwarding,no-X11-forwarding,restrict` as key options on the remote account; (3) an SSH config
  alias on the local host; (4) `remote_sources: ["ssh:<alias>"]`. Mention multi-home servers (`--home` per home,
  `--kanban-db` for shared boards) and the read permissions the export user needs.
- Disclosure: SSH network access only to configured sources, only with the fixed command, only while snapshots are
  collected; remote data is read-only and untrusted; the exporter writes nothing and omits tool arguments by default.
- CHANGELOG `[1.4.0]`; `plugin.yaml` version 1.4.0; settings table regenerated.

## 5. Tests and gates (every card)

- Exporter: fixture with two homes and one extra board DB; duplicate profile names; redaction (no tool args unless the
  flag); limits/truncation; writes nothing (snapshot of the fixture tree before/after); schema round trip.
- Collector: `subprocess.run` monkeypatched — argument list exact (no shell), dest validation (leading `-`, spaces, `;`,
  `$(`, newline), timeout, non-zero exit, oversize, invalid JSON, wrong schema, hostile strings; parallel fetch bounded by
  the timeout; last-good + stale; file sources (symlink and size refusals); `source/id` keys and roster matching rules;
  no remote data in triage prompts (assert the prompt builder never sees remote blockers).
- UI (DOM harness): host badges, read-only character card, remote blocked section without buttons, stale handling in
  live, footer lines, escaping of hostile remote strings, standalone demo with two sources.
- Gates as in round 4 (pytest, jscheck, jslint, funclen, contrast, render --demo, ruff). No test, probe or harness may
  call a real host, SSH or gateway.

## 6. Out of scope

Actions on remote cards, distributing tasks to other hosts, remote SOUL editing, ratings for remote bots, any background
polling, push transports, credentials handling inside the plugin.

## 7. Producer decisions after review R5-R (binding)

- **R5-D1 — a source-bound bot stays source-bound.** Every roster entry that represents a bot of a source carries
  `source`; the editor, Save and the collector keep it. A local profile is never marked remote because a source has a bot
  with the same id. `cfg.remoteBots` (the triage prompt's "not dispatchable" list) contains only operator-written roster
  entries with `remote: true` and **no** `source`; ids that come from a source never reach any prompt (§0.4).
- **R5-D2 — identity survives a dirty layout.** A draft entry with `source` renders with its `source/id` key, its host
  badge and the read-only character card even when the next snapshot no longer contains that bot (shown as
  `unknown`). Desk `data-id`, selection and every host message use the full key; a remote key never resolves to a local
  profile.
- **R5-D3 — data age is the document's age.** Age and staleness come from the document's `generated` time, for SSH and
  file sources alike, never from the receive time. A `generated` value more than 120 s in the future is invalid; one
  older than `remote_stale_after_s` makes the source `stale` and its bots never `running`.
- **R5-D4 — one bot, one live list.** A remote bot appears in at most one live list at any time. When a snapshot marks
  it stale, it leaves the active list immediately, also while a local input elsewhere has focus (the focus guard defers
  only the container that holds the focused element).
- **R5-D5 — the exporter creates no files.** For every database it reads: if neither `-wal` nor `-shm` exists, open it
  with `mode=ro&immutable=1`; otherwise `mode=ro`. No other change to the collector's local reads.
- **R5-D6 — the age reference is the newest server time.** "as of N ago" is measured against the newer of the snapshot's
  and the live data's `generated`, never the older one.
- **R5-D7 — supported entry point is the script with `-B`.** The forced command in the README is
  `python3 -B /path/to/pixelhq/export.py --label <name>`; `python3 -B -m pixelhq.export` is documented as equivalent.
  Without `-B`, `-m` imports the package before the exporter can stop bytecode writing — accepted and documented.
- **R5-D8 — the SSH child gets an explicit environment.** Only `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`,
  `LC_CTYPE` and `SSH_AUTH_SOCK` (each only if set) are passed; nothing else from the backend's environment.
- **R5-D9 — a home can be limited to named profiles.** `--home PATH=NAME[,NAME...]` reads only the listed profiles
  from that home (split on the **last** `=`; names follow the profile-name rule; an unknown name is a warning, not an
  error). Plain `--home PATH` keeps reading every profile. Reason: on a server with one Unix user per bot, every home
  also has an unused root `default` profile; without a filter the exporter reports duplicates on every call and the first
  home decides which `default` is shown. The README's multi-home example uses the filter.
- **R5-D10 — the open rule follows the database's journal mode (replaces the open rule of R5-D5).** The exporter
  reads bytes 18–19 of the database header (`1` = rollback journal, `2` = WAL) without SQLite:
  rollback journal → `mode=ro` (normal shared locks, so a concurrent writer is never read half-way; SQLite creates no
  file for a read-only reader); WAL with both `-wal` and `-shm` present → `mode=ro`; WAL with neither present →
  `mode=ro&immutable=1` (no process has the database open); WAL with `-wal` but no `-shm` (left over after a crash or a
  copy) → `mode=ro&immutable=1` **and** the warning `<what>: write-ahead log without its -shm file was not read; data
  may be older` (`<what>` = `profile <name>` or `board <slug>`). Unreadable header → the same warning text with
  `header unreadable` and the item is skipped. The exporter never creates a file — a file created by a privileged
  exporter in a bot's home could lock that bot out of its own database; slightly older data is the lesser harm.
- **R5-D11 — `generated` must not lie before 1970-01-01T00:00:00Z** (schema error), so the `lastActive` clamp never
  produces a value outside the schema range and validation stays idempotent.
- Ruff (`ruff check .`, version pinned in `requirements-dev.txt`) is part of the gates; the producer runs it.
