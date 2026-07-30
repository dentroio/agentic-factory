"""Tests for scripts/api_canary.py — the text-block extraction logic itself.

The canary's real value is calling the live API (unit tests can't do that,
by definition), but the extraction function it shares with every other
script is pure logic and testable without a network call.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from api_canary import extract_text  # noqa: E402


def _message(*block_types_and_text):
    """Build a fake Anthropic message with the given (type, text) content blocks."""
    content = [SimpleNamespace(type=t, text=x) for t, x in block_types_and_text]
    return SimpleNamespace(content=content)


def test_extracts_text_when_it_is_the_only_block():
    msg = _message(("text", "OK"))
    assert extract_text(msg) == "OK"


def test_extracts_text_when_a_thinking_block_comes_first():
    """The actual bug: sonnet-5 sometimes returns ThinkingBlock as content[0]."""
    thinking_block = SimpleNamespace(type="thinking")  # no .text attribute at all
    text_block = SimpleNamespace(type="text", text="OK")
    msg = SimpleNamespace(content=[thinking_block, text_block])
    assert extract_text(msg) == "OK"


def test_raises_clearly_when_no_text_block_exists():
    msg = _message(("thinking", None))
    try:
        extract_text(msg)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "No text block" in str(e)
