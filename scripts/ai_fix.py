#!/usr/bin/env python3
"""
ai_fix.py — Claude-powered CI failure auto-fixer

Called by ci-auto-fix.yml when CI fails on an agent PR.
Takes the failure log and the PR diff, asks Claude for a minimal fix,
writes the result to a JSON file that the workflow uses to apply changes.

Output JSON schema:
  {
    "can_fix": bool,
    "reason": str,          # why fix was skipped (only when can_fix=false)
    "summary": str,         # one-line description of the fix
    "changes": [
      {
        "path": str,        # relative file path from repo root
        "content": str      # full new file content (not a patch)
      }
    ]
  }

Usage:
  python3 scripts/ai_fix.py \
    --log-excerpt "<failure output>" \
    --diff "<git diff output>" \
    --output-file /tmp/ai_fix_result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """You are an automated CI fix agent. A CI run failed on a pull request.
Your job is to analyze the failure and produce a minimal, safe fix.

Rules:
- Only fix test files, linting issues, or trivial import/mock errors
- Never change production logic, business rules, or API contracts
- Never add new tests that don't test real behavior
- If the failure requires understanding business logic, output can_fix=false
- If multiple service files need changing, output can_fix=false
- Maximum 3 files changed
- Output ONLY valid JSON — no markdown, no explanation outside the JSON

Output format (JSON only):
{
  "can_fix": true/false,
  "reason": "why you cannot fix (only when can_fix=false)",
  "summary": "one-line description of the fix (when can_fix=true)",
  "confidence": "high/medium/low",
  "changes": [
    {
      "path": "relative/path/to/file.py",
      "content": "complete new file content as a string"
    }
  ]
}

Do not fix the failure if:
- confidence is low
- The fix requires changing production code logic
- The failure is a build failure (import errors in main code, missing deps)
- The diff changes >10 files (too complex to reason about safely)
- The failure is in a migration file
"""


def build_user_prompt(log_excerpt: str, diff: str) -> str:
    return f"""CI failed on this pull request. Here is what you have to work with:

## PR Diff (what the agent changed)

```diff
{diff[:6000]}
```

## Failure Log

```
{log_excerpt[:4000]}
```

Analyze the failure and the diff. If you can produce a safe, minimal fix, output the JSON with can_fix=true and the file changes. If not, output can_fix=false with a reason.

Remember: output ONLY valid JSON. No markdown wrapping."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude-powered CI failure fixer")
    parser.add_argument("--log-excerpt", required=True, help="CI failure log excerpt")
    parser.add_argument("--diff", required=True, help="PR diff text")
    parser.add_argument("--output-file", required=True, help="Path to write JSON result")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        result = {"can_fix": False, "reason": "ANTHROPIC_API_KEY not configured", "changes": []}
        with open(args.output_file, "w") as f:
            json.dump(result, f)
        sys.exit(0)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_user_prompt(args.log_excerpt, args.diff),
                }
            ],
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if model wrapped the JSON anyway
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        result = json.loads(raw)

        # Safety check: reject low-confidence fixes
        if result.get("confidence") == "low":
            result["can_fix"] = False
            result["reason"] = "Auto-fix skipped: confidence is low — needs human review"
            result["changes"] = []

        print(f"Claude result: can_fix={result.get('can_fix')}, files={len(result.get('changes', []))}")
        if not result.get("can_fix"):
            print(f"Reason: {result.get('reason', 'unknown')}")

    except json.JSONDecodeError as e:
        print(f"Could not parse Claude response as JSON: {e}", file=sys.stderr)
        result = {"can_fix": False, "reason": f"Invalid JSON from Claude: {e}", "changes": []}
    except Exception as e:
        print(f"Claude API call failed: {e}", file=sys.stderr)
        result = {"can_fix": False, "reason": f"API error: {e}", "changes": []}

    with open(args.output_file, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
