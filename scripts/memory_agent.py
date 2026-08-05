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

MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"

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


# type -> MEMORY.md section. Deliberately not a clean 1:1 with memory_agent's
# own 4-type taxonomy: empirically, auto-extracted "project" lessons are
# almost always durable technical gotchas (a race condition, an auth
# exemption, a subprocess invariant), not epic/program tracking — "Known
# Invariants" fits their actual content far better than "Active Programs"
# would. "reference" has no dedicated section in the template; it lands here
# too rather than being silently dropped.
_SECTION_BY_TYPE = {
    "feedback": "## Feedback & Working Style",
    "user": "## Team & Collaboration",
    "project": "## Known Invariants",
    "reference": "## Known Invariants",
}


def _parse_frontmatter(memory_text: str) -> dict:
    """Extract name/description/type from a memory file's frontmatter block."""
    m = re.match(r"^---\n(.*?)\n---\n", memory_text, re.DOTALL)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("name:"):
            fm["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            fm["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("type:"):
            fm["type"] = line.split(":", 1)[1].strip()
    return fm


def append_to_memory_index(memory_dir: str, filename: str, memory_text: str) -> bool:
    """Add a one-line pointer to MEMORY.md under the right section.

    This is the fix for AF-38 (2026-08 engineering assessment): the memory
    agent wrote 14 files here across weeks and MEMORY.md — the documented
    entry point, which calls itself "Index only" — pointed at none of them,
    because the workflow relied on a human doing this by hand during PR
    review and that step was silently skipped every single time. Returns
    False (non-fatal) if MEMORY.md is missing or has no matching section,
    so a template layout change can't crash the workflow.
    """
    index_path = os.path.join(memory_dir, "MEMORY.md")
    if not os.path.isfile(index_path):
        return False

    fm = _parse_frontmatter(memory_text)
    name = fm.get("name", filename.removesuffix(".md"))
    description = fm.get("description", "")
    section = _SECTION_BY_TYPE.get(fm.get("type", ""), "## Known Invariants")
    entry = f"- [{name}]({filename}) — {description}" if description else f"- [{name}]({filename})"

    with open(index_path) as f:
        lines = f.readlines()

    try:
        start = next(i for i, l in enumerate(lines) if l.rstrip() == section)
    except StopIteration:
        return False

    # Insert after the section header (and past any HTML-comment placeholder
    # lines immediately following it), before the next "## " heading or EOF.
    insert_at = start + 1
    while insert_at < len(lines) and lines[insert_at].lstrip().startswith("<!--"):
        insert_at += 1
    lines.insert(insert_at, entry + "\n")

    with open(index_path, "w") as f:
        f.writelines(lines)
    return True


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
        model=MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text_blocks = [b.text for b in message.content if b.type == "text"]
    result = "".join(text_blocks).strip()

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

    # AF-38: this used to be a manual step during PR review ("add a MEMORY.md
    # pointer") that never actually happened across 14 real memory files —
    # do it automatically instead so the index can't silently drift again.
    indexed = append_to_memory_index(args.memory_dir, filename, result)
    if indexed:
        print(f"Indexed in {os.path.join(args.memory_dir, 'MEMORY.md')}")
    else:
        print("Could not index in MEMORY.md (missing file or section) — added the memory file only.")

    # Output file tells the workflow which file(s) were written (for the commit step)
    with open(args.output, "w") as f:
        f.write(memory_path)

    print(f"Memory written: {memory_path}")
    print("Review and move to a named topic file if the lesson is broadly applicable.")


if __name__ == "__main__":
    main()
