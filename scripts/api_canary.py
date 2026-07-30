#!/usr/bin/env python3
"""
API canary — proves the real Anthropic API call + response-parsing path still
works, cheaply, on a schedule.

Unit tests never call the real API (they mock it), so they can't catch the
class of bug this exists for: on 2026-07-30, switching the default model to
claude-sonnet-5 broke every script's `message.content[0].text` extraction —
sonnet-5 sometimes returns a ThinkingBlock as content[0], which has no .text
attribute — and that went undetected until a real PR happened to exercise it.
49/49 unit tests stayed green the whole time.

This makes the same real API call and runs the same extraction logic every
other script here uses, with a minimal prompt so it costs a fraction of a
cent. Exit 0 on success, exit 1 (with a clear message) on any failure —
plugs directly into automation-watchdog.yml, no separate alerting needed.

Usage:
    python3 scripts/api_canary.py

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
"""

from __future__ import annotations

import os
import sys

MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"


def extract_text(message) -> str:
    """The exact pattern every script here uses — the thing that broke."""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise ValueError(
        f"No text block in response — content types were: "
        f"{[getattr(b, 'type', type(b).__name__) for b in message.content]}"
    )


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with exactly the word OK and nothing else."}],
        )
    except Exception as e:
        print(f"ERROR: API call failed for model={MODEL}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        text = extract_text(message)
    except Exception as e:
        print(f"ERROR: could not extract text from response (model={MODEL}): {e}", file=sys.stderr)
        sys.exit(1)

    if "ok" not in text.strip().lower():
        print(f"ERROR: unexpected response content for model={MODEL}: {text!r}", file=sys.stderr)
        sys.exit(1)

    print(f"OK — model={MODEL}, response parsed correctly: {text!r}")


if __name__ == "__main__":
    main()
