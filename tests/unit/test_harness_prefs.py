"""WO-1095: harness prefs allowlist for Settings → Deploy & Harness."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import product_setup as setup  # noqa: E402


def test_harness_status_defaults(tmp_path: Path):
    prefs = tmp_path / "prefs"
    prefs.write_text("", encoding="utf-8")
    status = setup.harness_status(setup.read_prefs(prefs))
    assert status["values"]["AGENT_PERMISSION_MODE"] == "bypassPermissions"
    assert status["values"]["USAGE_BUDGET_USD_WEEK"] == "0"
    assert "ENGINE_GITHUB_REPO" in status["allowed_keys"]


def test_configure_harness_writes_allowlisted_keys(tmp_path: Path):
    prefs = tmp_path / "prefs"
    result = setup.configure_harness(
        {
            "USAGE_BUDGET_USD_WEEK": "25",
            "AGENT_TOOL_ALLOWLIST": "Read,Bash",
            "GEMINI_YOLO": "0",
            "ENGINE_GITHUB_REPO": "acme/factory-engine",
        },
        prefs_file=prefs,
    )
    assert result["values"]["USAGE_BUDGET_USD_WEEK"] == "25"
    assert result["values"]["AGENT_TOOL_ALLOWLIST"] == "Read,Bash"
    assert result["values"]["GEMINI_YOLO"] == "0"
    assert result["values"]["ENGINE_GITHUB_REPO"] == "acme/factory-engine"
    text = prefs.read_text(encoding="utf-8")
    assert "USAGE_BUDGET_USD_WEEK=25" in text


def test_configure_harness_rejects_unknown_and_bad_mode(tmp_path: Path):
    prefs = tmp_path / "prefs"
    with pytest.raises(setup.ProductSetupError, match="Unknown harness key"):
        setup.configure_harness({"NOT_A_KEY": "x"}, prefs_file=prefs)
    with pytest.raises(setup.ProductSetupError, match="AGENT_PERMISSION_MODE"):
        setup.configure_harness({"AGENT_PERMISSION_MODE": "yolo"}, prefs_file=prefs)
