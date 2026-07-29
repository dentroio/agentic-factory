"""Tests for scripts/doc_writer.py — Claude response parsing.

Regression coverage for the bug where doc-writer skipped every page: Claude
often wraps its markdown response in a ```/```markdown fence despite the
system prompt saying not to, so `updated.startswith("---")` was always False.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from doc_writer import parse_frontmatter, strip_code_fence  # noqa: E402


def test_strip_code_fence_removes_markdown_fence():
    raw = "```markdown\n---\ntitle: Foo\n---\n\nBody text.\n```"
    assert strip_code_fence(raw) == "---\ntitle: Foo\n---\n\nBody text."


def test_strip_code_fence_removes_bare_fence():
    raw = "```\n---\ntitle: Foo\n---\n\nBody text.\n```"
    assert strip_code_fence(raw) == "---\ntitle: Foo\n---\n\nBody text."


def test_strip_code_fence_leaves_unfenced_content_untouched():
    raw = "---\ntitle: Foo\n---\n\nBody text."
    assert strip_code_fence(raw) == raw


def test_strip_code_fence_strips_surrounding_whitespace():
    raw = "\n\n```markdown\n---\ntitle: Foo\n---\n\nBody.\n```\n\n"
    assert strip_code_fence(raw) == "---\ntitle: Foo\n---\n\nBody."


def test_fenced_response_parses_as_valid_frontmatter_after_stripping():
    raw = "```markdown\n---\ntitle: Foo\ncovers_wos:\n  - WO-1\n---\n\nBody.\n```"
    fm, body = parse_frontmatter(strip_code_fence(raw))
    assert fm["title"] == "Foo"
    assert body.strip() == "Body."
