"""External occupancy — refuse factory claim when someone else already has the WO.

Factory dispatch_state only sees factory leases. A human Cursor session, a live
product claim file, an open GitHub PR, or a dirty `.worktrees/wo-NNN-*` checkout
are all "someone is already here" and must block `/api/next` and `/api/claim`.

Importable without apscheduler — unit tests load this module directly.
"""
from __future__ import annotations

import json
import subprocess
import tarfile
from io import BytesIO
from pathlib import Path

DONE_CLAIM_STATUSES = frozenset({
    "complete", "done", "merged", "closed", "cancelled", "canceled",
})
LIVE_CLAIM_STATUSES = frozenset({
    "in_progress", "claimed", "running", "awaiting_validation",
    "awaiting_commit", "awaiting_human", "implementing",
})

FACTORY_OWNED_STATUSES = frozenset({"claimed", "in_progress"})
# After /api/dispatch/{wo}/retry the row is retry_queued. The dirty worktree
# *is* the parked implementation — occupying on it would make Retry a no-op.
FACTORY_RETRY_STATUSES = frozenset({"retry_queued", "approved"})


def wo_num_from_id(wo_id: str) -> int | None:
    raw = (wo_id or "").strip().upper()
    if raw.startswith("WO-"):
        raw = raw[3:]
    return int(raw) if raw.isdigit() else None


def expected_branch_prefix(wo_num: int) -> str:
    return f"wo/{wo_num}-"


def branch_matches_wo(branch: str, wo_num: int) -> bool:
    if not branch or branch in ("HEAD", "DETACHED"):
        return False
    return branch.startswith(expected_branch_prefix(wo_num))


def claim_file_path(repo_root: str | Path, wo_num: int, runs_path: str = "docs/factory/runs") -> Path:
    return Path(repo_root) / runs_path / f"WO-{wo_num}.json"


def load_claim_file(repo_root: str | Path, wo_num: int, runs_path: str = "docs/factory/runs") -> dict | None:
    path = claim_file_path(repo_root, wo_num, runs_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def reason_from_claim(claim: dict | None) -> str | None:
    """Return a skip reason if the product claim file says this WO is live."""
    if not claim:
        return None
    status = str(claim.get("status") or "").strip().lower()
    if not status or status in DONE_CLAIM_STATUSES:
        return None
    agent = str(claim.get("agent") or "").strip() or "unknown"
    if status in LIVE_CLAIM_STATUSES or "progress" in status or status == "claimed":
        return f"product claim file is {status} (agent={agent})"
    return None


def reason_from_open_pr(wo_num: int, open_pr_urls: dict[int, str] | None) -> str | None:
    if not open_pr_urls:
        return None
    url = open_pr_urls.get(wo_num)
    if url:
        return f"open PR already exists: {url}"
    return None


def _run_git(cwd: str | Path, *args: str, timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, (proc.stdout or "").strip()


def inspect_worktrees(repo_root: str | Path, wo_num: int) -> dict:
    """Describe every `.worktrees/wo-{num}-*` directory under the product clone."""
    base = Path(repo_root) / ".worktrees"
    if not base.is_dir():
        return {"exists": False, "worktrees": []}
    matches = sorted(p for p in base.glob(f"wo-{wo_num}-*") if p.is_dir())
    if not matches:
        return {"exists": False, "worktrees": []}
    details = []
    for wt in matches:
        rc_b, branch = _run_git(wt, "rev-parse", "--abbrev-ref", "HEAD")
        rc_s, porcelain = _run_git(wt, "status", "--porcelain")
        rc_a, ahead_s = _run_git(wt, "rev-list", "--count", "origin/main..HEAD")
        ahead = int(ahead_s) if rc_a == 0 and ahead_s.isdigit() else 0
        details.append({
            "path": str(wt),
            "branch": branch if rc_b == 0 else "",
            "dirty": bool(porcelain) if rc_s == 0 else True,
            "ahead": ahead,
            "git_ok": rc_b == 0,
        })
    return {"exists": True, "worktrees": details}


def reason_from_worktrees(wo_num: int, info: dict | None) -> str | None:
    if not info or not info.get("exists"):
        return None
    prefix = expected_branch_prefix(wo_num)
    for wt in info.get("worktrees") or []:
        name = Path(str(wt.get("path") or "")).name or f"wo-{wo_num}"
        branch = str(wt.get("branch") or "")
        if not wt.get("git_ok"):
            return f"worktree {name} exists but is not a readable git checkout"
        if not branch_matches_wo(branch, wo_num):
            return f"worktree {name} is on {branch or 'unknown'}, not {prefix}*"
        if wt.get("dirty"):
            return f"worktree {name} has uncommitted files"
        if int(wt.get("ahead") or 0) > 0:
            return f"worktree {name} has {wt['ahead']} commit(s) not on origin/main"
    return None


def occupancy_reason(
    *,
    wo_num: int,
    claim: dict | None = None,
    worktrees: dict | None = None,
    open_pr_urls: dict[int, str] | None = None,
    factory_status: str = "",
) -> str | None:
    """Why factory must not dispatch this WO, or None if it is free.

    If the factory already holds an active lease (`claimed` / `in_progress`),
    occupancy is the factory's own in-flight work — `/api/next` already skips
    those via dispatch_state. Do not treat that as external occupancy.
    """
    if (factory_status or "").strip().lower() in FACTORY_OWNED_STATUSES:
        return None
    pr = reason_from_open_pr(wo_num, open_pr_urls)
    if pr:
        return pr
    retrying = (factory_status or "").strip().lower() in FACTORY_RETRY_STATUSES
    if not retrying:
        claimed = reason_from_claim(claim)
        if claimed:
            return claimed
    wt = reason_from_worktrees(wo_num, worktrees)
    if not wt:
        return None
    if retrying:
        # Reclaiming factory's own tree is allowed; a worktree whose HEAD is
        # another WO's branch is not. "not a readable git checkout" is what
        # Docker sees for host worktrees (`.git` file points at a host path)
        # and must not block Retry.
        if "not wo/" in wt:
            return wt
        return None
    return wt


def git_show(repo_root: str | Path, spec: str, timeout: int = 15) -> str | None:
    """Return `git show <spec>` text, or None if the ref/path does not exist."""
    try:
        proc = subprocess.run(
            ["git", "show", spec],
            cwd=str(repo_root),
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def list_ref_files(repo_root: str | Path, ref: str, prefix: str, timeout: int = 15) -> list[str]:
    """Filenames under `prefix` at `ref` (`git ls-tree -r --name-only`)."""
    rc, out = _run_git(repo_root, "ls-tree", "-r", "--name-only", ref, "--", prefix, timeout=timeout)
    if rc != 0 or not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def read_tree_files(
    repo_root: str | Path,
    ref: str,
    prefix: str,
    *,
    name_prefix: str = "WO-",
    suffix: str = ".md",
    timeout: int = 30,
) -> dict[str, str]:
    """Read files under `prefix` at `ref` in one `git archive` process.

    Returns {basename: content}. Empty if the ref/path does not exist.
    """
    try:
        proc = subprocess.run(
            ["git", "archive", "--format=tar", ref, "--", prefix],
            cwd=str(repo_root),
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout:
        return {}
    out: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=BytesIO(proc.stdout), mode="r:") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                if not (name.startswith(name_prefix) and name.endswith(suffix)):
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                out[name] = extracted.read().decode("utf-8", errors="replace")
    except tarfile.TarError:
        return {}
    return out
