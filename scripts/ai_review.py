#!/usr/bin/env python3
"""
AI code review script — generic, project-agnostic.

Reads a git diff, calls Claude with a project-appropriate system prompt,
and writes a structured markdown review to --output.

The system prompt checks for universal anti-patterns (secrets, bare excepts,
shell bypasses, type safety) plus project-specific patterns read from
PROJECT_REVIEW_CONTEXT env var or scripts/review_context.txt.

Usage:
    python3 scripts/ai_review.py --diff /tmp/pr_diff.txt --output /tmp/review.md

Exit codes:
    0 — LGTM or Needs attention (informational — does not block merge)
    1 — Review required (blocks merge via CI)

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    Add project-specific checks to scripts/review_context.txt
"""

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Universal checks applied to every project
# ---------------------------------------------------------------------------

UNIVERSAL_CHECKS = """
UNIVERSAL CHECKS (always apply these regardless of project):

1. Hardcoded secrets — API keys, passwords, tokens, private keys must never appear in code.
   They belong in environment variables or a secrets manager.

2. Shell || true bypasses — `|| true` silences failures. Flag every instance in CI scripts
   and Makefiles. Broken steps must be visible, not hidden.

3. Bare exception handling — `except:` or `except Exception: pass` swallows errors silently.
   Flag these — use specific exception types and always log or re-raise.

4. Type safety — `any` in TypeScript, untyped function parameters in Python without clear
   justification. Flag new occurrences.

5. SQL injection — string-interpolated SQL queries. Parameters must use placeholders (%s, ?, $1).

6. Missing error handling at system boundaries — external API calls, file I/O, DB writes
   should handle failures, not assume success.

7. Test coverage blind spots — new business logic added without a corresponding test.
   Flag when tests are absent for non-trivial code.
"""

# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------

RESPONSE_FORMAT = """
RESPONSE FORMAT — return exactly this markdown structure:

### Summary
One paragraph: what the change does, overall quality, patterns that stand out.

### Checks
| Check | Result | Detail |
|-------|--------|--------|
| No hardcoded secrets | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| No shell || true bypasses | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| No bare except / swallowed errors | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| Type safety | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| No SQL injection | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| Error handling at boundaries | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
| Test coverage | ✅ Pass / ⚠️ Warning / ❌ Fail | detail or — |
[Add project-specific check rows here when PROJECT_REVIEW_CONTEXT is provided]

### Suggestions
Inline suggestions, or "None." if there are none.

### Verdict
One of: **LGTM** / **Needs attention** / **Review required**

**LGTM** — No ❌ failures. Use this even when ⚠️ warnings exist, as long as the warnings
are minor style or typing concerns that do not affect correctness, security, or critical
patterns. Suggestions are informational. LGTM means: safe to merge.

**Needs attention** — Use ONLY when a ⚠️ warning describes something that materially affects
correctness, security, data integrity, or a project-critical pattern. Do NOT use for TypeScript
typing style, documentation gaps, refactor suggestions, or DRY improvements. Ask: "would
merging this cause a real problem?" If no — use LGTM with a note. If yes — use Needs attention.

**Review required** — Any ❌ failure in the Checks table. Merge is blocked.
"""

MAX_DIFF_LINES = 4000


def build_system_prompt(project_context: str | None) -> str:
    project_section = ""
    if project_context and project_context.strip():
        project_section = f"""
PROJECT-SPECIFIC CHECKS:
{project_context.strip()}

Apply these in addition to the universal checks above. Add rows for each
project-specific check to the Checks table in your response.
"""
    return f"""You are a code reviewer. Review the PR diff for quality and correctness.
{UNIVERSAL_CHECKS}
{project_section}
{RESPONSE_FORMAT}"""


def load_project_context() -> str | None:
    # 1. Environment variable (set by CI from a secret or repo var)
    ctx = os.environ.get("PROJECT_REVIEW_CONTEXT", "").strip()
    if ctx:
        return ctx
    # 2. File in the repo (committed, project-specific)
    ctx_file = os.path.join(os.path.dirname(__file__), "review_context.txt")
    if os.path.exists(ctx_file):
        with open(ctx_file) as f:
            return f.read().strip()
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    with open(args.diff) as f:
        lines = f.readlines()

    if len(lines) > MAX_DIFF_LINES:
        diff_text = "".join(lines[:MAX_DIFF_LINES])
        diff_text += f"\n\n[Diff truncated at {MAX_DIFF_LINES} lines — {len(lines) - MAX_DIFF_LINES} lines omitted]"
    else:
        diff_text = "".join(lines)

    if not diff_text.strip():
        with open(args.output, "w") as f:
            f.write("### Summary\nNo source file changes detected.\n\n### Verdict\n**LGTM**\n")
        print("No diff to review.")
        return

    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "")
    project_context = load_project_context()
    system_prompt = build_system_prompt(project_context)

    user_content = f"""PR Title: {pr_title}

PR Description:
{pr_body or "(no description)"}

Git Diff:
```diff
{diff_text}
```"""

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    # If Claude hit the token limit the response is truncated — ### Verdict will be missing.
    if message.stop_reason == "max_tokens":
        print("ERROR: review response was truncated (max_tokens reached) — ### Verdict section missing", file=sys.stderr)
        print("The diff may be too large. Increase MAX_DIFF_LINES or max_tokens in ai_review.py.", file=sys.stderr)
        sys.exit(1)

    review = message.content[0].text

    with open(args.output, "w") as f:
        f.write(review)

    print(f"Review written to {args.output}")

    # Anchor search to the "### Verdict" section — suggestion text can contain verdict
    # keywords and would cause a false match if we searched the full document.
    lines_out = review.splitlines()
    try:
        verdict_start = next(i for i, ln in enumerate(lines_out) if ln.strip() == "### Verdict")
        verdict_lines = lines_out[verdict_start:]
    except StopIteration:
        print("ERROR: ### Verdict section not found in review output — malformed response", file=sys.stderr)
        sys.exit(1)

    for line in verdict_lines:
        if "Review required" in line:
            print("AI review verdict: Review required — merge blocked", file=sys.stderr)
            sys.exit(1)
        if "Needs attention" in line:
            # Informational — does not block merge (exit 0)
            print("AI review verdict: Needs attention — review comment posted, merge can proceed")
            sys.exit(0)
        if "LGTM" in line:
            print("AI review verdict: LGTM — merge can proceed")
            sys.exit(0)

    print("ERROR: no verdict keyword found in ### Verdict section — malformed response", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
