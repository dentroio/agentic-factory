"""Tests for the parts of scripts/ai_review.py that decide what the gate does.

PR #194 was a 1,671-line diff. The reviewer exhausted its output budget before
emitting a `### Verdict`, so `ai_review.py` exited non-zero with a bare
truncation error and wrote no output file at all — the PR comment read "review
script failed to run" and the P1 gate blocked with no opinion attached. It
reproduced identically on rerun, so the largest changes were precisely the ones
the reviewer could never review.

These cover the two properties that has to have going forward: a large diff is
actually reviewed rather than refused, and every path that cannot review still
produces a verdict a human can act on instead of an unexplained red check.

No API calls — everything here is the pure text handling around the request.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ai_review.py"
_spec = importlib.util.spec_from_file_location("ai_review", SCRIPT)
ai_review = importlib.util.module_from_spec(_spec)
sys.modules["ai_review"] = ai_review
_spec.loader.exec_module(ai_review)


def _file_diff(path: str, body_lines: int) -> str:
    body = "".join(f"+line {i}\n" for i in range(body_lines))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n{body}"


def _review(verdict: str, checks: str = "", summary: str = "Did a thing.", suggestions: str = "None.") -> str:
    rows = checks or "| No hardcoded secrets | ✅ Pass | — |"
    return (
        f"### Summary\n{summary}\n\n"
        "### Checks\n| Check | Result | Detail |\n|-------|--------|--------|\n"
        f"{rows}\n\n"
        f"### Suggestions\n{suggestions}\n\n"
        f"### Verdict\n**{verdict}**\n"
    )


# ── Splitting ────────────────────────────────────────────────────────────────


def test_a_large_diff_is_split_instead_of_refused():
    diff = _file_diff("a.py", 900) + _file_diff("b.py", 900) + _file_diff("c.py", 900)

    chunks = ai_review.chunk_diff(diff, chunk_lines=1000)

    assert len(chunks) == 3
    assert sum(c.count("diff --git") for c in chunks) == 3


def test_chunks_never_split_a_file_across_requests():
    """Half a file's hunks is worse than no review of it — the model would flag
    phantom problems in the half it can see."""
    diff = _file_diff("small.py", 100) + _file_diff("medium.py", 300)

    for chunk in ai_review.chunk_diff(diff, chunk_lines=1000):
        for path in ("small.py", "medium.py"):
            header = f"diff --git a/{path}"
            assert chunk.count(header) in (0, 1)


def test_a_single_oversized_file_is_truncated_visibly_not_silently():
    diff = _file_diff("huge.py", 5000)

    chunks = ai_review.chunk_diff(diff, chunk_lines=1000)

    assert len(chunks) == 1
    assert "was truncated" in chunks[0]


def test_a_small_diff_still_goes_out_as_one_request():
    diff = _file_diff("a.py", 10) + _file_diff("b.py", 10)

    assert len(ai_review.chunk_diff(diff, chunk_lines=1000)) == 1


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_verdict_is_read_from_the_verdict_section_only():
    """Suggestion prose routinely contains the phrase "review required"."""
    review = _review("LGTM", suggestions="A reviewer might say Review required here.")

    assert ai_review.parse_verdict(review) == "LGTM"


def test_a_response_with_no_verdict_section_parses_as_none():
    assert ai_review.parse_verdict("### Summary\nRan out of room mid-sentence and") is None


def test_check_rows_are_parsed_without_the_header_or_separator():
    review = _review("LGTM", checks="| Type safety | ⚠️ Warning | one `any` |\n| Tests | ✅ Pass | — |")

    rows = ai_review.parse_check_rows(review)

    assert [r[0] for r in rows] == ["Type safety", "Tests"]
    assert rows[0][2] == "one `any`"


# ── Merging ──────────────────────────────────────────────────────────────────


def test_the_worst_verdict_across_chunks_wins():
    assert ai_review.worst_verdict(["LGTM", "Review required", "Needs attention"]) == "Review required"
    assert ai_review.worst_verdict(["LGTM", "Needs attention"]) == "Needs attention"
    assert ai_review.worst_verdict(["LGTM", "LGTM"]) == "LGTM"


def test_a_failure_in_a_later_chunk_is_not_washed_out_by_a_pass_in_an_earlier_one():
    """The merge is the whole risk of chunking: split the diff wrongly and a
    real ❌ gets averaged away into a green table."""
    clean = _review("LGTM", checks="| No hardcoded secrets | ✅ Pass | — |")
    dirty = _review("Review required", checks="| No hardcoded secrets | ❌ Fail | key in settings.py |")

    merged = ai_review.merge_reviews([("Chunk 1/2", clean), ("Chunk 2/2", dirty)])

    assert ai_review.parse_verdict(merged) == "Review required"
    rows = {r[0]: (r[1], r[2]) for r in ai_review.parse_check_rows(merged)}
    assert "❌" in rows["No hardcoded secrets"][0]
    assert "key in settings.py" in rows["No hardcoded secrets"][1]


def test_merging_one_chunk_returns_it_unchanged():
    single = _review("LGTM")

    assert ai_review.merge_reviews([("Review", single)]) == single


def test_merged_output_keeps_the_structure_the_workflow_posts():
    merged = ai_review.merge_reviews([("Chunk 1/2", _review("LGTM")), ("Chunk 2/2", _review("LGTM"))])

    for heading in ("### Summary", "### Checks", "### Suggestions", "### Verdict"):
        assert heading in merged


# ── Failing closed, but with something to act on ─────────────────────────────


def test_a_truncated_chunk_blocks_and_still_carries_a_verdict():
    """The regression this file exists for. Truncation used to exit 1 with no
    output; the gate blocked and the comment could only say the script
    crashed."""
    partial = "### Summary\nThe change refactors the reconciliation layer and"

    stand_in = ai_review.truncated_chunk_review("Chunk 2/3", partial)

    assert ai_review.parse_verdict(stand_in) == "Review required"
    assert "Chunk 2/3" in stand_in
    assert partial.split("\n")[-1] in stand_in


def test_a_truncated_chunk_does_not_let_the_others_pass_the_gate():
    merged = ai_review.merge_reviews([
        ("Chunk 1/2", _review("LGTM")),
        ("Chunk 2/2", ai_review.truncated_chunk_review("Chunk 2/2", "")),
    ])

    assert ai_review.parse_verdict(merged) == "Review required"


def test_the_output_budget_leaves_room_for_a_verdict():
    """A chunk is sized against the response budget, not the other way round —
    if this ratio ever inverts, truncation comes straight back."""
    assert ai_review.MAX_OUTPUT_TOKENS >= 16000
    assert ai_review.CHUNK_LINES <= ai_review.MAX_OUTPUT_TOKENS / 4
