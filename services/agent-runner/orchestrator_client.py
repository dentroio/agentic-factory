"""Thin async wrapper around the orchestrator REST API."""
from datetime import UTC, datetime

import httpx

from config import ORCHESTRATOR_URL, AGENT_NAME, HOSTNAME


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def get_next() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/next")
            resp.raise_for_status()
            data = resp.json()
            return data if data.get("wo") else None
    except Exception as e:
        print(f"[runner] get_next failed: {e}")
        return None


async def claim(wo_id: str, slug: str = "", backend: str = "") -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/claim", json={
                "wo": wo_id,
                "agent": AGENT_NAME,
                "backend": backend,
                "workstation": HOSTNAME,
                "slug": slug,
            })
            return resp.status_code == 200
    except Exception as e:
        print(f"[runner] claim {wo_id} failed: {e}")
        return False


async def checkin(wo_id: str, step: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/checkin",
                              params={"wo": wo_id, "agent": AGENT_NAME, "step": step})
    except Exception:
        pass  # non-blocking


async def request_validate(wo_id: str, verify_url: str = "", steps: list[str] | None = None,
                           ci_passed: bool = True, security_passed: bool = True,
                           thread_summary: str = "", pr_url: str = "",
                           pr_number: int | None = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORCHESTRATOR_URL}/api/validate", json={
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
            if resp.status_code == 422:
                print(f"[runner] validate rejected: {resp.json().get('detail')}")
                return False
            return resp.status_code == 200
    except Exception as e:
        print(f"[runner] validate failed: {e}")
        return False


async def complete(wo_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{ORCHESTRATOR_URL}/api/complete",
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
            await client.post(f"{ORCHESTRATOR_URL}/api/thread/{wo_id}/messages", json={
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
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/dispatch")
            resp.raise_for_status()
            state = resp.json()
            return state.get(wo_id, {}).get("status", "unknown")
    except Exception:
        return "unknown"


async def get_agent_config() -> dict:
    """Fetch agent config from the orchestrator (preferred backend, reviewers, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORCHESTRATOR_URL}/api/config")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[runner] get_agent_config failed: {e}")
        return {}
