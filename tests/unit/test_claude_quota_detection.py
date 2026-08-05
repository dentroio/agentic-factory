"""Regression test for claude.py's quota/session-limit detection regex.

A missed wording variant here isn't cosmetic: the runner only recognizes a
quota event (triggering fallback to cursor/codex) when _QUOTA_RE matches the
backend's output. On a miss it sees a plain nonzero exit, treats the run as
complete, and plows forward into rebuild + quality gate on whatever
half-done state existed — burning a full attempt for zero real work with no
fallback to an available backend. "you've hit your ... limit" was missing
this exact way and cost WO-440 an attempt on 2026-08-04.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"

if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


claude_backend = _load("claude_backend_under_test", AGENT_RUNNER_DIR / "backends" / "claude.py")

# Real messages Claude Code has been observed to emit for a usage/rate cap,
# collected across this session plus the wording variants the original
# pattern already covered.
QUOTA_MESSAGES = [
    "You've hit your session limit · resets 9:40pm (America/New_York)",
    "you've hit your usage limit for this session",
    "usage limit reached",
    "You've reached your usage limit for Claude Code",
    "rate limit exceeded, please try again later",
    "Please upgrade your plan to continue",
    "See claude.ai/upgrade for details",
]

NON_QUOTA_MESSAGES = [
    "Running tests...",
    "Implementing WO-440 per spec",
    "All 358 frontend Jest tests pass",
    "limiting the scope of this change to the identity module",
    "exit code 1",  # a plain failure with no quota wording must NOT false-positive
]


@pytest.mark.parametrize("message", QUOTA_MESSAGES)
def test_quota_re_matches_known_quota_messages(message):
    assert claude_backend._QUOTA_RE.search(message), (
        f"_QUOTA_RE failed to match a known quota message: {message!r}"
    )


@pytest.mark.parametrize("message", NON_QUOTA_MESSAGES)
def test_quota_re_does_not_false_positive_on_normal_output(message):
    assert not claude_backend._QUOTA_RE.search(message), (
        f"_QUOTA_RE incorrectly matched normal agent output: {message!r}"
    )
