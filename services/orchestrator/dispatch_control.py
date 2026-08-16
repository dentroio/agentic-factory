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


def atomic_write_json(path: Path, payload) -> None:
    """Write JSON via a sibling .tmp file then replace, so a crash cannot truncate the live file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    atomic_write_json(path, payload)
    return payload


def load_attempt_counts(path: Path) -> dict[str, int]:
    """Attempt counts keyed by WO id. Survives dispatch-record deletion (AF-21)."""
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        out: dict[str, int] = {}
        for key, raw in data.items():
            try:
                count = int(raw)
            except (TypeError, ValueError):
                continue
            if count > 0:
                out[str(key)] = count
        return out
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_attempt_counts(path: Path, counts: dict[str, int]) -> None:
    atomic_write_json(path, counts)


def recorded_attempts(counts: dict[str, int], wo_id: str, dispatch_count: int = 0) -> int:
    persisted = int(counts.get(wo_id, 0) or 0)
    try:
        from_dispatch = int(dispatch_count or 0)
    except (TypeError, ValueError):
        from_dispatch = 0
    return max(persisted, from_dispatch)


def record_attempt(counts: dict[str, int], wo_id: str, attempt: int) -> dict[str, int]:
    counts[wo_id] = int(attempt)
    return counts


def clear_attempt(counts: dict[str, int], wo_id: str) -> dict[str, int]:
    counts.pop(wo_id, None)
    return counts


def merge_allowed_for_priority(priority: str | None) -> bool:
    """P2/P3 may be merged by the PM tool. Unknown or P0/P1 must not."""
    return (priority or "").strip().upper() in {"P2", "P3"}


_LIVE_CLAIM_STATUSES = frozenset({"claimed", "in_progress"})


def live_claim(state: dict, wo_id: str) -> dict | None:
    """Return the live dispatch entry if this WO is still a claim.

    After an await, DELETE /api/dispatch or a checkin can remove or finish the
    key. Callers must use this instead of `state[wo_id]` so a vanished claim
    cannot KeyError the rest of poll().
    """
    entry = state.get(wo_id)
    if not isinstance(entry, dict):
        return None
    if entry.get("status") not in _LIVE_CLAIM_STATUSES:
        return None
    return entry
