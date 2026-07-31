"""Tests for the file-overlap dispatch guard and its supporting parsers.

Mirrors orchestrator.py's _parse_depends_on / _parse_files_likely_changed /
get_next() overlap logic as standalone pure functions — orchestrator.py
can't be imported directly in unit tests due to heavy deps (apscheduler),
same convention as test_reservation.py. Keep these in sync with the real
implementation if either changes.
"""

from __future__ import annotations

import re

# ── Mirrors of orchestrator.py's parsing/overlap logic ─────────────────────


def _parse_depends_on(content: str) -> list[int]:
    m = re.search(r"\*\*Depends on:\*\*\s*([^;\n]+)", content)
    if not m:
        return []
    return [int(n) for n in re.findall(r"WO-(\d+)", m.group(1))]


def _parse_files_likely_changed(content: str) -> list[str]:
    m = re.search(r"## Files Likely Changed\s*\n(.*?)(?:\n## |\Z)", content, re.DOTALL)
    if not m:
        return []
    return re.findall(r"`([^`]+\.[a-zA-Z]+)`", m.group(1))


def _files_in_flight(dispatch_state: dict, files_by_wo: dict, active_statuses: set) -> set:
    result: set = set()
    for wo_id, entry in dispatch_state.items():
        if entry.get("status") in active_statuses - {"complete"}:
            result |= set(files_by_wo.get(wo_id, []))
    return result


ACTIVE_STATUSES = {"claimed", "in_progress", "awaiting_human", "awaiting_commit", "complete"}


# ── _parse_depends_on ───────────────────────────────────────────────────────


def test_depends_on_simple():
    content = "**Depends on:** WO-100, WO-200\n\nSome other text."
    assert _parse_depends_on(content) == [100, 200]


def test_depends_on_none_declared():
    assert _parse_depends_on("No depends line here at all.") == []


def test_depends_on_stops_before_soft_note_after_semicolon():
    """The real bug this was written for: a soft/non-blocking note sharing the
    same line as the hard dependency list must not be captured as a blocker."""
    content = (
        "**Depends on:** WO-423 (page is standalone), WO-425 (merge order in "
        "`NetworkSegments.tsx`); WO-424 should ideally land first so copy "
        "doesn't churn twice, but is not blocking."
    )
    assert _parse_depends_on(content) == [423, 425]


# ── _parse_files_likely_changed ─────────────────────────────────────────────


def test_files_likely_changed_basic_list():
    content = """## Files Likely Changed

- `frontend/src/pages/infrastructure/NetworkSegments.tsx`
- `frontend/src/lib/segmentLabels.ts`

## Notes
"""
    assert _parse_files_likely_changed(content) == [
        "frontend/src/pages/infrastructure/NetworkSegments.tsx",
        "frontend/src/lib/segmentLabels.ts",
    ]


def test_files_likely_changed_multiple_paths_per_bullet():
    content = """## Files Likely Changed

- `frontend/src/pages/infrastructure/NetworkSegments.tsx`, `EnforcementRangesWorkflow.tsx` — copy + imports

## Notes
"""
    assert _parse_files_likely_changed(content) == [
        "frontend/src/pages/infrastructure/NetworkSegments.tsx",
        "EnforcementRangesWorkflow.tsx",
    ]


def test_files_likely_changed_ignores_inline_symbol_references():
    """The edge case flagged in review: a backtick-quoted symbol name with no
    file extension (e.g. a variable/export mentioned in parens) must not be
    mistaken for a file path."""
    content = """## Files Likely Changed

- `frontend/src/lib/segmentLabels.ts` (if WO-424 landed — `ROLE_GROUPS` lives with the other metadata)
- `frontend/src/pages/infrastructure/NetworkSegments.test.tsx`

## Notes
"""
    result = _parse_files_likely_changed(content)
    assert "ROLE_GROUPS" not in result
    assert result == [
        "frontend/src/lib/segmentLabels.ts",
        "frontend/src/pages/infrastructure/NetworkSegments.test.tsx",
    ]


def test_files_likely_changed_missing_section_returns_empty():
    assert _parse_files_likely_changed("## Some Other Section\n\nNo files section here.") == []


def test_files_likely_changed_stops_at_next_heading():
    content = """## Files Likely Changed

- `a.py`

## Notes

- `b.py` should NOT be captured — it's in a different section
"""
    assert _parse_files_likely_changed(content) == ["a.py"]


# ── overlap guard ────────────────────────────────────────────────────────────


def test_overlap_detected_between_active_and_candidate():
    dispatch_state = {"WO-425": {"status": "in_progress"}}
    files_by_wo = {
        "WO-425": ["frontend/src/pages/infrastructure/NetworkSegments.tsx"],
        "WO-426": ["frontend/src/pages/infrastructure/NetworkSegments.tsx", "frontend/src/lib/segmentLabels.ts"],
    }
    in_flight = _files_in_flight(dispatch_state, files_by_wo, ACTIVE_STATUSES)
    overlap = set(files_by_wo["WO-426"]) & in_flight
    assert overlap == {"frontend/src/pages/infrastructure/NetworkSegments.tsx"}


def test_no_overlap_when_files_disjoint():
    dispatch_state = {"WO-427": {"status": "in_progress"}}
    files_by_wo = {
        "WO-427": ["frontend/src/pages/Connectors.tsx"],
        "WO-425": ["frontend/src/pages/infrastructure/NetworkSegments.tsx"],
    }
    in_flight = _files_in_flight(dispatch_state, files_by_wo, ACTIVE_STATUSES)
    overlap = set(files_by_wo["WO-425"]) & in_flight
    assert overlap == set()


def test_non_active_statuses_excluded_from_in_flight():
    """retry_queued, stale, and complete must not hold files hostage — only
    genuinely active work should block a same-file candidate."""
    dispatch_state = {
        "WO-425": {"status": "retry_queued"},
        "WO-424": {"status": "stale"},
        "WO-392": {"status": "complete"},
    }
    files_by_wo = {
        "WO-425": ["frontend/src/pages/infrastructure/NetworkSegments.tsx"],
        "WO-424": ["frontend/src/pages/Topology.tsx"],
        "WO-392": ["some/other/file.py"],
    }
    in_flight = _files_in_flight(dispatch_state, files_by_wo, ACTIVE_STATUSES)
    assert in_flight == set()


def test_wo_with_no_declared_files_never_blocks_or_is_blocked():
    dispatch_state = {"WO-427": {"status": "in_progress"}}
    files_by_wo = {"WO-427": [], "WO-999": ["frontend/src/pages/Foo.tsx"]}
    in_flight = _files_in_flight(dispatch_state, files_by_wo, ACTIVE_STATUSES)
    assert in_flight == set()
    overlap = set(files_by_wo["WO-999"]) & in_flight
    assert overlap == set()
