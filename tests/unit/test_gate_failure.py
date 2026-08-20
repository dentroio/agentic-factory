"""Live 18 Aug 2026 gate logs must classify as infra vs code, not one bucket."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
STATUS_SITE_DIR = REPO_ROOT / "services" / "status-site"
sys.path.insert(0, str(AGENT_RUNNER_DIR))
sys.path.insert(0, str(STATUS_SITE_DIR))

import gate_failure as gf  # noqa: E402
from wo_parser import parse_wo_file  # noqa: E402
from wo_reconcile import apply_live_status, dispatch_status_counts  # noqa: E402


LOCK_LOG = "CI lock wait timed out — another CI run held the lock too long"
LUCIDE_LOG = """
x Build failed in 2.62s
error during build:
[commonjs--resolver] Failed to resolve entry for package "lucide-react".
make[1]: *** [frontend-check] Error 1
make: *** [ci-local] Error 2
"""
TIMEOUT_LOG = "make timed out after 1800s"
CODE_LOG = """
tests/unit/test_topology_device_seed_import_api.py ....                  [ 95%]
    assert asset["winner_explanation"] is not None
E   assert None is not None
FAILED tests/unit/test_identity_360_api.py::test_build_identity_360_evidence_sorted_by_reliability
=========== 1 failed, 1996 passed, 52 warnings in 145.57s (0:02:25) ============
make[1]: *** [test] Error 1
make: *** [ci-local] Error 2
"""


def _board(wos: dict) -> dict[str, list[int]]:
    columns: dict[str, list[int]] = {}
    for num, spec in sorted(wos.items()):
        columns.setdefault(spec.board_column, []).append(num)
    return columns


def _spec(number: int, status: str = "📋 Open", title: str = "Some work"):
    content = f"# WO-{number} — {title}\n\n**Status:** {status}\n**Priority:** P2\n"
    return parse_wo_file(content, f"WO-{number}-some-work.md", repo="dentroio/clarion")


def test_lock_timeout_is_infra():
    assert gf.classify_ci_output(LOCK_LOG) == gf.LOCK
    assert gf.is_infra(gf.LOCK)


def test_lucide_is_node_modules_not_code():
    assert gf.classify_ci_output(LUCIDE_LOG) == gf.NODE_MODULES


def test_wall_clock_hang_is_timeout():
    assert gf.classify_ci_output(TIMEOUT_LOG) == gf.TIMEOUT
    assert gf.is_infra(gf.TIMEOUT)


def test_pytest_assertion_is_code():
    assert gf.classify_ci_output(CODE_LOG) == gf.CODE
    assert not gf.is_infra(gf.CODE)


def test_code_wins_over_timeout_if_both_present():
    mixed = CODE_LOG + "\nmake timed out after 1800s\n"
    assert gf.classify_ci_output(mixed) == gf.CODE


def test_park_reason_includes_class():
    reason = gf.park_reason(gf.CODE, "CI tests failed")
    assert "code" in reason
    assert "CI tests failed" in reason


def test_runner_does_not_promise_an_automatic_fix_unless_it_queues_one():
    text = (AGENT_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
    assert "the agent will fix this automatically" not in text
    assert "MAX_GATE_FIX_ROUNDS" in text
    assert "classify_ci_output" in text


def test_retry_prompt_loads_thread_without_a_validation_rejection():
    text = (AGENT_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
    setup = text.split("async def run_wo")[1].split("async def ")[0]
    assert "get_thread_messages(wo_id) if prior_rejections" not in setup
    assert "get_thread_messages(wo_id)" in setup


def test_failed_gate_park_is_stalled_not_review():
    wos = {496: _spec(496)}
    dispatch = {
        "WO-496": {
            "status": "awaiting_commit",
            "step": "quality gate failed (code): CI tests failed",
        }
    }
    apply_live_status(wos, branches=[], prs=[], dispatch=dispatch, merged_prs=[])
    assert _board(wos)["stalled"] == [496]
    assert _board(wos).get("review", []) == []
    counts = dispatch_status_counts(dispatch)
    assert counts["awaiting_review"] == 0
    assert counts["stalled"] == 1
