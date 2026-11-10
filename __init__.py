"""Pixel HQ agent tools; desktop UI and backend are registered separately."""
from __future__ import annotations

import json
import os
from pathlib import Path


REVIEW_DESCRIPTION = "Record a quality review for a bot or helper in the Pixel HQ review ledger."
REVIEW_SCHEMA = {
    "name": "pixelhq_review",
    "description": REVIEW_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "minLength": 1, "maxLength": 64,
                      "pattern": r"^[A-Za-z0-9._+-]{1,64}$", "description": "Bot or helper being reviewed."},
            "verdict": {"type": "string", "enum": ["pass", "revise", "fail"]},
            **{key: {"type": "integer", "minimum": 1, "maximum": 5}
               for key in ("correctness", "completeness", "format", "safety")},
            "ref": {"type": "string", "maxLength": 200, "description": "Short review reference."},
            "parent": {"type": "string", "minLength": 1, "maxLength": 64,
                       "pattern": r"^[A-Za-z0-9._+-]{1,64}$", "description": "Profile that spawned the rated helper."},
        },
        "required": ["agent", "verdict"],
        "additionalProperties": False,
    },
}


def _handle_review(args: dict, **kwargs) -> str:
    try:
        if __package__:
            from .pixelhq import config, reviews
        else:
            from pixelhq import config, reviews
        home = Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
        reviewer = os.environ.get("HERMES_PROFILE") or (home.name if home.parent.name == "profiles" else "default")
        result = reviews.append_tool(args, config.load(), reviewer)
        return json.dumps(result if result["ok"] else {"error": result["message"]})
    except Exception:
        # Import/config/IO diagnostics may contain private paths or settings.
        return json.dumps({"error": "Could not save the review; check the plugin settings and review path."})


def register(ctx) -> None:
    """Register tools only when called by the plugin loader."""
    ctx.register_tool(name="pixelhq_review", toolset="pixelhq", schema=REVIEW_SCHEMA,
                      handler=_handle_review, description=REVIEW_DESCRIPTION)
