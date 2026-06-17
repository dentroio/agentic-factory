#!/usr/bin/env python3
"""
Memory agent — extracts lessons from a merged PR and writes them to memory/.

Runs after every merge to main. Asks Claude: "What was non-obvious or
surprising in this change that future agents should know?" Writes a memory
file only if there's something genuinely worth remembering.

Usage:
    python3 scripts/memory_agent.py \
        --diff /tmp/pr_diff.txt \
        --pr-title "feat(auth): WO-042 — add user export" \
        --pr-body "..." \
        --memory-dir memory/ \
        --output /tmp/new_memory.md

Exit codes:
    0 — always (non-blocking; memory is advisory)

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import os
import re
import sys

SYSTEM_PROMPT = """You are a memory agent for an AI engineering team. After each merged PR,
you identify lessons that future agents should know — things that were non-obvious,
surprising, or that represent project-specific invariants discovered during the change.

You write memories in one of four types:
- feedback: a rule about how to approach work (do/don't)
- project: a fact about ongoing work, decisions, or architecture
- reference: where to find something in external systems
- user: something about the human's preferences or role (rare)

Memory file format (return ONLY this, no preamble):
---
name: {{short-kebab-case-slug}}
description: {{one-line summary — used to decide relevance in future conversations}}
metadata:
  type: {{feedback|project|reference|user}}
---

{{memory body — for feedback/project types: state the rule/fact, then **Why:** and **How to apply:** lines}}

RESPONSE RULES:
- If nothing in the PR is genuinely non-obvious or surprising, respond with exactly: NOTHING_TO_REMEMBER
- Only write memories for things that would NOT be obvious to a fresh agent reading the codebase
- Do NOT write memories about what the PR did (that's in the git log)
- DO write memories about: hidden invariants, surprising constraints, non-obvious patterns,
  pitfalls discovered, decisions made for non-obvious reasons
- One memory per PR maximum. If multiple lessons exist, pick the most important.
"""

MAX_DIFF_LINES = 2000


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:50]


def next_memory_filename(memory_dir: str, slug: str) -> str:
    existing = set(os.listdir(memory_dir)) if os.path.isdir(memory_dir) else set()
    candidate = f"auto_{slug}.md"
    if candidate not in existing:
        return candidate
    for i in range(2, 100):
        candidate = f"auto_{slug}_{i}.md"
        if candidate not in existing:
            return candidate
    return f"auto_{slug}_overflow.md"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", required=True)
    parser.add_argument("--pr-title", required=True)
    parser.add_argument("--pr-body", default="")
    parser.add_argument("--memory-dir", default="memory")
    parser.add_argument("--output", required=True, help="Path to write the new memory file (or empty marker)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(0)  # Non-blocking

    with open(args.diff) as f:
        diff_lines = f.readlines()

    if len(diff_lines) > MAX_DIFF_LINES:
        diff_text = "".join(diff_lines[:MAX_DIFF_LINES])
        diff_text += f"\n\n[Diff truncated at {MAX_DIFF_LINES} lines]"
    else:
        diff_text = "".join(diff_lines)

    if not diff_text.strip():
        print("No diff — nothing to remember.")
        with open(args.output, "w") as f:
            f.write("")
        return

    user_content = f"""PR Title: {args.pr_title}

PR Description:
{args.pr_body or "(no description)"}

Merged Diff:
```diff
{diff_text}
```

What should future agents know about this change that they would NOT discover by reading the code?"""

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    result = message.content[0].text.strip()

    if result == "NOTHING_TO_REMEMBER" or not result:
        print("Memory agent: nothing noteworthy in this PR.")
        with open(args.output, "w") as f:
            f.write("")
        return

    # Write the memory file to memory_dir
    wo_match = re.search(r"WO-(\d+)", args.pr_title)
    slug_base = f"wo{wo_match.group(1)}" if wo_match else slugify(args.pr_title)
    filename = next_memory_filename(args.memory_dir, slug_base)
    memory_path = os.path.join(args.memory_dir, filename)

    os.makedirs(args.memory_dir, exist_ok=True)
    with open(memory_path, "w") as f:
        f.write(result)

    # Output file tells the workflow which file was written (for the commit step)
    with open(args.output, "w") as f:
        f.write(memory_path)

    print(f"Memory written: {memory_path}")
    print("Review and move to a named topic file if the lesson is broadly applicable.")


if __name__ == "__main__":
    main()
