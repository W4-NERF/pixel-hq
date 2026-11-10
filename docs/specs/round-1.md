# Pixel HQ — Round 1 spec: Foundation

Status: binding for cards R1-01 … R1-05 (branch `round-1`, worktree `<worktree>`).
Producer decisions are final; a builder who finds a contradiction blocks with `kanban_block --kind needs_input`
instead of guessing. Everything here must work for a stranger's Hermes installation: 1–N profiles, with or
without Kanban, with or without a review ledger, no Prometheus.

## 0. Non-negotiables (apply to every card)

- Read-only against Hermes data except the two explicit write paths: Kanban actions via `hermes kanban …`
  (already exists) and the reviews JSONL (new, this round). Never write into any Hermes database.
- All untrusted text (card titles, session titles, tool args, review refs) is clipped server-side and escaped
  in the UI with `esc()` before it reaches `innerHTML`.
- No new Python dependencies. Stdlib + what Hermes already ships (PyYAML, FastAPI). Imports of Hermes modules
  only inside `try/except ImportError` with a working fallback, because the code also runs standalone
  (`render.py`, tests, no Hermes on `sys.path`).
- The desktop half (`desktop/plugin.js`) stays inside the plugin SDK (no DOM poking of the app, no `eval`).
- Keep the no-build property: the UI is plain HTML/CSS/JS inlined by `page.py`.
- Public repo: no personal names, hostnames, IPs, board or card titles from any real installation in code,
  tests, fixtures or docs. Fixtures use invented names.

## 1. Scoring model (`pixelhq/scoring.py`) — card R1-01

### 1.1 Sources

| Source | Who has it | Mapping |
|---|---|---|
| **Kanban outcomes** (automatic) | every Kanban user | per `task_events` row joined to `tasks.assignee`: `completed` → pass · `changes_requested` → revise · `gave_up`, `timed_out` → fail · `suspected_hallucinated_references` → fail and counted as *mirage*. `protocol_violation` is NOT an XP event (a `gave_up`/`timed_out` follows it) but feeds the Discipline attribute. |
| **Reviews JSONL** (human via UI, agents via tool, legacy ledger) | opt-in | one JSON object per line, schema §1.2; `verdict` → pass/revise/fail. |

Both sources are recomputed from scratch on every snapshot (no state, idempotent). A Kanban event is
identified by `(board, task_events.id)`; the same event is never counted twice. Boards listed in
`exclude_boards` are skipped. Setting `kanban_xp: false` disables the Kanban source.

### 1.2 Review record

```json
{"ts": "2026-11-09T21:00:00+00:00", "agent": "ops-bot", "verdict": "pass",
 "dims": {"correctness": 5, "completeness": 4, "format": 4, "safety": 5},
 "ref": "nightly backup verification", "parent": "default", "reviewer": "operator", "source": "ui"}
```

- `agent` (required), `verdict` ∈ {pass, revise, fail} (required). Unknown verdicts are skipped.
- `dims` optional; also accepted: `scores` object or the four keys flat on the object (legacy). Values 1–5.
- `parent` optional: profile that spawned a sub-agent/helper → it receives the XP (`summon`). Without `parent`,
  agents matching `^(subagent|delegate_task|claude-code-cli|opencode|codex)` or `cron:` or
  `<orchestrator>-subagent*` are credited to `orchestrator_profile` as summons. `a+b` → `a`.
- `reviewer` optional (who rated), `source` optional ∈ {ui, tool, agent, legacy}.
- **Self-review rule:** if `reviewer` is present and equals the credited bot, the record counts in
  `selfReviews` but gives no XP, no HP and no attribute input.
- Files: `reviews_path` setting (default `<root HERMES_HOME>/plugin-data/pixel-hq/reviews.jsonl`) plus, when
  non-empty, `legacy_ledger_path` (read-only; a user's older ledger). Missing files are fine. Unparseable lines
  are skipped and counted in `warnings`.

### 1.3 Derived numbers (per bot, unchanged formulas)

- Raw contribution per bucket: `raw = Σ pass·xp_pass + revise·xp_revise + fail·xp_fail` (signed, may be negative).
- **Producer decision (floor rule):** the floor applies per bucket `own` and `summon` over BOTH sources:
  `xpOwn = max(0, raw_own_kanban + raw_own_reviews)`, `xpSummon = max(0, raw_summon_kanban + raw_summon_reviews)`,
  `xp = xpOwn + xpSummon`. `xpBySource = {"kanban": raw_kanban, "reviews": raw_reviews}` reports the SIGNED raw sums
  (own + summon) per source without any floor — it is informative and need not add up to `xp`. No additive
  remainder distribution anywhere (demo.py must follow the same rule).
- `level = 1 + floor(sqrt(xp/25))`, `xpPct` = progress inside the level.
- `hp = round(100 · pass / (pass+revise+fail))`, `null` when there is nothing to count.
- Counters: `own = [pass, revise, fail]`, `summ = [pass, revise, fail]`, `bySource = {"kanban": {...}, "reviews": {...}}`.

### 1.4 Attributes (Precision · Stamina · Discipline · Wisdom, 1–5)

1. If review `dims` exist for the bot: averages of correctness / completeness / format / safety
   (`attrsSource: "reviews"`).
2. Else, if the bot has ≥ 3 Kanban completions: derived from Kanban, clamped to 1..5, one decimal
   (`attrsSource: "kanban"`):
   - Precision = 5 − 4 · mirage / max(1, completed)
   - Stamina = 1 + 4 · completed / max(1, completed + gave_up + timed_out)
   - Discipline = 1 + 4 · (1 − protocol_violations / max(1, runs)), runs = number of `claimed` events
   - Wisdom = 1 + 4 · (1 − changes_requested / max(1, completed + changes_requested))
3. Else `attrs = [null, null, null, null]`, `attrsSource: null`.

### 1.5 Events for the log

Kanban events as today (`completed`, `blocked`, `gave_up`, `timed_out`, `protocol_violation`,
`suspected_hallucinated_references`, `created`) plus `changes_requested` ("changes requested"). Review records
become `qc-pass` / `qc-revise` / `qc-fail` events with `summon` and `source` flags. Newest 40 overall.

### 1.6 Interface

`scoring.compute(bots: list[str], kanban: KanbanIndex, reviews: list[dict], cfg) -> dict[bot_id, Score]`
where `collect.py` builds the Kanban index once (one pass over the boards) and passes the parsed review
records. `collect.py` keeps its output shape (keys used by `ui/app.js`) and adds the new keys above.

## 2. Profiles, roster, schema tolerance (`pixelhq/profiles.py`, `collect.py`, `live.py`) — card R1-02

### 2.1 No more `hermes profile list`

- Profiles = the root profile `default` (dir = root HERMES_HOME) + every directory under
  `<root>/profiles/` that contains `config.yaml` or `profile.yaml`; skip names starting with `_` or `.`.
  Root HERMES_HOME: `$HERMES_HOME` unwrapped (`…/profiles/<x>` → root) else `~/.hermes`.
- `model`: `config.yaml` → `model.default` (+ `model.provider`). Parse with PyYAML when importable, otherwise a
  minimal fallback that finds the `model:` block and its `default:`/`provider:` lines. Missing → `"?"`.
- `gateway`: `gateway.pid` in the profile dir → `"running"` if the pid is alive (`os.kill(pid, 0)`), else
  `"stopped"`; no file → `None`. **File format (verified on a live installation):** either a bare integer OR a JSON
  object `{"pid": 1273, "kind": "hermes-gateway", "argv": [...]}` — accept both; anything else → `None` plus a
  warning (never an exception).
- `description` from `profile.yaml` (`description:`), used as `cls` for bots the roster does not describe.
- Target: full snapshot < 500 ms on a 20-profile installation (no subprocess).

### 2.2 Roster rules

- Bots shown = roster entries whose `id` is an existing profile, plus roster entries with `remote: true`
  (status from Kanban only), plus every existing profile missing from the roster (auto entry: `title`
  "Recruit", `cls` = profile description or "Hermes profile", `color` = stable hash colour, `auto: true`).
  Roster entries for non-existent, non-remote profiles are dropped (count them in `warnings`).
- No `roster.json` → generated roster: one room `{"id":"hq","label":"HEADQUARTERS","main":true,
  "zones":[{"id":"command","label":"COMMAND"},{"id":"crew","label":"CREW"}]}`; `orchestrator_profile` → `command`
  (with `leader: true`), everyone else → `crew`. `roster.example.json` is documentation only and is never
  loaded automatically. `cfg.rosterSource ∈ {"file","generated"}`.
- Remote bots have no local `state.db`; everything else about them comes from Kanban.

### 2.3 Schema tolerance

- Helper `columns(con, table) -> set[str]` via `PRAGMA table_info`. Every SELECT on `sessions`, `tasks`,
  `task_events`, `task_comments`, `task_links` is built from a list of wanted columns; a missing column becomes
  `NULL AS <col>`. A missing *table* skips that source for that DB.
- Any per-profile or per-board failure lands in `warnings` (list of short strings, max 120 chars each) instead
  of silently dropping the bot/board. `collect()` returns `warnings`; the UI shows them in the footer.

## 3. Settings via Hermes (`plugin.yaml` `config_schema`, `pixelhq/config.py`) — card R1-03

`config_schema` keys (type, default, description): `locale` (str, "en-GB"), `timezone` (str, "UTC"),
`theme_label` (str, "PIXEL HQ"), `operator_name` (str, "operator"), `orchestrator_profile` (str, "default"),
`reviews_path` (str, ""), `legacy_ledger_path` (str, ""), `kanban_xp` (bool, true), `xp_pass` (int, 10),
`xp_revise` (int, 3), `xp_fail` (int, −5), `stale_days` (int, 14), `exclude_boards` (list, []),
`needs_input_keywords` (list, current defaults), `prometheus_url` (str, ""), `metrics_prefix` (str, "vllm"),
`model_endpoint` (str, ""), `node_aliases` (dict, {}).

Precedence in `config.load()`: defaults ← `plugin-data/pixel-hq/config.json` (kept for headless setups) ←
Hermes settings `plugins.entries.pixel-hq.settings` read through `hermes_cli.config.load_config_readonly()`
inside `try/except ImportError` (standalone: skipped). Flat keys replace the old nested `gpu` and `xp`
blocks; `config.json` may still use the old nested form (map it). `config.public()` reports `settingsSource`
∈ {"hermes","file","defaults"}.

## 4. UI split + review controls (`pixelhq/ui/`, `page.py`, `plugin_api.py`, `desktop/plugin.js`) — card R1-04

- Split `ui.html` into `pixelhq/ui/index.html` (markup), `pixelhq/ui/style.css`, `pixelhq/ui/app.js`;
  `page.py` inlines them (fonts as today). Rendered output must be functionally identical.
- Review control ("Rate") on every session row in **Live** (not on sub-agent rows) and on the **character
  card**: three buttons pass / revise / fail; clicking opens an inline form (4 selects 1–5, default 4; `ref`
  text prefilled with the session/quest title clipped to 80) with Confirm/Cancel. Confirm posts
  `{pixelhqReview: {agent, verdict, dims, ref, sessionId}}` to the host; the frame shows the result line like
  Kanban actions do. Standalone page: control visible only with `?actions=1`.
- Host: `ctx.rest('/review', {method:'POST', body})` → backend `pixelhq/reviews.py`: validate `agent` (must be
  a known bot id), `verdict`, `dims` (ints 1–5 or absent), `ref` ≤ 200 chars; set `ts` (ISO, UTC),
  `reviewer` = `operator_name`, `source` = "ui"; append to `reviews_path` (create dir/file); return
  `{ok, message}`; snapshot cache invalidated.
- Attribute block shows a muted "(from Kanban)" or "(from reviews)" label per `attrsSource`; the footer shows
  XP sources and `warnings`.
- `desktop/plugin.js`: forward `pixelhqReview` like `pixelhqAction`.

## 5. Agent tool `pixelhq_review` (`__init__.py`, `plugin.yaml`) — card R1-05

- `register(ctx)` registers one tool (`ctx.register_tool(name="pixelhq_review", toolset="pixelhq",
  schema=…, handler=…, description=…)`; handler signature `handler(args: dict, **kwargs) -> str` returning a
  JSON string). Schema parameters: `agent` (string, required), `verdict` (enum pass|revise|fail, required),
  `correctness`, `completeness`, `format`, `safety` (integer 1–5, optional), `ref` (string ≤ 200, optional),
  `parent` (string, optional — the profile that spawned the rated helper).
- The handler appends a review record with `reviewer` = calling profile (`$HERMES_PROFILE`, else the basename
  of `$HERMES_HOME` when it lies under `profiles/`, else "default") and `source` = "tool". It never raises:
  errors come back as `{"error": "…"}`.
- `plugin.yaml`: `capabilities.provides_tools: [pixelhq_review]` (the catalog validator checks that declared
  tools match registrations). `__init__.py` must import without Hermes present (tests) — keep the registry
  interaction inside `register()`.
- API reference for the builder: a Hermes source snapshot lies in `<hermes-agent source checkout>/`
  (`hermes_cli/plugins.py` → `register_tool`, `plugins/google_meet/` as a small example).

## 6. Tests (every card adds its own; R1-05 consolidates)

- `tests/` with pytest, stdlib fixtures: `tests/fixtures.py` builds a temporary HERMES_HOME with 3 profiles
  (`default`, `ops-bot`, `remote-bot` only in roster), two Kanban boards (`platform`, `website`) as real
  SQLite files with the minimal schema (`tasks`, `task_events`, `task_comments`, `task_links`), and a
  `state.db` per local profile (`sessions`, `messages`). Column names as in current Hermes; one board
  deliberately lacks `block_kind`/`last_heartbeat_at` to test tolerance.
- Must-have tests: Kanban → XP mapping and dedupe; review attribution incl. `parent`, helper names, `a+b`;
  self-review exclusion; attributes from reviews vs from Kanban vs null; level/HP formulas; blocked-card
  categories; roster rules (dropped ghost, auto recruit, generated roster); profile parsing (yaml + fallback,
  gateway pid bare/JSON alive, dead and invalid); config precedence (defaults < file < hermes settings via monkeypatched loader);
  `reviews.append` validation (bad agent/verdict/dims/ref); `actions.run` guards with `subprocess.run`
  monkeypatched (never calls the real CLI), exact answer/retry/comment/archive argv and pre-archive workspace backup;
  tool registration/schema, trusted calling-profile metadata, helper parents and JSON errors;
  `demo.snapshot()` and `page_html()` smoke.
- Final consolidated suite: **297 tests**. Socket access and real CLI processes are denied by the shared fixtures;
  subprocess probes use only offline Python/Node, and REST tests use in-process ASGI transport.
- Gates (run inside the sandbox, see the card's environment block):
  `pytest -q` all green, `python3 tools/jscheck.py` (strips `import`/`export` lines and runs `node --check`
  on `pixelhq/ui/app.js` and `desktop/plugin.js`) exits 0, `python3 pixelhq/render.py --demo` writes
  `dist/pixel-hq.html` containing `"demo": true`.

## 7. Out of scope for Round 1

Open-session / talk-to-bot buttons, nudge, class-based sprites, roster editor, light theme, docs rewrite,
video — Round 2/3. Do not start them.

## 8. Producer decisions after review R1-R (binding, 2026-11-10)

- **D1 Self-review rule (clarifies §1.2):** a record is a self-review only when `reviewer` equals the RATED `agent`
  (before summon attribution). An orchestrator rating its own helper (`agent` = helper, credited to the orchestrator
  via `parent`/helper rule) is NOT a self-review and gives summon XP — that is the intended use of the tool.
  Self-reviews still appear in the event log (flag `selfReview`) but do not update `lastQc`.
- **D2 Config robustness (§3):** every settings value is coerced to the schema type (`int`/`bool`/`list`/`dict`/`str`);
  a value that cannot be coerced falls back to the default and appends `"<key>: expected <type>"` to `warnings`
  (and sets `config_error` to the first such message). `exclude_boards` given as a string → `[string]`. Snapshot
  must never 500 because of a settings value.
- **D3 Roster robustness (§2.2):** malformed `roster.json` (invalid JSON, not an object, bot without `id`, non-string
  `id`) → warning + fall back to the GENERATED roster (bad entries are skipped individually when the file is otherwise
  usable). Nothing may fail at import time: `collect.py`/`live.py` load config/roster lazily per request.
- **D4 Identifiers:** `agent` and `parent` must match `^[A-Za-z0-9._+-]{1,64}$` on every write path (UI and tool);
  otherwise the record is rejected with a clear message.
- **D5 Paths:** a relative `reviews_path`/`legacy_ledger_path` resolves against `<root>/plugin-data/pixel-hq/`;
  absolute paths are honoured as a deliberate operator choice (documented in README). The default never leaves
  `plugin-data`.
- **D6 Model field (§2.1):** `model:` may be a scalar string (`model: gpt-x`) → that is the model, provider unknown.
- **D7 Escaping:** numeric-looking values from SQLite (`pid`, counts) are rendered through `esc()` or `Number()`.
- **D8 Standalone page:** when `window.parent === window`, review/action submits resolve immediately with the
  result line "standalone page: no host, nothing was sent" instead of pending forever.
- **D9 Spec edits by builders:** the §6 test-count edit in commit 59f83fe is confirmed.
- **D10 Repository hygiene:** `docs/cards/`, `tools/write_cards_r1.py`, `tools/create_cards_r1.py` and the absolute
  paths in this spec are orchestration scaffolding; they are removed/sanitised by the producer at squash-merge time and
  never reach `main`/GitHub. Builders do not touch them.
