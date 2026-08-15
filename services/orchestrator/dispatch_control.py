"""Dispatch pause and claim-lease helpers.

AF-18: a claim is a lease. The orchestrator issues a fencing token on claim
and every subsequent mutating call for that WO must present it. A mismatch
is 409 — the caller lost the claim and must stop, not retry as if it still
owns the worktree.

Factory closeout: a persisted pause flag makes /api/next and /api/claim
refuse work so the factory cannot start development until an operator
explicitly unpauses.
"""
from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path


def issue_claim_token() -> str:
    return secrets.token_urlsafe(32)


def lease_matches(stored: str | None, provided: str | None) -> bool:
    if not stored or not provided:
        return False
    try:
        return hmac.compare_digest(stored, provided)
    except (TypeError, ValueError):
        return False


def load_pause(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return {
                "paused": bool(data.get("paused")),
                "reason": str(data.get("reason") or ""),
            }
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"paused": False, "reason": ""}


def save_pause(path: Path, paused: bool, reason: str = "") -> dict:
    payload = {"paused": bool(paused), "reason": str(reason or "")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)
    return payload


def merge_allowed_for_priority(priority: str | None) -> bool:
    """P2/P3 may be merged by the PM tool. Unknown or P0/P1 must not."""
    return (priority or "").strip().upper() in {"P2", "P3"}
