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
- If old_string is not found, the edit will fail safely without touching the file

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

Analyze the failure and the diff. If you can produce a safe, minimal fix, output the JSON \
with can_fix=true and search-and-replace edits. old_string must exactly match text visible \
in the diff above. If not, output can_fix=false with a reason.

Remember: output ONLY valid JSON. No markdown wrapping."""


def apply_edits(edits: list[dict]) -> list[str]:
    """Apply search-and-replace edits to files. Returns list of applied file paths."""
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
            print(f"  SKIP {path}: old_string not found in file (Claude had stale context)", file=sys.stderr)
            continue

        new_content = content.replace(old_string, new_string, 1)
        with open(path, "w") as f:
            f.write(new_content)
        print(f"  APPLIED {path}")
        applied.append(path)

    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude-powered CI failure fixer")
    parser.add_argument("--log-excerpt", required=True, help="CI failure log excerpt")
    parser.add_argument("--diff", required=True, help="PR diff text")
    parser.add_argument("--output-file", required=True, help="Path to write JSON result")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        result = {"can_fix": False, "reason": "ANTHROPIC_API_KEY not configured", "edits": []}
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

        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(raw)

        if result.get("confidence") == "low":
            result["can_fix"] = False
            result["reason"] = "Auto-fix skipped: confidence is low — needs human review"
            result["edits"] = []

        if result.get("can_fix") and result.get("edits"):
            applied = apply_edits(result["edits"])
            result["applied_files"] = applied
            if not applied:
                result["can_fix"] = False
                result["reason"] = "No edits could be applied — old_string not found in any file"

        print(f"Claude result: can_fix={result.get('can_fix')}, edits={len(result.get('edits', []))}")
        if not result.get("can_fix"):
            print(f"Reason: {result.get('reason', 'unknown')}")

    except json.JSONDecodeError as e:
        print(f"Could not parse Claude response as JSON: {e}", file=sys.stderr)
        result = {"can_fix": False, "reason": f"Invalid JSON from Claude: {e}", "edits": []}
    except Exception as e:
        print(f"Claude API call failed: {e}", file=sys.stderr)
        result = {"can_fix": False, "reason": f"API error: {e}", "edits": []}

    with open(args.output_file, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
