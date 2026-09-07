"""Records WO run metrics (duration + estimated tokens/cost) to the orchestrator."""
from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

# Crude per-1M-token USD rates for budgeting (subscription CLIs still burn quota).
# Override with USAGE_RATE_<BACKEND>_PER_MTOK if needed.
_DEFAULT_RATES: dict[str, float] = {
    "claude": 3.0,
    "cursor": 3.0,
    "codex": 5.0,
    "gemini": 1.0,
    "unknown": 3.0,
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Empty → 0."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def rate_for_backend(backend: str, env: dict[str, str] | None = None) -> float:
    e = env if env is not None else os.environ
    key = f"USAGE_RATE_{backend.upper().replace('-', '_')}_PER_MTOK"
    raw = e.get(key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_RATES.get(backend.lower(), _DEFAULT_RATES["unknown"])


def estimate_cost_usd(
    *,
    backend: str,
    prompt_tokens: int,
    ask_tokens: int,
    env: dict[str, str] | None = None,
) -> float:
    """Estimate USD for prompt + ask traffic (completion assumed ~prompt size)."""
    # Assume completion ≈ prompt for coding runs; ask answers ≈ ask prompts.
    total = prompt_tokens * 2 + ask_tokens * 2
    return round((total / 1_000_000.0) * rate_for_backend(backend, env), 6)


def build_usage_record(
    wo_id: str,
    backend: str,
    start_time: datetime,
    success: bool,
    ask_calls: list[dict],
    prompt: str = "",
    env: dict[str, str] | None = None,
) -> dict:
    prompt_tokens = estimate_tokens(prompt)
    ask_text = "\n".join(
        str(c.get("question", "") or c.get("prompt", "") or c.get("content", ""))
        for c in (ask_calls or [])
    )
    ask_tokens = estimate_tokens(ask_text)
    return {
        "ts": datetime.now(UTC).isoformat(),
        "wo": wo_id,
        "backend": backend,
        "duration_s": (datetime.now(UTC) - start_time).total_seconds(),
        "success": success,
        "ask_calls": ask_calls or [],
        "prompt_tokens_est": prompt_tokens,
        "ask_tokens_est": ask_tokens,
        "estimated_cost_usd": estimate_cost_usd(
            backend=backend,
            prompt_tokens=prompt_tokens,
            ask_tokens=ask_tokens,
            env=env,
        ),
    }


def weekly_budget_usd(env: dict[str, str] | None = None) -> float:
    e = env if env is not None else os.environ
    raw = (e.get("USAGE_BUDGET_USD_WEEK") or "0").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def week_spend_usd(records: list[dict], *, week_ago_iso: str) -> float:
    total = 0.0
    for r in records:
        if (r.get("ts") or "") < week_ago_iso:
            continue
        try:
            total += float(r.get("estimated_cost_usd") or 0.0)
        except (TypeError, ValueError):
            continue
    return round(total, 6)


async def budget_hold_reason(orchestrator_url: str, auth_token: str = "") -> str | None:
    """Return a human reason if weekly estimated spend exceeds budget; else None."""
    budget = weekly_budget_usd()
    if budget <= 0:
        return None
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{orchestrator_url}/api/usage", headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as e:
        print(f"[usage_tracker] budget check failed: {e}")
        return None

    spend = float((data.get("summary") or {}).get("estimated_cost_usd_week") or 0.0)
    if spend >= budget:
        return (
            f"Weekly estimated LLM spend ${spend:.2f} >= budget "
            f"${budget:.2f} (USAGE_BUDGET_USD_WEEK) — not claiming new WOs"
        )
    return None


async def record_run(
    orchestrator_url: str,
    wo_id: str,
    backend: str,
    start_time: datetime,
    success: bool,
    ask_calls: list[dict],
    prompt: str = "",
) -> None:
    record = build_usage_record(
        wo_id, backend, start_time, success, ask_calls, prompt=prompt
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{orchestrator_url}/api/usage", json=record)
    except Exception as e:
        print(f"[usage_tracker] failed to record run for {wo_id}: {e}")
