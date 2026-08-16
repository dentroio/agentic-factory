"""Guards: every GitHub workflow declares a concurrency group (AF-44)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_every_workflow_has_concurrency():
    files = sorted(p for p in WORKFLOWS.glob("*.yml") if not p.name.endswith(".template"))
    assert files, "expected workflow YAML files"
    missing = [p.name for p in files if "\nconcurrency:" not in p.read_text(encoding="utf-8")]
    assert missing == [], f"workflows missing concurrency: {missing}"


def test_risk_tier_still_does_not_cancel_in_progress():
    text = (WORKFLOWS / "risk-tier-approval.yml").read_text(encoding="utf-8")
    assert "cancel-in-progress: false" in text
    assert "cancel-in-progress: true" not in text
