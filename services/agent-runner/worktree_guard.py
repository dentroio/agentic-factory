"""Refuse to reuse a WO worktree whose HEAD is not `wo/NNN-*`.

A directory named `.worktrees/wo-479-…` can still be checked out to a
different WO's branch. Re-entering that tree implements the wrong ticket.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def wo_number(raw: str | int) -> str:
    return re.sub(r"^WO-0*", "", str(raw), flags=re.IGNORECASE) or str(raw)


def expected_branch_prefix(wo_num: str | int) -> str:
    return f"wo/{wo_number(wo_num)}-"


def branch_matches_wo(branch: str, wo_num: str | int) -> bool:
    if not branch or branch in ("HEAD", "DETACHED"):
        return False
    return branch.startswith(expected_branch_prefix(wo_num))


def head_branch(worktree: str | Path, timeout: int = 10) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def matching_worktrees(repo_root: str | Path, wo_num: str | int) -> list[Path]:
    base = Path(repo_root) / ".worktrees"
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(f"wo-{wo_number(wo_num)}-*") if p.is_dir())


def refuse_wrong_branch(repo_root: str | Path, wo_num: str | int) -> str | None:
    """Return an error string if any wo-NNN worktree is on the wrong branch."""
    prefix = expected_branch_prefix(wo_num)
    for wt in matching_worktrees(repo_root, wo_num):
        branch = head_branch(wt)
        if not branch_matches_wo(branch, wo_num):
            return (
                f"Worktree {wt.name} is on {branch or 'unknown'}, expected {prefix}* — "
                "refusing to reuse it (would implement the wrong WO)"
            )
    return None
