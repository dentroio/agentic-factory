---
name: avoid-fixed-dates-in-rolling-window-tests
description: Tests for status-site's merged-PR rolling window must use relative timestamps, not fixed calendar dates
metadata:
  type: feedback
---

Tests covering the status-site's 56-day rolling merged-PR window (`tests/unit/test_merged_pr_window.py`) must generate fixture timestamps relative to "now" (e.g. `datetime.now(UTC) - timedelta(days=1)`), not hardcoded calendar dates. A fixed date like `"2026-08-01T00:00:00Z"` silently ages out of the window as real time passes and causes tests to start failing out of nowhere months later, with no code change to blame.

**Why:** The filter under test compares merged_at against a rolling cutoff (now - 56 days), so any fixture date eventually falls outside the window and gets dropped, breaking the assertion. This already happened once (PR #451) and will recur if new fixtures reintroduce fixed dates.

**How to apply:** When adding/editing tests in this file (or similar rolling-window logic elsewhere), use a helper like `_recently_merged()` that computes a timestamp relative to `datetime.now(UTC)` rather than a literal date string. If you see a fixed date in such a fixture, flag it as a time bomb and replace it.