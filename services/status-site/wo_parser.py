import re
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class WOSpec:
    number: int
    title: str
    status: str
    priority: str
    effort: str
    services: str
    depends_on: list[int]
    program: str
    raw: str
    repo: str = ""
    # Set when the WO was reconstructed from a PR/branch/dispatch entry with no
    # spec file behind it — the board still has to show it, but nothing on the
    # page should imply a spec was read.
    spec_missing: bool = False
    # runtime fields set after load
    agent_name: str = ""
    agent_step: str = ""
    pr_number: int | None = None
    ci_state: str = ""
    merged_at: str = ""

    @property
    def priority_class(self) -> str:
        return {"P0": "badge-p0", "P1": "badge-p1", "P2": "badge-p2", "P3": "badge-p3"}.get(
            self.priority, "badge-p3"
        )

    @property
    def board_column(self) -> str:
        # "Planned" is acknowledged backlog — visible as open on the board.
        # Dispatch eligibility (Ready vs Planned) is enforced by the orchestrator separately.
        return classify_wo_status(self.status)

    @property
    def description(self) -> str:
        m = re.search(
            r"^## (?:Background|Summary|Description|Overview|Context|Problem)\s*\n+(.*?)(?=\n^##|\Z)",
            self.raw,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return ""
        text = m.group(1).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @property
    def sections(self) -> list[tuple[str, str]]:
        """Return (heading, body) pairs for all ## sections except the header metadata block."""
        skip = {"background", "summary", "description", "overview", "context", "problem"}
        parts = re.split(r"^(## .+)$", self.raw, flags=re.MULTILINE)
        result = []
        for i in range(1, len(parts) - 1, 2):
            heading = parts[i].lstrip("# ").strip()
            body = parts[i + 1].strip()
            if heading.lower() not in skip and body:
                result.append((heading, body))
        return result

    @property
    def age_label(self) -> str:
        return ""


def parse_wo_file(content: str, filename: str, repo: str = "") -> WOSpec | None:
    m = re.match(r"WO-(\d+)", filename)
    if not m:
        return None
    number = int(m.group(1))

    title_m = re.search(r"^# (?:WO-[\d–-]+|Work Order \d+)\s*[—:]\s*(.+)$", content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else f"WO-{number}"

    def extract(label: str) -> str:
        pat = rf"\*\*{label}:\*\*\s*(.+)"
        fm = re.search(pat, content)
        return fm.group(1).strip() if fm else ""

    status = extract("Status")
    priority = extract("Priority")
    effort = extract("Effort")
    services = extract("Services")

    depends_on: list[int] = []
    dep_m = re.search(r"\*\*Depends on:\*\*\s*(.+)", content)
    if dep_m:
        dep_text = dep_m.group(1)
        depends_on = [int(n) for n in re.findall(r"WO-(\d+)", dep_text)]

    program = extract("Program") or extract("Initiative") or ""

    return WOSpec(
        number=number,
        title=title,
        status=status,
        priority=priority,
        effort=effort,
        services=services,
        depends_on=depends_on,
        program=program,
        raw=content,
        repo=repo,
    )


def extract_wo_number_from_branch(branch_name: str) -> int | None:
    m = re.match(r"wo/(\d+)-", branch_name)
    return int(m.group(1)) if m else None


def extract_wo_number_from_pr_title(title: str) -> int | None:
    m = re.search(r"\bWO-(\d+)\b", title, re.IGNORECASE)
    return int(m.group(1)) if m else None


def resolve_wo_for_pr(pr: dict) -> int | None:
    """Resolve WO number for a PR dict; branch takes priority over title."""
    head_ref = pr.get("head", {}).get("ref", "") or ""
    n = extract_wo_number_from_branch(head_ref)
    if n is not None:
        return n
    return extract_wo_number_from_pr_title(pr.get("title", "") or "")


def resolve_all_wos_for_pr(pr: dict) -> list[int]:
    """Like resolve_wo_for_pr, but returns every WO number the PR resolves,
    not just the first. Conflict-resolution / follow-up PRs routinely
    reference two WOs in one title (e.g. "WO-1035: Resolve conflict: PR #455
    — WO-417: Coverage Consolidation") — both are genuinely done by that
    merge, but resolve_wo_for_pr's single-number contract only ever credits
    whichever one the regex matches first, silently leaving the other stuck
    looking unfinished forever.

    Kept in parity with scripts/wo_resolver.py and orchestrator/wo_resolver.py's
    copies of the same function — see tests/unit/test_wo_resolver_parity.py,
    which fails CI if any of the three drift.
    """
    head_ref = pr.get("head", {}).get("ref", "") or ""
    title = pr.get("title", "") or ""
    nums = {int(m) for m in re.findall(r"\bWO-(\d+)\b", title, re.IGNORECASE)}
    branch_n = extract_wo_number_from_branch(head_ref)
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
    branch_n = extract_wo_number_from_branch(head_ref)
    if branch_n is not None:
        nums.add(branch_n)
    for m in re.finditer(r"(?i)\bWO-(\d+)\s*[:—]", title):
        nums.add(int(m.group(1)))
    if re.search(r"(?i)\bmark(?:ed)?\b", title) and re.search(
        r"(?i)\b(?:complete|done)\b", title
    ):
        nums.update(int(x) for x in re.findall(r"(?i)\bWO-(\d+)\b", title))
    return sorted(nums)
