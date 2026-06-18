#!/usr/bin/env python3
"""
ai_review_apply.py — Apply AI code review suggestions to source files.

Called by ai-review-applier.yml when the AI code review posts a
"Needs attention" verdict. Takes the suggestions text and the PR diff,
asks Claude to produce minimal file edits that address the suggestions,
and writes the result to a JSON file.

Output JSON schema (same format as ai_fix.py):
  {
    "can_apply": bool,
    "reason": str,      # why skipped (only when can_apply=false)
    "summary": str,     # one-line description of changes made
    "changes": [
      {
        "path": str,    # relative file path from repo root
        "content": str  # full new file content
      }
    ]
  }

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
  "changes": [
    {
      "path": "relative/path/to/file.py",
      "content": "complete new file content as a string"
    }
  ]
}"""


def build_prompt(suggestions: str, diff: str, review_body: str) -> str:
    return f"""## AI Review Suggestions to Apply

{suggestions}

## Full Review Context (for understanding what was flagged)

{review_body[:3000]}

## PR Diff (the code that was reviewed)

```diff
{diff[:6000]}
```

Apply the suggestions above where clearly safe and actionable. Output only JSON."""


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
        result = {"can_apply": False, "reason": "ANTHROPIC_API_KEY not configured", "changes": []}
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

        # Strip markdown fences if model wrapped the JSON
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(raw)

        # Reject low-confidence applies
        if result.get("confidence") == "low":
            result["can_apply"] = False
            result["reason"] = "Suggestions require human judgment (confidence: low)"
            result["changes"] = []

        print(f"Apply result: can_apply={result.get('can_apply')}, files={len(result.get('changes', []))}")
        if not result.get("can_apply"):
            print(f"Reason: {result.get('reason', 'unknown')}")

    except json.JSONDecodeError as e:
        print(f"Could not parse Claude response as JSON: {e}", file=sys.stderr)
        result = {"can_apply": False, "reason": f"Invalid JSON from model: {e}", "changes": []}
    except Exception as e:
        print(f"API call failed: {e}", file=sys.stderr)
        result = {"can_apply": False, "reason": f"API error: {e}", "changes": []}

    with open(args.output_file, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
