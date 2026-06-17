#!/usr/bin/env python3
"""
Verifier agent — checks acceptance criteria from a WO spec against a PR diff.

Reads the WO spec linked in a PR title (WO-NNN pattern), extracts the
Acceptance Criteria section, and asks Claude whether each criterion is met
by the diff. Posts a structured report.

Usage:
    python3 scripts/verifier_agent.py \
        --wo-spec docs/project_management/work_orders/WO-042-user-export.md \
        --diff /tmp/pr_diff.txt \
        --output /tmp/verification.md

Exit codes:
    0 — all criteria met (or WO spec not found — non-blocking)
    1 — one or more criteria explicitly NOT met

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import os
import re
import sys

SYSTEM_PROMPT = """You are a verification agent. You check whether a pull request diff
satisfies the acceptance criteria listed in a Work Order specification.

For each acceptance criterion:
- Mark ✅ Met if the diff clearly implements or addresses it
- Mark ⚠️ Partial if the diff partially addresses it but has gaps
- Mark ❌ Not met if the diff does not address it at all
- Mark ➖ Not verifiable if the criterion requires runtime/manual verification

Be specific in the Detail column — cite file names and line changes.

RESPONSE FORMAT — return exactly this markdown:

### Verification Report

**WO:** {wo_title}
**Verdict:** All met / Partial / Failed

| Criterion | Status | Detail |
|-----------|--------|--------|
| criterion text | ✅ Met / ⚠️ Partial / ❌ Not met / ➖ Not verifiable | detail |

### Summary
One paragraph: overall assessment. Call out any criteria that block merge vs. those that can be addressed in a follow-up WO.

### Verdict
One of: **All criteria met** / **Partial — follow-up needed** / **Criteria not met — do not merge**
"""

MAX_DIFF_LINES = 3000


def extract_acceptance_criteria(wo_spec: str) -> str:
    match = re.search(
        r"## Acceptance Criteria\s*\n(.*?)(?=\n## |\Z)", wo_spec, re.DOTALL
    )
    if not match:
        return ""
    return match.group(1).strip()


def extract_wo_title(wo_spec: str) -> str:
    match = re.search(r"^# (WO-\d+ — .+)$", wo_spec, re.MULTILINE)
    if match:
        return match.group(1)
    return "Unknown WO"


def find_wo_spec(pr_title: str, search_dir: str = "docs/project_management/work_orders") -> str | None:
    match = re.search(r"WO-(\d+)", pr_title)
    if not match:
        return None
    wo_num = int(match.group(1))
    if not os.path.isdir(search_dir):
        return None
    for fname in os.listdir(search_dir):
        if re.match(rf"WO-{wo_num:03d}-.*\.md", fname):
            return os.path.join(search_dir, fname)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wo-spec", help="Path to WO spec (overrides auto-discovery)")
    parser.add_argument("--pr-title", default="", help="PR title (used for auto WO discovery)")
    parser.add_argument("--diff", required=True, help="Path to PR diff file")
    parser.add_argument("--output", required=True, help="Output path for verification report")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    wo_spec_path = args.wo_spec
    if not wo_spec_path and args.pr_title:
        wo_spec_path = find_wo_spec(args.pr_title)

    if not wo_spec_path or not os.path.exists(wo_spec_path):
        print("No WO spec found — skipping verification.")
        with open(args.output, "w") as f:
            f.write("### Verification Report\n\nNo linked WO spec found. Skipping verification.\n\n### Verdict\n**All criteria met** (no spec to check)\n")
        return

    with open(wo_spec_path) as f:
        wo_spec = f.read()

    criteria = extract_acceptance_criteria(wo_spec)
    if not criteria:
        print("No acceptance criteria found in WO spec — skipping.")
        with open(args.output, "w") as f:
            f.write("### Verification Report\n\nNo acceptance criteria in WO spec.\n\n### Verdict\n**All criteria met** (no criteria to check)\n")
        return

    with open(args.diff) as f:
        diff_lines = f.readlines()

    if len(diff_lines) > MAX_DIFF_LINES:
        diff_text = "".join(diff_lines[:MAX_DIFF_LINES])
        diff_text += f"\n\n[Diff truncated at {MAX_DIFF_LINES} lines]"
    else:
        diff_text = "".join(diff_lines)

    wo_title = extract_wo_title(wo_spec)

    user_content = f"""WO Spec: {wo_title}

Acceptance Criteria:
{criteria}

PR Diff:
```diff
{diff_text}
```

Check each acceptance criterion against the diff."""

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    report = message.content[0].text

    with open(args.output, "w") as f:
        f.write(report)

    print(f"Verification report written to {args.output}")

    for line in reversed(report.splitlines()):
        if "Criteria not met" in line:
            print("Verifier: criteria not met — blocking merge", file=sys.stderr)
            sys.exit(1)
        if "All criteria met" in line or "Partial" in line:
            break


if __name__ == "__main__":
    main()
