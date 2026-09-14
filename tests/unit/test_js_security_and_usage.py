"""WO-1105: JS security scan hardening + API usage recording."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import quality_gate as qg  # noqa: E402
import usage_tracker as ut  # noqa: E402


def test_js_exts_include_react():
    assert ".tsx" in qg._JS_EXTS
    assert ".jsx" in qg._JS_EXTS


def test_eslint_security_rules_cover_more_than_eval():
    assert "security/detect-eval-with-expression" in qg._ESLINT_SECURITY_RULES
    assert "security/detect-child-process" in qg._ESLINT_SECURITY_RULES
    assert len(qg._ESLINT_SECURITY_RULES) >= 5


def test_js_danger_patterns_include_react_xss():
    text = "dangerouslySetInnerHTML={{ __html: x }}"
    matched = [desc for pat, desc in qg._JS_DANGER_PATTERNS if pat.search(text)]
    assert matched


def test_build_usage_record_prefers_api_tokens():
    start = datetime.now(UTC) - timedelta(seconds=5)
    rec = ut.build_usage_record(
        "WO-1105",
        "claude",
        start,
        True,
        [],
        prompt="x" * 4000,  # would estimate to 1000 if used
        env={"USAGE_RATE_CLAUDE_PER_MTOK": "3.0"},
        api_usage=[
            {"input_tokens": 100, "output_tokens": 50, "reviewer": "security"},
            {"input_tokens": 80, "output_tokens": 20, "reviewer": "architecture"},
        ],
    )
    assert rec["usage_source"] == "api"
    assert rec["prompt_tokens"] == 180
    assert rec["completion_tokens"] == 70
    assert rec["prompt_tokens_est"] == 180
    # exact: (180+70)/1e6 * 3 = 0.00075
    assert rec["estimated_cost_usd"] == 0.00075


def test_build_usage_record_falls_back_to_estimate():
    start = datetime.now(UTC) - timedelta(seconds=5)
    rec = ut.build_usage_record(
        "WO-1105",
        "claude",
        start,
        True,
        [{"question": "why?"}],
        prompt="x" * 400,
        env={"USAGE_RATE_CLAUDE_PER_MTOK": "3.0"},
    )
    assert rec["usage_source"] == "estimate"
    assert rec["prompt_tokens"] is None
    assert rec["prompt_tokens_est"] == 100


def test_quality_gate_npx_pins_eslint8():
    src = (AGENT_RUNNER_DIR / "quality_gate.py").read_text()
    assert "eslint@8.57.1" in src
    assert "eslint-plugin-security@3.0.1" in src
    assert "--yes" in src


def test_review_chain_returns_api_usage():
    src = (AGENT_RUNNER_DIR / "review_chain.py").read_text()
    assert "input_tokens" in src
    assert "api_usage" in src
    assert "return chain_passed, all_findings, api_usage" in src
