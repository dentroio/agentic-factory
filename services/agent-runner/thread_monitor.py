"""Polls the WO thread for new human messages while the agent is working."""
import httpx

from config import ORCHESTRATOR_URL
from orchestrator_client import post_thread_message


def _is_question(content: str) -> bool:
    """Heuristic — is this a question (Q&A) or a directive (guidance)?"""
    stripped = content.strip()
    return stripped.endswith("?") or stripped.lower().startswith(
        ("why", "what", "how", "explain", "can you", "did you", "where", "when", "who")
    )


class ThreadMonitor:
    """Tracks incoming human messages and posts agent replies to a WO thread."""

    def __init__(self, wo_id: str) -> None:
        self.wo_id = wo_id
        self.last_id = ""  # message id of the last human message we processed

    async def poll(self) -> list[dict]:
        """Return new human messages since the last call."""
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                params = {"since": self.last_id} if self.last_id else {}
                resp = await client.get(
                    f"{ORCHESTRATOR_URL}/api/thread/{self.wo_id}/messages",
                    params=params,
                )
                if resp.status_code != 200:
                    return []
                msgs = [m for m in resp.json() if m.get("role") == "human"]
                if msgs:
                    self.last_id = msgs[-1]["id"]
                return msgs
        except Exception:
            return []

    async def post(
        self, content: str, msg_type: str = "text", metadata: dict | None = None
    ) -> None:
        """Post an agent message to the thread (best-effort, never raises)."""
        await post_thread_message(self.wo_id, content, msg_type, metadata)
