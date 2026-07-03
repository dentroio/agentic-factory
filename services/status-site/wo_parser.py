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
        s = self.status.lower()
        if "done" in s or "complete" in s or "✅" in self.status:
            return "done"
        if "review" in s or "👀" in self.status:
            return "review"
        if "progress" in s or "🔄" in self.status:
            return "in_progress"
        if "blocked" in s or "🔴" in self.status or "⏸" in self.status:
            return "blocked"
        return "open"

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


def parse_wo_file(content: str, filename: str) -> WOSpec | None:
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
    )


def extract_wo_number_from_branch(branch_name: str) -> int | None:
    m = re.match(r"wo/(\d+)-", branch_name)
    return int(m.group(1)) if m else None


def extract_wo_number_from_pr_title(title: str) -> int | None:
    m = re.search(r"WO-(\d+)", title)
    return int(m.group(1)) if m else None
