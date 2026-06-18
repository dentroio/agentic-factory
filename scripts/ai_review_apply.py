#!/usr/bin/env python3
"""
ai_review_apply.py — Apply AI code review suggestions to source files.

Called by ai-review-applier.yml when the AI code review posts a
"Needs attention" verdict. Takes the suggestions text and the PR diff,
asks Claude to produce minimal file edits that address the suggestions,
and writes the result to a JSON file.

Output JSON schema:
  {
    "can_apply": bool,
    "reason": str,      # why skipped (only when can_apply=false)
    "summary": str,     # one-line description of changes made
    "edits": [
      {
        "path": str,        # relative file path from repo root
        "old_string": str,  # exact string to find in the file
        "new_string": str   # replacement string
      }
    ]
  }

Using search-and-replace edits (not full file content) so Claude only
touches the specific lines it changes — existing code outside the edit
is preserved regardless of what Claude saw in context.

Usage:
  python3 scripts/ai_review_apply.py \
    --diff /tmp/pr_diff.txt \
    --suggestions "..." \
    --review "..." \
    --output-file /tmp/apply_result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """You are an automated code improvement agent. An AI code reviewer
posted suggestions on a pull request. Your job is to apply those suggestions
as minimal, safe code changes.

Rules:
- Only apply suggestions that are clearly localized: type annotations, missing
  error handling at a specific call site, variable renaming, docstring additions,
  removing dead code, or adding a test for a specific function.
- Do NOT apply suggestions that:
    - Require architectural decisions (refactor X to use pattern Y)
    - Affect multiple services or change an API contract
    - Say "consider" without a clear actionable fix
    - Would change business logic
    - Are vague ("improve error handling" without specifying where)
- For each suggestion you apply, make the minimal change — no refactoring beyond
  what the suggestion specifically asks for.
- If no suggestions are safely applicable, output can_apply=false.
- Output ONLY valid JSON. No markdown fences, no explanation outside the JSON.

Output format:
{
  "can_apply": true/false,
  "reason": "why you cannot apply (only when can_apply=false)",
  "summary": "comma-separated list of what was changed (when can_apply=true)",
  "confidence": "high/medium/low",
  "edits": [
    {
      "path": "relative/path/to/file.py",
      "old_string": "exact string currently in the file (must match character-for-character)",
      "new_string": "replacement string"
    }
  ]
}

IMPORTANT — use search-and-replace edits, NOT full file content:
- old_string must be an exact substring of the current file (copy it verbatim from the diff)
- new_string replaces that exact substring
- Include enough surrounding context in old_string to make it unique (2-3 lines)
- If old_string is not found in the file, the edit is skipped safely without touching the file
- This ensures code added to main after the branch diverged is never accidentally overwritten"""


def build_prompt(suggestions: str, diff: str, review_body: str) -> str:
    return f"""## AI Review Suggestions to Apply

{suggestions}

## Full Review Context (for understanding what was flagged)

{review_body[:3000]}

## PR Diff (the code that was reviewed)

```diff
{diff[:6000]}
```

Apply the suggestions above where clearly safe and actionable. \
Use search-and-replace edits — old_string must exactly match text visible in the diff. \
Output only JSON."""


def apply_edits(edits: list[dict]) -> list[str]:
    """Apply search-and-replace edits to files. Returns list of successfully edited file paths."""
    applied = []
    for edit in edits:
        path = edit["path"]
        old_string = edit["old_string"]
        new_string = edit["new_string"]

        try:
            with open(path) as f:
                content = f.read()
        except FileNotFoundError:
            print(f"  SKIP {path}: file not found", file=sys.stderr)
            continue

        if old_string not in content:
            print(
                f"  SKIP {path}: old_string not found — Claude had stale context, "
                "file is preserved unchanged",
                file=sys.stderr,
            )
            continue

        new_content = content.replace(old_string, new_string, 1)
        with open(path, "w") as f:
            f.write(new_content)
        print(f"  APPLIED {path}")
        applied.append(path)

    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AI review suggestions to source files")
    parser.add_argument("--diff", required=True, help="Path to PR diff file")
    parser.add_argument("--suggestions", required=True, help="Suggestions text from AI review")
    parser.add_argument("--review", required=True, help="Full review comment body")
    parser.add_argument("--output-file", required=True, help="Path to write JSON result")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        result = {"can_apply": False, "reason": "ANTHROPIC_API_KEY not configured", "edits": []}
        with open(args.output_file, "w") as f:
            json.dump(result, f)
        sys.exit(0)

    try:
        with open(args.diff) as f:
            diff_text = f.read()
    except FileNotFoundError:
        diff_text = "(diff not available)"

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_prompt(args.suggestions, diff_text, args.review),
                }
            ],
        )
        raw = message.content[0].text.strip()

        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(raw)

        if result.get("confidence") == "low":
            result["can_apply"] = False
            result["reason"] = "Suggestions require human judgment (confidence: low)"
            result["edits"] = []

        if result.get("can_apply") and result.get("edits"):
            applied = apply_edits(result["edits"])
            result["applied_files"] = applied
            if not applied:
                result["can_apply"] = False
                result["reason"] = "No edits could be applied — old_string not found in any file"

        print(f"Apply result: can_apply={result.get('can_apply')}, edits={len(result.get('edits', []))}")
        if not result.get("can_apply"):
            print(f"Reason: {result.get('reason', 'unknown')}")

    except json.JSONDecodeError as e:
        print(f"Could not parse Claude response as JSON: {e}", file=sys.stderr)
        result = {"can_apply": False, "reason": f"Invalid JSON from model: {e}", "edits": []}
    except Exception as e:
        print(f"API call failed: {e}", file=sys.stderr)
        result = {"can_apply": False, "reason": f"API error: {e}", "edits": []}

    with open(args.output_file, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
