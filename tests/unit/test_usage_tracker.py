"""WO-1093: usage estimates and weekly budget helpers."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import usage_tracker as ut  # noqa: E402


def test_estimate_tokens_roughly_chars_over_four():
    assert ut.estimate_tokens("") == 0
    assert ut.estimate_tokens("abcd") == 1
    assert ut.estimate_tokens("a" * 400) == 100


def test_build_usage_record_includes_cost_fields():
    start = datetime.now(UTC) - timedelta(seconds=12)
    rec = ut.build_usage_record(
        "WO-1093",
        "claude",
        start,
        True,
        [{"question": "why?"}],
        prompt="x" * 400,
        env={"USAGE_RATE_CLAUDE_PER_MTOK": "3.0"},
    )
    assert rec["prompt_tokens_est"] == 100
    assert rec["ask_tokens_est"] >= 1
    assert rec["estimated_cost_usd"] > 0
    assert rec["wo"] == "WO-1093"
    assert rec["success"] is True


def test_week_spend_sums_recent_only():
    now = datetime.now(UTC)
    week_ago = (now - timedelta(days=7)).isoformat()
    records = [
        {"ts": (now - timedelta(days=1)).isoformat(), "estimated_cost_usd": 1.5},
        {"ts": (now - timedelta(days=10)).isoformat(), "estimated_cost_usd": 9.0},
        {"ts": (now - timedelta(days=2)).isoformat(), "estimated_cost_usd": 0.25},
    ]
    assert ut.week_spend_usd(records, week_ago_iso=week_ago) == 1.75


def test_weekly_budget_defaults_disabled():
    assert ut.weekly_budget_usd(env={}) == 0.0
    assert ut.weekly_budget_usd(env={"USAGE_BUDGET_USD_WEEK": "25"}) == 25.0
