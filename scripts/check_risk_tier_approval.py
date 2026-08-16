#!/usr/bin/env python3
"""Risk-tier approval gate (AF-01).

The ruleset's own required_approving_review_count is 0 — set higher, it
would block P2/P3's documented auto-merge-after-CI flow just as hard as it
would block an unreviewed P0/P1 merge, since GitHub rulesets apply a
required-reviewer count uniformly to every PR regardless of content. This
script is the tier-aware alternative: it reads the WO's own declared risk
tier and requires a human approval only for P0/P1, leaving P2/P3 free to
auto-merge exactly as AGENT_PROCESS.md documents.

Exit 0 (pass) when:
  - the branch isn't a WO branch (wo/NNN-slug) — hotfixes, dependency bumps,
    and anything else with no declared tier are not gated by this check
  - the resolved WO's spec declares P2 or P3
  - the resolved WO's spec declares P0/P1 AND the PR has at least one
    APPROVED review, or the `risk-tier-approved` label (GitHub forbids
    approving your own pull request, so a solo operator cannot satisfy
    the review object; the label is the explicit substitute)

Exit 1 (fail, blocks merge once registered as a required status check) when:
  - the resolved WO's spec declares P0/P1 and has neither an APPROVED
    review nor the `risk-tier-approved` label

This intentionally trusts the spec file's own Priority field — it does not
attempt to verify the declared tier matches the actual diff (that's a
separate, harder problem tracked as part of AF-17: "risk tier ... is just
text the agent writes into its own WO spec ... with no contradiction check
against the diff").
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WO_DIRS = [REPO_ROOT / "docs" / "work_orders", REPO_ROOT / "docs" / "project_management" / "work_orders"]

_BRANCH_RE = re.compile(r"wo/(\d+)-", re.IGNORECASE)
_PRIORITY_RE = re.compile(r"\*\*Priority:\*\*\s*(P[0-3])", re.IGNORECASE)
APPROVAL_LABEL = "risk-tier-approved"
_DEFAULT_LABEL_WAIT = 30.0
_DEFAULT_LABEL_POLL = 2.0


def extract_wo_number(branch: str) -> int | None:
    m = _BRANCH_RE.search(branch)
    return int(m.group(1)) if m else None


def find_spec(wo_num: int) -> Path | None:
    for wo_dir in WO_DIRS:
        if not wo_dir.is_dir():
            continue
        matches = sorted(wo_dir.glob(f"WO-{wo_num}-*.md"))
        if matches:
            return matches[0]
    return None


def parse_priority(spec_path: Path) -> str | None:
    content = spec_path.read_text(encoding="utf-8", errors="replace")
    m = _PRIORITY_RE.search(content)
    return m.group(1).upper() if m else None


def _api_get(url: str, token: str) -> list | dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def has_approval(repo: str, pr_number: int, token: str) -> bool:
    reviews = _api_get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews", token)
    # A later review from the same reviewer supersedes an earlier one (e.g. a
    # re-request after CHANGES_REQUESTED) — only the most recent state per
    # reviewer counts, matching how GitHub's own required-reviews UI behaves.
    latest_by_reviewer: dict[str, str] = {}
    for r in reviews:
        user = r.get("user", {}).get("login", "")
        state = r.get("state", "")
        if user and state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest_by_reviewer[user] = state
    return "APPROVED" in latest_by_reviewer.values()


def has_approval_label(repo: str, pr_number: int, token: str) -> bool:
    """Solo-operator substitute for APPROVED: GitHub rejects self-approvals."""
    labels = _api_get(f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels", token)
    if not isinstance(labels, list):
        return False
    return any(str(item.get("name") or "") == APPROVAL_LABEL for item in labels)


def _wait_seconds() -> float:
    raw = os.environ.get("RISK_TIER_LABEL_WAIT_SECONDS")
    return float(raw) if raw is not None else _DEFAULT_LABEL_WAIT


def _poll_seconds() -> float:
    raw = os.environ.get("RISK_TIER_LABEL_WAIT_POLL")
    return float(raw) if raw is not None else _DEFAULT_LABEL_POLL


def wait_for_human_approval(repo: str, pr_number: int, token: str) -> str | None:
    """Return 'review' or 'label' once present. Retry so opened absorbs create-then-label."""
    deadline = time.monotonic() + _wait_seconds()
    while True:
        if has_approval(repo, pr_number, token):
            return "review"
        if has_approval_label(repo, pr_number, token):
            return "label"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(_poll_seconds(), remaining))


def main() -> int:
    branch = os.environ.get("PR_HEAD_REF", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number_str = os.environ.get("PR_NUMBER", "")
    token = os.environ.get("GITHUB_TOKEN", "")

    wo_num = extract_wo_number(branch)
    if wo_num is None:
        print(f"Branch {branch!r} is not a WO branch (no wo/NNN- prefix) — not gated by this check.")
        return 0

    spec_path = find_spec(wo_num)
    if spec_path is None:
        print(f"WO-{wo_num}: no spec file found in {[str(d) for d in WO_DIRS]} — not gated by this check.")
        return 0

    priority = parse_priority(spec_path)
    if priority is None:
        print(f"WO-{wo_num}: spec {spec_path} has no parseable Priority field — not gated by this check.")
        return 0

    try:
        spec_display = spec_path.relative_to(REPO_ROOT)
    except ValueError:
        spec_display = spec_path
    print(f"WO-{wo_num}: declared priority {priority} (from {spec_display})")

    if priority not in ("P0", "P1"):
        print(f"{priority} does not require human approval — pass.")
        return 0

    if not pr_number_str or not repo or not token:
        print("::error::P0/P1 WO but PR_NUMBER/GITHUB_REPOSITORY/GITHUB_TOKEN not available to check reviews.")
        return 1

    found = wait_for_human_approval(repo, int(pr_number_str), token)
    if found == "review":
        print(f"{priority} WO has at least one APPROVED review — pass.")
        return 0
    if found == "label":
        print(f"{priority} WO has the {APPROVAL_LABEL} label — pass.")
        return 0

    print(
        f"::error::WO-{wo_num} is {priority} and requires human approval before merge — "
        f"no APPROVED review and no `{APPROVAL_LABEL}` label. "
        f"GitHub does not allow approving your own PR; add the `{APPROVAL_LABEL}` label instead."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
