"""Runner PRs must carry `agent-pr` so CI auto-fix / review applier can run."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
RUNNER = ROOT / "services" / "agent-runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(SCRIPTS))

import factory_status as fs  # noqa: E402
import prompt_builder as pb  # noqa: E402
import setup_factory as setup  # noqa: E402


def test_runner_pr_create_applies_agent_pr_label():
    src = (RUNNER / "runner.py").read_text(encoding="utf-8")
    assert 'AGENT_PR_LABEL = "agent-pr"' in src
    assert "def pr_create_argv(" in src
    assert 'argv.extend(["--label", AGENT_PR_LABEL])' in src
    assert "pr_create_argv(wo_id, title, branch, labeled=True)" in src
    assert "pr_create_argv(wo_id, title, branch, labeled=False)" in src
    assert "async def _ensure_agent_pr_label(" in src
    assert "async def _add_agent_pr_label(" in src


def test_prompt_tells_agents_to_pass_the_label():
    assert "--label agent-pr" in pb.PROCESS_SECTION


def test_factory_status_requires_all_three_engine_labels():
    assert fs.REQUIRED_LABELS == ("new-wo", "agent-pr", "pm-sync")


def test_setup_factory_creates_all_three_labels():
    names = [name for name, _, _ in setup.ENGINE_LABELS]
    assert names == ["new-wo", "agent-pr", "pm-sync"]


def test_engine_ci_docs_do_not_claim_clarion_jobs():
    """AGENT_PROCESS §9 must describe this engine, not Clarion's PR Gate."""
    text = (ROOT / "AGENT_PROCESS.md").read_text(encoding="utf-8")
    section = text.split("## §9 GitHub Actions")[1].split("## §10")[0]
    assert "Unit Tests" in section
    assert "Secret Detection (Gitleaks)" in section
    assert "Claude Code Review" in section
    assert "Risk Tier Approval Gate" in section
    assert "PR Gate" not in section
    assert "Migration Safety" not in section
