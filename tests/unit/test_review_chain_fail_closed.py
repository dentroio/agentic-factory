"""Review chain must fail closed when every reviewer errors (e.g. 401)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("openai", MagicMock())

import review_chain as rc  # noqa: E402


class _Monitor:
    def __init__(self):
        self.posts: list[str] = []

    async def post(self, msg: str, msg_type: str = "text", metadata=None):
        self.posts.append(msg)


def test_all_reviewer_errors_fail_chain():
    monitor = _Monitor()

    async def _boom(*_a, **_k):
        raise RuntimeError("401 Unauthorized")

    with patch.object(
        rc,
        "REVIEW_CHAIN",
        {"P0": ["security", "correctness"], "P1": ["security", "correctness"], "P2": [], "P3": []},
    ):
        with patch.object(rc, "_resolve_anthropic_key", AsyncMock(return_value="sk-test")):
            with patch.object(rc, "_run_sdk_reviewer", side_effect=_boom):
                with patch.object(rc, "checkin", AsyncMock()):
                    passed, findings, _usage = asyncio.run(
                        rc.run_review_chain(
                            wo_spec={
                                "wo": 1,
                                "title": "t",
                                "priority": "P1",
                                "services": "x",
                            },
                            diff="diff --git a/x b/x\n",
                            monitor=monitor,
                            previous_findings=[],
                            coding_backend="claude",
                            wo_id="WO-1",
                        )
                    )

    assert passed is False
    assert findings == []
    assert any("failed closed" in p.lower() for p in monitor.posts)


def test_source_documents_fail_closed():
    text = (AGENT_RUNNER_DIR / "review_chain.py").read_text(encoding="utf-8")
    harness = text.split("# --- Parallel SDK harness ---")[1].split("else:")[0]
    assert "chain_passed = False" in harness
    assert "failed closed" in harness
    assert "completed == 0" in harness


def test_runner_skips_cursor_claim_without_api_key():
    text = (AGENT_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
    assert "CURSOR_API_KEY" in text
    assert "skipping claim" in text
    assert 'run_backend == "cursor"' in text
