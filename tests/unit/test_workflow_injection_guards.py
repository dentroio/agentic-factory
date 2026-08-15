"""Guards against AF-13/AF-14 workflow injection and untrusted script execution."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_planning_agent_does_not_interpolate_issue_fields_in_run_scripts():
    text = (WORKFLOWS / "planning-agent.yml").read_text()
    run_blocks = text.split("run: |")
    for block in run_blocks[1:]:
        body = block.split("\n      - ")[0]
        assert "${{ github.event.issue.title }}" not in body
        assert "${{ github.event.issue.body }}" not in body
        assert "${{ github.event.issue.number }}" not in body
    assert "ISSUE_TITLE: ${{ github.event.issue.title }}" in text
    assert '--title "$ISSUE_TITLE"' in text


def test_ci_auto_fix_runs_trusted_scripts_not_pr_tree():
    text = (WORKFLOWS / "ci-auto-fix.yml").read_text()
    assert "python3 trusted-scripts/scripts/ai_fix.py" in text
    assert "python3 scripts/ai_fix.py" not in text
    assert "path: trusted-scripts" in text
    assert "persist-credentials: false" in text
    assert "--log-excerpt \"$LOG_EXCERPT\"" in text or '--log-excerpt "$LOG_EXCERPT"' in text


def test_ai_review_applier_runs_trusted_scripts_not_pr_tree():
    text = (WORKFLOWS / "ai-review-applier.yml").read_text()
    assert "python3 trusted-scripts/scripts/ai_review_apply.py" in text
    assert "python3 scripts/ai_review_apply.py" not in text


def test_ai_review_runs_trusted_script():
    text = (WORKFLOWS / "ai-review.yml").read_text()
    assert "python3 trusted-scripts/scripts/ai_review.py" in text
    assert "python3 scripts/ai_review.py" not in text


def test_dependabot_bridge_does_not_interpolate_pr_fields_into_js_templates():
    text = (WORKFLOWS / "dependabot-wo-bridge.yml").read_text()
    assert "const prTitle = `${{ steps.pr.outputs.pr_title }}`" not in text
    assert "PR_TITLE: ${{ steps.pr.outputs.pr_title }}" in text
    assert "const prTitle = process.env.PR_TITLE;" in text
