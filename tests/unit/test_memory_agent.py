"""Unit tests for scripts/memory_agent.py's MEMORY.md indexing (AF-38).

AF-38 in the 2026-08 engineering assessment: the memory agent wrote 14 real
lesson files across weeks, and MEMORY.md — the documented entry point,
which calls itself "Index only" — pointed at none of them, because the
workflow relied on a human adding the index pointer by hand during PR
review, and that step was silently skipped every single time. These tests
cover the fix: automatic indexing, wired into the same run that writes the
memory file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

TEMPLATE_MEMORY_MD = """# Test Project Memory

## Feedback & Working Style
<!-- Add entries when the user corrects or confirms a non-obvious approach -->
<!-- Format: [Rule](feedback_NAME.md) — one-line summary -->

## Known Invariants
<!-- Add entries for critical code patterns that must never be violated -->
<!-- Format: [Invariant name](invariant_NAME.md) — one-line rule -->

---

_Index only — keep each entry under ~150 chars. All detail lives in topic files._
"""


def _load():
    spec = importlib.util.spec_from_file_location("memory_agent", REPO_ROOT / "scripts" / "memory_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["memory_agent"] = module
    spec.loader.exec_module(module)
    return module


m = _load()


def _memory_text(name: str, description: str, mtype: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  type: {mtype}\n---\n\nBody text.\n"


def test_parse_frontmatter():
    text = _memory_text("my-lesson", "A useful description", "project")
    fm = m._parse_frontmatter(text)
    assert fm == {"name": "my-lesson", "description": "A useful description", "type": "project"}


def test_parse_frontmatter_missing_block_returns_empty():
    assert m._parse_frontmatter("no frontmatter here") == {}


@pytest.mark.parametrize(
    "mtype,expected_section",
    [
        ("feedback", "## Feedback & Working Style"),
        ("project", "## Known Invariants"),
        ("reference", "## Known Invariants"),
        ("unknown-type", "## Known Invariants"),
    ],
)
def test_append_to_memory_index_places_in_correct_section(tmp_path, mtype, expected_section):
    (tmp_path / "MEMORY.md").write_text(TEMPLATE_MEMORY_MD)
    text = _memory_text("some-lesson", "Some description", mtype)

    ok = m.append_to_memory_index(str(tmp_path), "auto_some-lesson.md", text)
    assert ok is True

    content = (tmp_path / "MEMORY.md").read_text()
    assert "[some-lesson](auto_some-lesson.md) — Some description" in content

    # Confirm it landed under the right heading, not some other one
    section_body = content.split(expected_section, 1)[1].split("##", 1)[0]
    assert "some-lesson" in section_body


def test_append_to_memory_index_missing_file_returns_false(tmp_path):
    text = _memory_text("x", "y", "project")
    ok = m.append_to_memory_index(str(tmp_path), "auto_x.md", text)
    assert ok is False


def test_append_to_memory_index_falls_back_to_filename_without_frontmatter(tmp_path):
    (tmp_path / "MEMORY.md").write_text(TEMPLATE_MEMORY_MD)
    ok = m.append_to_memory_index(str(tmp_path), "auto_no_frontmatter.md", "just some text, no frontmatter")
    assert ok is True
    content = (tmp_path / "MEMORY.md").read_text()
    assert "[auto_no_frontmatter](auto_no_frontmatter.md)" in content


def test_append_to_memory_index_is_idempotent_across_multiple_entries(tmp_path):
    """Two lessons of the same type both land under the section, oldest first."""
    (tmp_path / "MEMORY.md").write_text(TEMPLATE_MEMORY_MD)
    m.append_to_memory_index(str(tmp_path), "auto_first.md", _memory_text("first-lesson", "First", "feedback"))
    m.append_to_memory_index(str(tmp_path), "auto_second.md", _memory_text("second-lesson", "Second", "feedback"))

    content = (tmp_path / "MEMORY.md").read_text()
    assert "first-lesson" in content
    assert "second-lesson" in content
    # Most-recently-added entry inserted right after the heading, so it reads
    # newest-first — matches how a human skimming the index would expect to
    # see the latest lesson without scrolling.
    assert content.index("second-lesson") < content.index("first-lesson")
