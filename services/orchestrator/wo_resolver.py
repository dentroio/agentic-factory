"""Single source for WO ID normalization, spec/claim path resolution, and PR WO extraction."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_WO_DIR = Path("docs/work_orders")
DEFAULT_RUNS_DIR = Path("docs/factory/runs")

_WO_NUM_RE = re.compile(r"\bWO-(\d+)\b", re.IGNORECASE)
_BRANCH_RE = re.compile(r"wo/(\d+)-", re.IGNORECASE)


def normalize_wo_id(raw: str) -> str:
    """Normalize to canonical WO-NNN (uppercase, single WO- prefix).

    Examples:
        wo-1035 -> WO-1035
        WO-WO-1035 -> WO-1035
    """
    wo_id = (raw or "").strip()
    if not wo_id:
        raise ValueError("empty WO id")

    wo_upper = wo_id.upper()
    if not wo_upper.startswith("WO-"):
        wo_id = f"WO-{wo_id.lstrip('-')}"
    else:
        wo_id = wo_upper

    while wo_id.startswith("WO-WO-"):
        wo_id = "WO-" + wo_id[6:]

    num_part = wo_id[3:]
    if not num_part.isdigit():
        raise ValueError(f"invalid WO id: {raw!r}")
    return wo_id


def parse_wo_number(text: str) -> int | None:
    """Extract the first WO number from branch names, PR titles, or filenames."""
    if not text:
        return None
    m = _WO_NUM_RE.search(text)
    return int(m.group(1)) if m else None


def parse_wo_number_from_branch(branch: str) -> int | None:
    """Extract WO number from a branch like refs/heads/wo/1035-slug."""
    if not branch:
        return None
    m = _BRANCH_RE.search(branch)
    return int(m.group(1)) if m else None


def wo_number_from_id(wo_id: str) -> int:
    return int(normalize_wo_id(wo_id)[3:])


def extract_wo_from_branch(branch: str) -> int | None:
    """Extract WO number from branch name (e.g. 'wo/1041-slug' -> 1041)."""
    if not branch:
        return None
    m = re.match(r"wo/(\d+)-", branch)
    return int(m.group(1)) if m else None


def extract_wo_from_title(title: str) -> int | None:
    """Extract WO number from a PR title using word-boundary matching."""
    if not title:
        return None
    m = re.search(r"\bWO-(\d+)\b", title, re.IGNORECASE)
    return int(m.group(1)) if m else None


def resolve_wo_for_pr(pr: dict) -> int | None:
    """
    Resolve the WO number for a PR dict.

    Precedence:
    1. Branch name: wo/NNN- pattern (authoritative — the branch is the WO's home)
    2. PR title: WO-NNN as fallback

    Returns None if no WO can be identified.
    """
    n, _ = resolve_wo_for_pr_with_source(pr)
    return n


def resolve_wo_for_pr_with_source(pr: dict) -> tuple[int | None, str | None]:
    """
    Like resolve_wo_for_pr but also returns the resolution source.

    Returns (wo_num, source) where source is "branch", "title", or None.
    Only "branch" is safe for destructive actions (auto-complete, ghost cleanup).
    """
    head_ref = pr.get("head", {}).get("ref", "") or ""
    n = extract_wo_from_branch(head_ref)
    if n is not None:
        return n, "branch"
    n = extract_wo_from_title(pr.get("title", "") or "")
    if n is not None:
        return n, "title"
    return None, None


def spec_glob_pattern(wo_num: int) -> str:
    return f"WO-{wo_num}-*.md"


def find_spec_path(
    wo_num: int,
    *,
    wo_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path | None:
    """Return the first matching WO spec markdown file, or None."""
    base = (repo_root or Path.cwd()).resolve()
    directory = base / (wo_dir or DEFAULT_WO_DIR)
    if not directory.is_dir():
        return None
    matches = sorted(directory.glob(spec_glob_pattern(wo_num)))
    return matches[0] if matches else None


def find_claim_path(
    wo_num: int,
    *,
    runs_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    base = (repo_root or Path.cwd()).resolve()
    return base / (runs_dir or DEFAULT_RUNS_DIR) / f"WO-{wo_num}.json"


def branch_name_for(wo_num: int, slug: str) -> str:
    """Build wo/NNN-slug branch name from WO number and slug."""
    clean = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:40].rstrip("-")
    return f"wo/{wo_num}-{clean}"
