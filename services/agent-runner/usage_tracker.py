"""Records WO run metrics to the orchestrator after each WO completes."""
from datetime import UTC, datetime

import httpx


async def record_run(
    orchestrator_url: str,
    wo_id: str,
    backend: str,
    start_time: datetime,
    success: bool,
    ask_calls: list[dict],
) -> None:
    duration_s = (datetime.now(UTC) - start_time).total_seconds()
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "wo": wo_id,
        "backend": backend,
        "duration_s": duration_s,
        "success": success,
        "ask_calls": ask_calls,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{orchestrator_url}/api/usage", json=record)
    except Exception as e:
        print(f"[usage_tracker] failed to record run for {wo_id}: {e}")
