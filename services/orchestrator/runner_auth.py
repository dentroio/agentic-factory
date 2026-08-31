"""Agent runner token authentication, registry, and zero-trust identity verification (WO-1090)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets


def hash_runner_token(token: str) -> str:
    """Return SHA-256 hash of a runner token."""
    return hashlib.sha256(token.strip().encode()).hexdigest()


def issue_runner_token() -> str:
    """Generate a new cryptographically random runner token with rn_ prefix."""
    return f"rn_{secrets.token_urlsafe(32)}"


def load_runners(path: Path | str) -> list[dict]:
    """Load registered runners from JSON storage."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[runner_auth] load runners failed: {exc}")
        return []


def save_runners(path: Path | str, runners: list[dict]) -> None:
    """Persist registered runners to JSON storage."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(runners, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[runner_auth] save runners failed: {exc}")


def find_runner_by_token(runners: list[dict], token: str) -> dict | None:
    """Find matching runner entry for a bearer token, or None."""
    if not token or not token.startswith("rn_"):
        return None
    token_hash = hash_runner_token(token)
    for r in runners:
        if secrets.compare_digest(r.get("token_hash", ""), token_hash):
            return r
    return None


def register_runner(
    path: Path | str,
    runners: list[dict],
    agent_name: str,
    backend: str = "claude",
    workstation: str = "",
) -> dict:
    """Register a new runner and persist to disk. Returns new entry with plaintext token."""
    agent_name = agent_name.strip()
    if not agent_name:
        raise ValueError("agent_name cannot be empty")

    raw_token = issue_runner_token()
    token_hash = hash_runner_token(raw_token)
    runner_id = f"run_{secrets.token_hex(4)}"

    entry = {
        "id": runner_id,
        "agent_name": agent_name,
        "backend": backend or "claude",
        "workstation": workstation or "",
        "token_hash": token_hash,
        "token_prefix": f"{raw_token[:7]}...{raw_token[-4:]}",
        "status": "active",
        "created_at": None,
        "last_seen": None,
        "revoked_at": None,
    }
    runners.append(entry)
    save_runners(path, runners)
    return {
        "id": runner_id,
        "agent_name": agent_name,
        "backend": entry["backend"],
        "workstation": entry["workstation"],
        "token": raw_token,
        "token_prefix": entry["token_prefix"],
    }


def revoke_runner(path: Path | str, runners: list[dict], runner_id: str) -> dict | None:
    """Revoke a runner token by ID. Returns updated entry or None if not found."""
    target = None
    for r in runners:
        if r.get("id") == runner_id:
            r["status"] = "revoked"
            target = r
            break
    if target is not None:
        save_runners(path, runners)
    return target


def check_agent_identity(runner: dict | None, agent_name: str) -> tuple[bool, str]:
    """Verify that agent_name matches registered runner identity if a runner token was used.
    
    Returns (True, "") if allowed, or (False, reason) if identity mismatch.
    """
    if not runner or not runner.get("agent_name"):
        return True, ""
    expected = runner["agent_name"].strip().lower()
    actual = (agent_name or "").strip().lower()
    if actual != expected:
        return False, f"Identity mismatch: runner token is issued for '{runner['agent_name']}', but request specified '{agent_name}'"
    return True, ""
