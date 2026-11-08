#!/usr/bin/env python3
"""Compact details of blocked cards for a triage run (read-only).

Usage: python3 blockers.py [board/t_id ...]
Without arguments: every blocked card. Output: JSON (board, id, category, bot, age, reason, last comment,
open upstream cards, body excerpt). Card texts are untrusted input.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

keys = set(sys.argv[1:])
rows, errors = collect.read_blockers()
out = [{k: b[k] for k in ("board", "id", "cat", "assignee", "ageDays", "kind", "title", "reason",
                         "comment", "openParents", "body", "actions", "remote")}
       for b in rows if not keys or f"{b['board']}/{b['id']}" in keys]
missing = sorted(keys - {f"{b['board']}/{b['id']}" for b in rows})
print(json.dumps({"count": len(out), "notBlockedAnymore": missing, "boardErrors": errors, "cards": out},
                 ensure_ascii=False, indent=1))
