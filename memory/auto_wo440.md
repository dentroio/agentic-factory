---
name: claude-quota-regex-fragile
description: Claude backend's quota fallback depends entirely on _QUOTA_RE matching exact wording; misses silently continue instead of falling back
metadata:
  type: project
---

The agent-runner's fallback to cursor/codex on Claude quota/session-limit exhaustion depends entirely on `_QUOTA_RE` in `services/agent-runner/backends/claude.py` matching the exact wording Claude Code emits. If a wording variant isn't covered (e.g. "you've hit your ... limit" vs "you've reached your ... limit"), the runner does NOT raise `QuotaExceededError` — it silently treats the nonzero exit as a normal completed run and proceeds straight into rebuild + quality gate on whatever half-done state existed, with no fallback to an available backend. This burned a full work-order attempt (WO-440) with zero real implementation work.

**Why:** This regex is a single point of failure for the entire quota-fallback mechanism, and Claude Code's exact session-limit wording isn't documented anywhere and can vary/change without notice.

**How to apply:** When debugging a work order that failed CI after seemingly doing no real work, check the run logs for any session/usage-limit phrasing before assuming it's a genuine implementation failure — it may be an unmatched quota message. When adding/updating quota detection, add the exact observed message string to `tests/unit/test_claude_quota_detection.py`'s `QUOTA_MESSAGES` list so future wording drift fails