"""AF-17: AI reviewer cannot auto-approve P0/P1 or UI/API-surface changes."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import prompt_builder as pb  # noqa: E402
import reviewer  # noqa: E402


def test_p0_p1_never_auto_approve():
    assert not reviewer.may_auto_approve("P0", False, False)
    assert not reviewer.may_auto_approve("P1", False, False)
    assert not reviewer.may_auto_approve("p1", False, False)


def test_ui_or_api_never_auto_approve():
    assert not reviewer.may_auto_approve("P2", True, False)
    assert not reviewer.may_auto_approve("P3", False, True)
    assert not reviewer.may_auto_approve("P2", True, True)


def test_p2_p3_backend_only_may_auto_approve():
    assert reviewer.may_auto_approve("P2", False, False)
    assert reviewer.may_auto_approve("P3", False, False)
    assert reviewer.may_auto_approve("p2", False, False)


def test_missing_priority_is_not_auto_approved():
    assert not reviewer.may_auto_approve(None, False, False)
    assert not reviewer.may_auto_approve("", False, False)
    assert not reviewer.may_auto_approve("unknown", False, False)


def test_claude_review_wraps_the_diff_as_data():
    text = (AGENT_RUNNER_DIR / "reviewer.py").read_text(encoding="utf-8")
    assert "wrap_untrusted(\"pull request diff\"" in text
    assert "from prompt_builder import wrap_untrusted" in text
    assert pb.UNTRUSTED_BEGIN
    assert "may_auto_approve(" in text
    assert "_worktree_for_wo" in text
    assert "shared main" in text
