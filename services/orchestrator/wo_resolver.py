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


def resolve_all_wos_for_pr(pr: dict) -> list[int]:
    """Like resolve_wo_for_pr, but returns every WO number the PR resolves,
    not just the first. Conflict-resolution / follow-up PRs routinely
    reference two WOs in one title (e.g. "WO-1035: Resolve conflict: PR #455
    — WO-417: Coverage Consolidation") — both are genuinely done by that
    merge, but resolve_wo_for_pr's single-number contract only ever credits
    whichever one the regex matches first, silently leaving the other stuck
    looking unfinished forever.

    Kept in parity with scripts/wo_resolver.py and status-site/wo_parser.py's
    copies of the same function — see tests/unit/test_wo_resolver_parity.py,
    which fails CI if any of the three drift.
    """
    head_ref = pr.get("head", {}).get("ref", "") or ""
    title = pr.get("title", "") or ""
    nums = {int(m) for m in re.findall(r"\bWO-(\d+)\b", title, re.IGNORECASE)}
    branch_n = extract_wo_from_branch(head_ref)
    if branch_n is not None:
        nums.add(branch_n)
    return sorted(nums)


_STATUS_EMOJI_RE = re.compile(
    r"^(?:✅|⏸|⛔|❌|🔴|🟡|🔄|👀|⏳|⚠(?:️)?|🔲|📋)\s*"
)
_FILING_TITLE_RE = re.compile(
    r"(?i)^(?:(?:docs|chore)(?:\([^)]+\))?:\s*(?:file|backfill|scope)\b"
    r"|WO-\d+\s*[:—]\s*backfill\b)"
)


def classify_wo_status(status: str) -> str:
    """Map a spec Status: line to a board column.

    Leading emoji is stripped before keyword checks so '⛔ Superseded'
    and '❌ Cancelled' are terminal (done), not Open/Blocked.
    """
    s = (status or "").strip().lstrip("*").strip()
    sl = s.lower()
    core = _STATUS_EMOJI_RE.sub("", sl).strip()
    if s.startswith("✅") or core.startswith((
        "done", "complete", "completed", "superseded", "abandoned",
        "cancelled", "canceled", "shipped",
    )):
        return "done"
    if s.startswith("⏸") or core.startswith("deferred"):
        return "deferred"
    if s.startswith(("👀", "⏳")) or core.startswith(("review", "in review", "awaiting")):
        return "review"
    if s.startswith("🔄") or core.startswith("in progress"):
        return "in_progress"
    if s.startswith(("🔴", "❌")) or core.startswith("blocked"):
        return "blocked"
    if s.startswith("⚠") or core.startswith("stalled"):
        return "stalled"
    return "open"


def wos_completed_by_merged_pr(pr: dict) -> list[int]:
    """WO numbers this merged PR actually completed.

    A title mention is not completion: 'docs(wo): file WO-508' and
    'docs(pm): program — WO-449–456' name WOs they did not implement.
    Completion requires a wo/NNN- branch or a 'WO-NNN:' / mark-done title.
    Spec-filing titles never complete, even on a wo/NNN- branch.
    """
    title = (pr.get("title") or "").strip()
    head_ref = (pr.get("head") or {}).get("ref", "") or ""
    if _FILING_TITLE_RE.match(title):
        return []
    nums: set[int] = set()
    branch_n = extract_wo_from_branch(head_ref)
    if branch_n is not None:
        nums.add(branch_n)
    for m in re.finditer(r"(?i)\bWO-(\d+)\s*[:—]", title):
        nums.add(int(m.group(1)))
    if re.search(r"(?i)\bmark(?:ed)?\b", title) and re.search(
        r"(?i)\b(?:complete|done)\b", title
    ):
        nums.update(int(x) for x in re.findall(r"(?i)\bWO-(\d+)\b", title))
    return sorted(nums)


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
