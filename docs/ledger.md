# Quality ledger format

Pixel HQ reads XP, HP and attributes from a JSON-lines file (default `~/.hermes/quality/ledger.jsonl`,
configurable via `ledger_path`). Append one object per reviewed delegated answer:

```json
{"ts": "2026-11-04T00:30:00+01:00", "agent": "sysadmin", "model": "local/llm-34b",
 "task_type": "change", "dims": {"correctness": 5, "completeness": 4, "format": 4, "safety": 5},
 "verdict": "pass", "ref": "docker-upgrade-proxy", "parent": "default"}
```

| Field | Meaning |
|---|---|
| `agent` | profile name of the bot (or `subagent`, `delegate_task`, `claude-code-cli`, `opencode`, `cron:…` for helpers) |
| `verdict` | `pass` / `revise` / `fail` — drives XP and HP |
| `dims` | 1–5 scores; `scores` or flat top-level keys are accepted too |
| `parent` | profile that spawned a sub-agent/helper; it receives the XP. Without it, helpers are credited to `orchestrator_profile` |
| `ts` | ISO-8601; used for the event log |
| `ref` | short topic / task id shown in the event log |

Lines that do not parse are skipped. The file is never written by Pixel HQ.
