import json
import os
from datetime import UTC, datetime

from github_client import get_branch_file

RUNS_PATH = os.getenv("RUNS_PATH", "docs/factory/runs")


async def get_agent_status(branch: str, wo_number: int) -> dict | None:
    content = await get_branch_file(branch, f"{RUNS_PATH}/WO-{wo_number}.json")
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:
        return None


def format_duration(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except Exception:
        return "unknown"
