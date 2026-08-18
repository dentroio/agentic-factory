"""Thin async wrapper around the orchestrator REST API."""
from datetime import UTC, datetime

import httpx

from config import ORCHESTRATOR_URL, AGENT_NAME, HOSTNAME, API_SECRET

_AUTH = {"Authorization": f"Bearer {API_SECRET}"} if API_SECRET else {}
_claim_tokens: dict[str, str] = {}


class ClaimLost(Exception):
    """The orchestrator rejected our claim lease (409). Stop touching this WO."""


def _lease_headers(wo_id: str = "") -> dict:
    headers = dict(_AUTH)
    token = _claim_tokens.get(wo_id, "")
    if token:
        headers["X-Factory-Claim-Token"] = token
    return headers


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def get_next(domain: str = "") -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            params = {"domain": domain} if domain else {}
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/next", headers=_AUTH, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if data.get("wo") else None
    except Exception as e:
        print(f"[runner] get_next failed: {e}")
        return None


async def claim(wo_id: str, slug: str = "", backend: str = "") -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/claim", headers=_AUTH, json={
                "wo": wo_id,
                "agent": AGENT_NAME,
                "backend": backend,
                "workstation": HOSTNAME,
                "slug": slug,
            })
            if resp.status_code == 423:
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    detail = ""
                print(f"[runner] {wo_id} claim refused — {detail or 'locked (423)'}")
                return False
            if resp.status_code == 429:
                # Distinct from a routine 409 (someone else has it) — this WO is
                # permanently blocked until a human resets it. Say so plainly instead
                # of letting it look like ordinary contention on every poll forever.
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    detail = ""
                print(f"[runner] {wo_id} claim blocked — {detail or 'exceeded max retry attempts, needs manual reset'}")
            if resp.status_code == 200:
                try:
                    token = resp.json().get("claim_token") or ""
                except Exception:
                    token = ""
                if token:
                    _claim_tokens[wo_id] = token
                return True
            return False
    except Exception as e:
        print(f"[runner] claim {wo_id} failed: {e}")
        return False


async def checkin(wo_id: str, step: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/api/checkin",
                headers=_lease_headers(wo_id),
                params={"wo": wo_id, "agent": AGENT_NAME, "step": step},
            )
            if resp.status_code == 409:
                _claim_tokens.pop(wo_id, None)
                raise ClaimLost(wo_id)
    except ClaimLost:
        raise
    except Exception:
        pass  # non-blocking for transient errors


async def request_validate(wo_id: str, verify_url: str = "", steps: list[str] | None = None,
                           ci_passed: bool = True, security_passed: bool = True,
                           thread_summary: str = "", pr_url: str = "",
                           pr_number: int | None = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/validate", headers=_lease_headers(wo_id), json={
                "wo": wo_id,
                "agent": AGENT_NAME,
                "workstation": HOSTNAME,
                "verify_url": verify_url,
                "steps": steps or [],
                "ci_passed": ci_passed,
                "security_passed": security_passed,
                "thread_summary": thread_summary,
                "pr_url": pr_url,
                "pr_number": pr_number,
            })
            if resp.status_code == 409:
                _claim_tokens.pop(wo_id, None)
                raise ClaimLost(wo_id)
            if resp.status_code == 422:
                print(f"[runner] validate rejected: {resp.json().get('detail')}")
                return False
            return resp.status_code == 200
    except ClaimLost:
        raise
    except Exception as e:
        print(f"[runner] validate failed: {e}")
        return False


async def complete(wo_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/complete", headers=_lease_headers(wo_id),
                              json={"wo": wo_id, "agent": AGENT_NAME})
    except Exception as e:
        print(f"[runner] complete {wo_id} failed: {e}")


async def post_thread_message(
    wo_id: str,
    content: str,
    msg_type: str = "text",
    metadata: dict | None = None,
) -> None:
    """Post a message to the WO thread (non-blocking — errors are swallowed)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/thread/{wo_id}/messages", headers=_AUTH, json={
                "author": AGENT_NAME,
                "role": "agent",
                "type": msg_type,
                "content": content,
                "metadata": metadata or {},
            })
    except Exception:
        pass  # thread messages are best-effort


async def get_dispatch_status(wo_id: str) -> str:
    """Return the current dispatch status for a WO ('approved', 'rejected', etc.)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch", headers=_AUTH)
            resp.raise_for_status()
            state = resp.json()
            return state.get(wo_id, {}).get("status", "unknown")
    except Exception:
        return "unknown"


async def get_prior_rejections(wo_id: str) -> list[dict]:
    """Return prior rejected validations for this WO, newest first, with a reject_reason."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/validations", headers=_AUTH)
            resp.raise_for_status()
            return [
                v for v in reversed(resp.json())
                if v.get("wo") == wo_id
                and v.get("status") == "rejected"
                and v.get("reject_reason")
            ]
    except Exception:
        return []


async def get_thread_messages(wo_id: str) -> list[dict]:
    """Return all thread messages for a WO."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/thread/{wo_id}/messages", headers=_AUTH)
            resp.raise_for_status()
            msgs = resp.json()
            return msgs if isinstance(msgs, list) else []
    except Exception:
        return []


async def release_dispatch(wo_id: str) -> None:
    """Remove WO from dispatch state so capacity is freed and it can be re-claimed."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/dispatch/{wo_id}/retry", headers=_lease_headers(wo_id))
        _claim_tokens.pop(wo_id, None)
    except Exception as e:
        print(f"[runner] release_dispatch {wo_id} failed: {e}")


async def get_agent_config() -> dict:
    """Fetch agent config from the orchestrator (preferred backend, reviewers, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/config", headers=_AUTH)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[runner] get_agent_config failed: {e}")
        return {}
