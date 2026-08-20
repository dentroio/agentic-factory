"""External occupancy: Clarion claim files, open PRs, dirty/wrong-branch worktrees."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"
RUNNER = REPO_ROOT / "services" / "agent-runner"


def _load_occupancy():
    spec = importlib.util.spec_from_file_location("factory_occupancy", ORCH / "occupancy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_claim_does_not_occupy():
    occ = _load_occupancy()
    assert occ.reason_from_claim({"status": "complete", "agent": "cursor"}) is None
    assert occ.reason_from_claim({"status": "done"}) is None
    assert occ.reason_from_claim({}) is None
    assert occ.reason_from_claim(None) is None


def test_live_claim_occupies():
    occ = _load_occupancy()
    reason = occ.reason_from_claim({"status": "in_progress", "agent": "steve-cursor"})
    assert reason is not None
    assert "in_progress" in reason
    assert "steve-cursor" in reason


def test_open_pr_occupies():
    occ = _load_occupancy()
    assert occ.reason_from_open_pr(482, {482: "https://github.com/org/repo/pull/1"})
    assert occ.reason_from_open_pr(482, {99: "https://example"}) is None


def test_wrong_branch_worktree_occupies():
    occ = _load_occupancy()
    info = {
        "exists": True,
        "worktrees": [{
            "path": "/repos/primary/.worktrees/wo-479-slug",
            "branch": "wo/485-other",
            "dirty": False,
            "ahead": 0,
            "git_ok": True,
        }],
    }
    reason = occ.reason_from_worktrees(479, info)
    assert reason is not None
    assert "wo/485-other" in reason


def test_clean_matching_worktree_does_not_occupy():
    occ = _load_occupancy()
    info = {
        "exists": True,
        "worktrees": [{
            "path": "/repos/primary/.worktrees/wo-500-slug",
            "branch": "wo/500-slug",
            "dirty": False,
            "ahead": 0,
            "git_ok": True,
        }],
    }
    assert occ.reason_from_worktrees(500, info) is None


def test_dirty_worktree_occupies():
    occ = _load_occupancy()
    info = {
        "exists": True,
        "worktrees": [{
            "path": "/repos/primary/.worktrees/wo-482-slug",
            "branch": "wo/482-slug",
            "dirty": True,
            "ahead": 0,
            "git_ok": True,
        }],
    }
    assert "uncommitted" in occ.reason_from_worktrees(482, info)


def test_factory_owned_lease_is_not_external_occupancy():
    occ = _load_occupancy()
    reason = occ.occupancy_reason(
        wo_num=482,
        claim={"status": "in_progress", "agent": "human"},
        worktrees={"exists": True, "worktrees": [{
            "path": "x", "branch": "wo/482-x", "dirty": True, "ahead": 0, "git_ok": True,
        }]},
        open_pr_urls={482: "https://example/pull/1"},
        factory_status="in_progress",
    )
    assert reason is None


def test_retry_queued_allows_own_dirty_tree_but_not_open_pr():
    occ = _load_occupancy()
    dirty = {
        "exists": True,
        "worktrees": [{
            "path": "wo-505-x", "branch": "wo/505-x", "dirty": True, "ahead": 1, "git_ok": True,
        }],
    }
    assert occ.occupancy_reason(
        wo_num=505, worktrees=dirty, factory_status="retry_queued",
    ) is None
    assert occ.occupancy_reason(
        wo_num=505,
        worktrees=dirty,
        open_pr_urls={505: "https://github.com/org/repo/pull/9"},
        factory_status="retry_queued",
    )


def test_retry_queued_ignores_unreadable_host_worktree():
    """Orchestrator runs in Docker; host worktrees look unreadable via git."""
    occ = _load_occupancy()
    unread = {
        "exists": True,
        "worktrees": [{
            "path": "wo-502-x", "branch": "", "dirty": True, "ahead": 0, "git_ok": False,
        }],
    }
    assert occ.occupancy_reason(wo_num=502, worktrees=unread, factory_status="retry_queued") is None
    assert occ.occupancy_reason(wo_num=502, worktrees=unread, factory_status="") is not None


def test_retry_queued_still_refuses_wrong_branch():
    occ = _load_occupancy()
    wrong = {
        "exists": True,
        "worktrees": [{
            "path": "wo-479-x", "branch": "wo/485-y", "dirty": False, "ahead": 0, "git_ok": True,
        }],
    }
    reason = occ.occupancy_reason(wo_num=479, worktrees=wrong, factory_status="retry_queued")
    assert reason is not None
    assert "wo/485-y" in reason


def test_load_claim_file(tmp_path):
    occ = _load_occupancy()
    runs = tmp_path / "docs" / "factory" / "runs"
    runs.mkdir(parents=True)
    (runs / "WO-337.json").write_text(json.dumps({
        "status": "in_progress", "agent": "cursor",
    }))
    claim = occ.load_claim_file(tmp_path, 337)
    assert occ.reason_from_claim(claim)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_inspect_worktrees_detects_dirty_and_wrong_branch(tmp_path):
    occ = _load_occupancy()
    repo = tmp_path / "clarion"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("x\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "wo/100-ok")

    wt = repo / ".worktrees" / "wo-100-ok"
    wt.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", str(wt), "wo/100-ok")
    (wt / "dirty.txt").write_text("in progress\n")
    info = occ.inspect_worktrees(repo, 100)
    assert info["exists"]
    assert occ.reason_from_worktrees(100, info)

    # Switch that worktree to another WO's branch
    _git(wt, "checkout", "-b", "wo/101-other")
    info = occ.inspect_worktrees(repo, 100)
    reason = occ.reason_from_worktrees(100, info)
    assert reason is not None
    assert "wo/101-other" in reason


def test_orchestrator_never_merges_operator_working_tree():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    sync = text.split("async def _sync_local_repo")[1].split("async def ")[0]
    assert "git fetch" in sync
    assert '"merge"' not in sync
    assert "--ff-only" not in sync
    assert "working tree untouched" in sync
    assert "import occupancy" in text
    assert "_occupancy_reason_for" in text
    assert "/api/dispatch/{wo_id}/park" in text


def test_get_next_and_claim_call_occupancy():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    get_next = text.split("async def get_next")[1].split("async def ")[0]
    claim = text.split("async def claim_wo")[1].split("async def ")[0]
    assert "_occupancy_reason_for" in get_next
    assert "_occupancy_reason_for" in claim
    assert 'status_code=423' in claim


def test_runner_parks_failed_closeout():
    text = (RUNNER / "runner.py").read_text(encoding="utf-8")
    closeout = text.split("pr_url = await _commit_and_push")[1].split("async def ")[0]
    assert "_park_closeout" in closeout
    assert "await release_dispatch(wo_id)" not in closeout.split("if not pr_url")[1].split("if not validated")[0]


def test_runner_refuses_wrong_worktree_branch():
    setup = (RUNNER / "runner.py").read_text(encoding="utf-8").split(
        "async def _setup_worktree"
    )[1].split("async def ")[0]
    assert "refuse_wrong_branch" in setup
    assert "git stash" not in setup


def test_reviewer_rebuilds_from_worktree_not_main():
    text = (RUNNER / "reviewer.py").read_text(encoding="utf-8")
    assert "_worktree_for_wo" in text
    site = text.split("API routes or schemas changed")[1].split("def ")[0]
    assert "_rebuild_and_smoke, worktree" in site
    assert "_rebuild_and_smoke, repo, services" not in site
    assert "shared main clone" in text or "shared main checkout" in text
