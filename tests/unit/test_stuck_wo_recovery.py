"""Tests for the stuck-WO reassignment fix (health_agent.py) and the max-retry
notification gate (orchestrator.py's /api/claim).

Root cause this covers: health_agent's check_stuck_wos() only checked git commit
age to decide a WO was "stuck," so a WO with real uncommitted work in progress
(no commit yet, but actively being edited) got its backend reassigned out from
under it repeatedly, burning attempt_count up to MAX_RETRY_ATTEMPTS for no real
reason — and once at the ceiling, claim() 429s forever with no human ever told,
since runner.py logged that identically to routine 409 contention.

health_agent.py has no heavy deps (stdlib only), so it's imported directly here
rather than mirrored, unlike orchestrator.py (test_reservation.py's convention).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AGENT_RUNNER_DIR = Path(__file__).resolve().parents[2] / "services" / "agent-runner"
sys.path.insert(0, str(AGENT_RUNNER_DIR))

import health_agent  # noqa: E402


def _init_repo_with_worktree(tmp_path: Path, wo_num: int) -> Path:
    """Set up a bare-bones git repo with a WO worktree, mirroring the factory's
    .worktrees/wo-NNN-slug/ layout that the helpers glob for."""
    repo = tmp_path / "clarion"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    worktree_dir = repo / ".worktrees" / f"wo-{wo_num}-some-slug"
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-q",
            "-b",
            f"wo/{wo_num}-some-slug",
            str(worktree_dir),
        ],
        cwd=repo,
        check=True,
    )
    return repo


# ── _worktree_uncommitted_activity_age ──────────────────────────────────────


def test_uncommitted_activity_detected_on_recently_touched_file(tmp_path):
    repo = _init_repo_with_worktree(tmp_path, 999)
    wt = repo / ".worktrees" / "wo-999-some-slug"
    (wt / "app.py").write_text("changed")

    age_h = health_agent._worktree_uncommitted_activity_age("WO-999", str(repo))
    assert age_h is not None
    assert age_h < 0.01  # just written, should be near-zero hours old


def test_clean_worktree_returns_none(tmp_path):
    repo = _init_repo_with_worktree(tmp_path, 998)

    age_h = health_agent._worktree_uncommitted_activity_age("WO-998", str(repo))
    assert age_h is None


def test_missing_worktree_returns_none(tmp_path):
    repo = tmp_path / "clarion"
    repo.mkdir()
    (repo / ".worktrees").mkdir()

    age_h = health_agent._worktree_uncommitted_activity_age("WO-777", str(repo))
    assert age_h is None


def test_new_untracked_file_counts_as_activity(tmp_path):
    """The real bug scenario: an agent creates a brand-new component file and
    hasn't committed yet — that must register as recent activity, not silence."""
    repo = _init_repo_with_worktree(tmp_path, 427)
    wt = repo / ".worktrees" / "wo-427-some-slug"
    (wt / "NewComponent.tsx").write_text("export const X = () => null;")

    age_h = health_agent._worktree_uncommitted_activity_age("WO-427", str(repo))
    assert age_h is not None
    assert age_h < 0.01


# ── check_stuck_wos: max-retry-ceiling short-circuit ────────────────────────


def test_at_retry_ceiling_notifies_instead_of_reassigning(tmp_path, monkeypatch):
    """A WO already at MAX_RETRY_ATTEMPTS must not be reassigned (the next claim()
    would just 429 regardless of backend) — it should be flagged for manual reset."""
    import asyncio

    repo = _init_repo_with_worktree(tmp_path, 427)
    wt = repo / ".worktrees" / "wo-427-some-slug"
    # No uncommitted changes — and backdate the worktree branch's commit so
    # commit_age_h doesn't short-circuit the check before it ever reaches the
    # retry-ceiling logic. Must amend inside the worktree itself: its branch is
    # a separate ref from main's, sharing history only up to the initial commit.
    old_date = "2020-01-01T00:00:00"
    import os as _os

    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", f"--date={old_date}"],
        cwd=wt,
        check=True,
        env={**_os.environ, "GIT_COMMITTER_DATE": old_date},
    )

    dispatch = {
        "WO-427": {
            "status": "in_progress",
            "claimed_at": "2020-01-01T00:00:00Z",
            "backend": "cursor",
            "attempt_count": health_agent.MAX_RETRY_ATTEMPTS,
        }
    }

    notified = []
    reassigned = []
    released = []

    async def fake_get(path):
        return dispatch

    async def fake_notify(title, body, level="default"):
        notified.append((title, body, level))

    async def fake_post(path, params=None):
        reassigned.append((path, params))
        return {"ok": True}

    async def fake_delete(path):
        released.append(path)
        return True

    monkeypatch.setenv("LOCAL_REPO_PATH", str(repo))
    monkeypatch.setattr(health_agent, "_get", fake_get)
    monkeypatch.setattr(health_agent, "_notify", fake_notify)
    monkeypatch.setattr(health_agent, "_post", fake_post)
    monkeypatch.setattr(health_agent, "_delete", fake_delete)
    health_agent._acted.clear()

    asyncio.run(health_agent.check_stuck_wos())

    assert released == []  # never released the claim to re-dispatch it
    assert reassigned == []  # never called /api/pm/dispatch to reassign
    assert len(notified) == 1
    assert "WO-427" in notified[0][0]
    assert "reset" in notified[0][1].lower()


# ── check_local_runners: missing-plist dedup ────────────────────────────────


def test_missing_plist_notifies_once_not_every_cycle(monkeypatch):
    """Found live: gemini's plist was never installed on this workstation, and
    check_local_runners() re-sent 'Runner gemini won't start' every 5-minute
    cycle forever, because the dedup guard only ever got set on a *successful*
    reload — a plist that doesn't exist can never succeed, so it never got
    deduped. Must notify once (distinctly) and then stay silent, not retry a
    launchctl load that can't possibly work."""
    import asyncio

    notified = []

    async def fake_notify(title, body, level="default"):
        notified.append((title, body, level))

    monkeypatch.setattr(health_agent, "_launchd_status", lambda: {})
    monkeypatch.setattr(health_agent, "_notify", fake_notify)
    monkeypatch.setattr(health_agent, "DRY_RUN", False)
    monkeypatch.setattr(
        health_agent,
        "RUNNER_SERVICES",
        {"com.dentroio.factory-agent-gemini": "gemini"},
    )
    monkeypatch.setattr(Path, "exists", lambda self: False)
    health_agent._acted.clear()

    asyncio.run(health_agent.check_local_runners())
    asyncio.run(health_agent.check_local_runners())
    asyncio.run(health_agent.check_local_runners())

    assert len(notified) == 1
    assert "gemini" in notified[0][0].lower()
    assert "not installed" in notified[0][0].lower()
