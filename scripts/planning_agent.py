#!/usr/bin/env python3
"""
Planning agent — converts a problem statement (GitHub issue) into a WO spec.

Reads an issue title + body, calls Claude, writes a filled WO-000-template.md
to --output. Run manually or triggered by the planning-agent.yml workflow when
an issue is labeled 'new-wo'.

Usage:
    python3 scripts/planning_agent.py \
        --title "Feature: user CSV export" \
        --body "Users need to download their data..." \
        --next-wo-num 042 \
        --output docs/project_management/work_orders/WO-042-user-csv-export.md

Exit codes:
    0 — WO spec written
    1 — error (missing key, bad input)

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    Add project context to scripts/review_context.txt (same file as ai_review.py uses)
"""

import argparse
import os
import re
import sys

SYSTEM_PROMPT = """You are a software engineering planning agent. You convert problem statements
into structured Work Order (WO) specifications that AI agents can execute.

A good WO spec has:
- A clear Problem (symptoms, not solutions)
- A Goal (what "done" looks like from the user's perspective)
- Scope (in/out of scope, explicitly stated)
- Approach (technical plan with file names, not vague)
- Acceptance Criteria (verifiable checklist items, not vague)
- Verification Steps (runnable commands)
- An Execution section (branch name, risk tier, PR title, files to touch)

Risk tier rules:
- P0: auth, security, data loss risk → human merges
- P1: core features, schema changes → human merges
- P2: additive features, tests, docs → auto-merge allowed
- P3: docs/PM files only → commit directly to main

Return ONLY the filled WO spec in markdown. No preamble, no explanation.
"""

WO_TEMPLATE = """\
# WO-{num:03d} — {title}

**Status:** 🔵 Open
**Priority:** {priority}
**Assigned:** Agent
**Target:** {{YYYY-MM-DD}}
**Depends on:** —

---

## Problem

{problem}

## Goal

{goal}

## Scope

**In scope:**
{in_scope}

**Out of scope:**
{out_of_scope}

## Approach

{approach}

## Acceptance Criteria

{acceptance_criteria}

## Verification Steps

```bash
{verification_steps}
```

---

## Execution

> This section is read by agents before starting implementation.

**Branch:** `wo/{num:03d}-{branch_slug}`
**Risk tier:** {priority}
**PR title:** `{commit_type}({scope}): WO-{num:03d} — {title}`
**Auto-merge:** {auto_merge}

**PM docs to update after merge:**
- `docs/project_management/PROGRESS.md` — mark WO-{num:03d} complete
- `docs/project_management/CAPABILITY_STATUS.md` — update affected capability row (if applicable)

**Files to touch (estimated):**
{files_to_touch}

**Key constraints:**
{key_constraints}

---

## Notes / Context

{notes}
"""

USER_TEMPLATE = """\
Convert this problem statement into a WO spec.

WO number: {num:03d}
Issue title: {title}
Issue body:
{body}

Project context:
{project_context}

Fill in every section of the WO spec. Be specific about file paths and technical approach.
If you cannot determine the right risk tier from the description, default to P1 (human merge).
"""


def load_project_context() -> str:
    ctx = os.environ.get("PROJECT_REVIEW_CONTEXT", "").strip()
    if ctx:
        return ctx
    ctx_file = os.path.join(os.path.dirname(__file__), "review_context.txt")
    if os.path.exists(ctx_file):
        with open(ctx_file) as f:
            return f.read().strip()
    return "(no project-specific context configured)"


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="Issue/feature title")
    parser.add_argument("--body", required=True, help="Issue body / problem description")
    parser.add_argument("--next-wo-num", required=True, type=int, help="WO number to assign")
    parser.add_argument("--output", required=True, help="Output path for the WO spec")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    project_context = load_project_context()

    user_content = USER_TEMPLATE.format(
        num=args.next_wo_num,
        title=args.title,
        body=args.body or "(no body provided)",
        project_context=project_context,
    )

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    wo_spec = message.content[0].text

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(wo_spec)

    print(f"WO-{args.next_wo_num:03d} spec written to {args.output}")
    print(f"Review and adjust before merging — particularly risk tier and acceptance criteria.")


if __name__ == "__main__":
    main()
