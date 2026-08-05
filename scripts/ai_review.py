#!/usr/bin/env python3
"""
AI code review script — generic, project-agnostic.

Reads a git diff, calls Claude with a project-appropriate system prompt,
and writes a structured markdown review to --output.

The system prompt checks for universal anti-patterns (secrets, bare excepts,
shell bypasses, type safety) plus project-specific patterns read from
PROJECT_REVIEW_CONTEXT env var or scripts/review_context.txt.

Large diffs are reviewed in chunks split on file boundaries and merged into a
single document. Before that, a diff big enough to exhaust the model's output
budget produced no review at all: the script exited non-zero with a bare
"max_tokens reached" and the gate blocked with no verdict, so the reviewer
could not review exactly the changes that most needed reviewing. See PR #194,
which failed this way twice on a 1,671-line diff.

Usage:
    python3 scripts/ai_review.py --diff /tmp/pr_diff.txt --output /tmp/review.md

Exit codes:
    0 — LGTM or Needs attention (informational — does not block merge)
    1 — Review required, or the review could not be completed (blocks merge)

The script always writes --output when it has anything to say, including when
it blocks. A blocking exit with no file is what turns a tooling problem into an
unexplained red check.

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    Add project-specific checks to scripts/review_context.txt
"""

from __future__ import annotations

import argparse
import os
import re
import sys

MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"

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

BUDGET DISCIPLINE — you have a bounded output budget and the Verdict section is the only
part the CI gate can act on. Keep the Summary to one paragraph and the Suggestions to the
highest-value items. Never let a long Suggestions section crowd out the Verdict.
"""

# Hard ceiling on diff size sent to the model at all, as cost protection. Beyond
# this the tail is dropped and the review says so explicitly rather than
# pretending it saw everything.
MAX_DIFF_LINES = int(os.getenv("AI_REVIEW_MAX_DIFF_LINES", "20000"))

# Diff lines per request. Sized so a chunk's review comfortably fits in
# MAX_OUTPUT_TOKENS with the Verdict section intact.
CHUNK_LINES = int(os.getenv("AI_REVIEW_CHUNK_LINES", "1200"))

MAX_OUTPUT_TOKENS = int(os.getenv("AI_REVIEW_MAX_TOKENS", "16000"))

VERDICTS = ("LGTM", "Needs attention", "Review required")
_VERDICT_SEVERITY = {"LGTM": 0, "Needs attention": 1, "Review required": 2}
_RESULT_SEVERITY = {"✅": 0, "⚠️": 1, "⚠": 1, "❌": 2}


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


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def split_diff_by_file(diff_text: str) -> list[str]:
    """Split a unified diff into one string per file, on `diff --git` boundaries."""
    parts: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            parts.append("".join(current))
            current = []
        current.append(line)
    if current:
        parts.append("".join(current))
    return [p for p in parts if p.strip()]


def chunk_diff(diff_text: str, chunk_lines: int = CHUNK_LINES) -> list[str]:
    """Group a diff into chunks of at most `chunk_lines`, never splitting a file.

    A single file larger than the budget gets its own chunk and is truncated
    with a visible marker — reviewing most of one file beats reviewing none of
    the PR, but the reviewer must know it saw a partial file.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for file_diff in split_diff_by_file(diff_text):
        file_len = file_diff.count("\n")
        if file_len > chunk_lines:
            if current:
                chunks.append("".join(current))
                current, current_len = [], 0
            kept = file_diff.splitlines(keepends=True)[:chunk_lines]
            omitted = file_len - chunk_lines
            chunks.append(
                "".join(kept) + f"\n[This file's diff was truncated — {omitted} more lines]\n"
            )
            continue
        if current_len + file_len > chunk_lines and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(file_diff)
        current_len += file_len

    if current:
        chunks.append("".join(current))
    return chunks or ([diff_text] if diff_text.strip() else [])


# ---------------------------------------------------------------------------
# Parsing and merging chunk reviews
# ---------------------------------------------------------------------------


def extract_section(review: str, heading: str) -> str:
    """Return the body under `### heading`, up to the next `### ` heading."""
    lines = review.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == f"### {heading}")
    except StopIteration:
        return ""
    body: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("### "):
            break
        body.append(ln)
    return "\n".join(body).strip()


def parse_verdict(review: str) -> str | None:
    """Read the verdict keyword from the `### Verdict` section only.

    Anchored to the section because suggestion prose routinely contains the
    words "review required" and would otherwise match.
    """
    section = extract_section(review, "Verdict")
    if not section:
        return None
    for line in section.splitlines():
        for verdict in ("Review required", "Needs attention", "LGTM"):
            if verdict in line:
                return verdict
    return None


def parse_check_rows(review: str) -> list[tuple[str, str, str]]:
    """Return (check, result, detail) for each data row of the Checks table."""
    rows: list[tuple[str, str, str]] = []
    for line in extract_section(review, "Checks").splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- :"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "check":
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def _result_severity(result: str) -> int:
    for symbol, severity in _RESULT_SEVERITY.items():
        if symbol in result:
            return severity
    return 0


def worst_verdict(verdicts: list[str]) -> str:
    return max(verdicts, key=lambda v: _VERDICT_SEVERITY.get(v, 2), default="Review required")


def merge_reviews(chunk_reviews: list[tuple[str, str]]) -> str:
    """Combine per-chunk reviews into one document with one verdict.

    Each check row keeps its worst result across chunks — a ❌ found in chunk 3
    cannot be washed out by a ✅ for the same check in chunk 1.
    """
    if len(chunk_reviews) == 1:
        return chunk_reviews[0][1]

    summaries: list[str] = []
    suggestions: list[str] = []
    verdicts: list[str] = []
    checks: dict[str, tuple[str, str, list[str]]] = {}
    order: list[str] = []

    for label, review in chunk_reviews:
        summary = extract_section(review, "Summary")
        if summary:
            summaries.append(f"**{label}** — {summary}")

        suggestion = extract_section(review, "Suggestions")
        if suggestion and suggestion.strip().rstrip(".").lower() != "none":
            suggestions.append(f"**{label}**\n\n{suggestion}")

        verdicts.append(parse_verdict(review) or "Review required")

        for check, result, detail in parse_check_rows(review):
            key = check.lower()
            if key not in checks:
                checks[key] = (check, result, [])
                order.append(key)
            name, worst, details = checks[key]
            if _result_severity(result) > _result_severity(worst):
                worst = result
            if detail and detail not in {"—", "-", ""} and _result_severity(result) > 0:
                details.append(f"{label}: {detail}")
            checks[key] = (name, worst, details)

    table = ["| Check | Result | Detail |", "|-------|--------|--------|"]
    for key in order:
        name, result, details = checks[key]
        table.append(f"| {name} | {result} | {'; '.join(details) if details else '—'} |")

    parts = [
        f"_Reviewed in {len(chunk_reviews)} chunks — the diff exceeds what fits in one "
        "request. Results below are merged; each check row shows the worst result found "
        "in any chunk._",
        "",
        "### Summary",
        "\n\n".join(summaries) or "No summary returned.",
        "",
        "### Checks",
        "\n".join(table),
        "",
        "### Suggestions",
        "\n\n".join(suggestions) or "None.",
        "",
        "### Verdict",
        f"**{worst_verdict(verdicts)}**",
    ]
    return "\n".join(parts) + "\n"


def truncated_chunk_review(label: str, partial: str) -> str:
    """A verdict-bearing review for a chunk whose response hit the ceiling.

    Fails closed, because an unreviewed chunk is not an endorsed one — but it
    fails closed with something a human can act on, which is the whole point.
    A bare truncation error leaves a red check and no opinion.
    """
    body = partial.strip()
    return (
        "### Summary\n"
        f"{label} exhausted the reviewer's output budget before it finished. "
        "Everything it managed to say is below; treat the rest of this chunk as unreviewed. "
        "Split the PR into smaller changes, or review these files by hand.\n\n"
        f"{body}\n\n"
        "### Checks\n"
        "| Check | Result | Detail |\n"
        "|-------|--------|--------|\n"
        f"| Review completed | ❌ Fail | {label} was truncated — no verdict from the model |\n\n"
        "### Suggestions\n"
        "Split this PR, or lower AI_REVIEW_CHUNK_LINES so each request has more room.\n\n"
        "### Verdict\n"
        "**Review required**\n"
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def review_chunk(client, system_prompt: str, user_content: str) -> tuple[str, bool]:
    """Return (text, truncated) for one review request."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = next((b.text for b in message.content if b.type == "text"), "")
    return text, message.stop_reason == "max_tokens"


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

    omitted_note = ""
    if len(lines) > MAX_DIFF_LINES:
        omitted_note = (
            f"\n\n[Diff truncated at {MAX_DIFF_LINES} lines — "
            f"{len(lines) - MAX_DIFF_LINES} lines were not sent to the reviewer]"
        )
        diff_text = "".join(lines[:MAX_DIFF_LINES])
    else:
        diff_text = "".join(lines)

    if not diff_text.strip():
        with open(args.output, "w") as f:
            f.write("### Summary\nNo source file changes detected.\n\n### Verdict\n**LGTM**\n")
        print("No diff to review.")
        return

    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "")
    system_prompt = build_system_prompt(load_project_context())

    chunks = chunk_diff(diff_text)
    print(f"Reviewing {len(lines)} diff lines in {len(chunks)} chunk(s), "
          f"max_tokens={MAX_OUTPUT_TOKENS}")

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    chunk_reviews: list[tuple[str, str]] = []
    for i, chunk in enumerate(chunks, start=1):
        label = f"Chunk {i}/{len(chunks)}" if len(chunks) > 1 else "Review"
        scope = ""
        if len(chunks) > 1:
            files = re.findall(r"^diff --git a/\S+ b/(\S+)", chunk, re.MULTILINE)
            scope = (
                f"\n\nThis is part {i} of {len(chunks)} of a larger PR. Review ONLY the files "
                f"below ({', '.join(files) or 'see diff'}); other parts are reviewed separately. "
                "Still return the full response format including a Verdict for this part."
            )

        user_content = f"""PR Title: {pr_title}

PR Description:
{pr_body or "(no description)"}
{scope}

Git Diff:
```diff
{chunk}{omitted_note if i == len(chunks) else ""}
```"""

        try:
            text, truncated = review_chunk(client, system_prompt, user_content)
        except Exception as exc:
            # A genuine API failure is not an endorsement — block, but say why
            # in the output file so the PR comment carries the reason.
            with open(args.output, "w") as f:
                f.write(
                    "### Summary\n"
                    f"The reviewer could not complete {label}: `{type(exc).__name__}: {exc}`\n\n"
                    "### Verdict\n**Review required**\n"
                )
            print(f"ERROR: review request failed on {label}: {exc}", file=sys.stderr)
            sys.exit(1)

        if truncated or parse_verdict(text) is None:
            reason = "truncated at max_tokens" if truncated else "returned no ### Verdict section"
            print(f"WARNING: {label} {reason} — recording it as blocking", file=sys.stderr)
            text = truncated_chunk_review(label, text)
        chunk_reviews.append((label, text))

    review = merge_reviews(chunk_reviews)
    if omitted_note:
        review += f"\n{omitted_note.strip()}\n"

    with open(args.output, "w") as f:
        f.write(review)
    print(f"Review written to {args.output}")

    verdict = parse_verdict(review)
    if verdict == "Review required":
        print("AI review verdict: Review required — merge blocked", file=sys.stderr)
        sys.exit(1)
    if verdict == "Needs attention":
        # Informational — does not block merge (exit 0)
        print("AI review verdict: Needs attention — review comment posted, merge can proceed")
        sys.exit(0)
    if verdict == "LGTM":
        print("AI review verdict: LGTM — merge can proceed")
        sys.exit(0)

    print("ERROR: no verdict keyword found in ### Verdict section — malformed response",
          file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
