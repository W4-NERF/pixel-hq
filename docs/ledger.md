# Review ledger format

Pixel HQ reads XP, HP and attributes from JSON-lines review ledgers, one object per line:

- **Review ledger** (`reviews_path`, default `~/.hermes/plugin-data/pixel-hq/reviews.jsonl` under the root
  Hermes home). Pixel HQ appends to it when you confirm a rating in the UI and when an agent calls the
  `pixelhq_review` tool; the file is created when missing and must not be a symbolic link.
- **Legacy ledger** (`legacy_ledger_path`, optional). An older quality ledger that is only read, never written.

Kanban outcomes are scored as well (unless `kanban_xp` is `false`); see
[How XP is earned](../README.md#how-xp-is-earned) for the scoring rules.

```json
{"ts": "2026-11-04T00:30:00+01:00", "agent": "sysadmin", "verdict": "pass",
 "dims": {"correctness": 5, "completeness": 4, "format": 4, "safety": 5},
 "ref": "docker-upgrade-proxy", "parent": "default", "reviewer": "operator", "source": "tool"}
```

| Field | Meaning |
|---|---|
| `agent` | Required. Profile name of the bot, or a helper id (`subagent`, `delegate_task`, `claude-code-cli`, `opencode`, `codex`, `cron:…`). |
| `verdict` | Required. `pass` / `revise` / `fail` — drives XP and HP. Other values are skipped. |
| `dims` | Optional 1–5 scores for `correctness`, `completeness`, `format` and `safety`; legacy `scores` or flat top-level keys are accepted when reading. |
| `parent` | Profile that spawned a helper; it receives the summon XP. Without it, helpers are credited to `orchestrator_profile`. |
| `ts` | ISO 8601 time, used for the event log; written in UTC by Pixel HQ. |
| `ref` | Short topic or task reference shown in the event log (at most 200 characters when written by Pixel HQ). |
| `reviewer` | Who reviewed: `operator_name` for UI reviews, the calling profile for tool reviews. A review whose `reviewer` equals the rated `agent` is a self-review and earns no XP. |
| `source` | `ui` or `tool` when written by Pixel HQ; records without it count as `legacy`. |
| `rid` | Request id of a UI review draft; a retry with the same id is not appended twice. |

Lines that do not parse are skipped with a warning in the footer. Pixel HQ never rewrites or truncates
existing lines; it only appends.
