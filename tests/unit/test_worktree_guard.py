"""Worktree HEAD must be wo/NNN-* before the runner reuses it."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "services" / "agent-runner"


def _load():
    spec = importlib.util.spec_from_file_location("worktree_guard", RUNNER / "worktree_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_branch_matches_wo():
    g = _load()
    assert g.branch_matches_wo("wo/479-slug", 479)
    assert not g.branch_matches_wo("wo/485-other", 479)
    assert not g.branch_matches_wo("HEAD", 479)
    assert not g.branch_matches_wo("main", 479)


def test_refuse_wrong_branch(tmp_path):
    g = _load()
    repo = tmp_path / "clarion"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "README").write_text("x\n")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "wo/485-other"], cwd=repo, check=True, capture_output=True)
    wt = repo / ".worktrees" / "wo-479-named-wrong"
    wt.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", str(wt), "wo/485-other"], cwd=repo, check=True, capture_output=True)
    err = g.refuse_wrong_branch(repo, 479)
    assert err is not None
    assert "wo/485-other" in err
    assert g.refuse_wrong_branch(repo, 485) is None
