---
name: wo-resolution-source-safety-invariant
description: WO resolution from PR title is never safe for destructive auto-actions; only branch-corroborated matches may trigger auto-complete or ghost cleanup
metadata:
  type: project
---

The project has an explicit safety tier for WO resolution: `resolve_wo_for_pr_with_source()` returns `(wo_num, "branch")` or `(wo_num, "title")`, and **only `"branch"` sources are permitted to trigger destructive or irreversible automation** (WO auto-complete, ghost escalation to `status=ghost`). Title-only matches must log a warning and take no action.

This is not just a code style choice — it exists because PR titles frequently reference *old or related* WOs (e.g. "Fix regression from WO-410") that are unrelated to the actual work in that PR. Auto-completing the wrong WO based on a title mention caused or risked silent data loss in dispatch state.

**Why:** The branch name (`wo/NNN-slug`) is an authoritative, structured signal set by the agent opening the PR. The title is free-form and often mentions WO numbers incidentally.

**How to apply:**
- Any new code path that calls `resolve_wo_for_pr` for a destructive purpose (completing, rejecting, archiving, ghost-escalating a WO) must switch to `resolve_wo_for_pr_with_source` and gate on `src == "branch"`.
- `resolve_wo_for_pr` (source-blind) is only safe for read-only / advisory uses.
- The override tombstone (`/api/wos/{wo_id}/override` with `action: "no-auto-complete"`) provides a human escape hatch when even a branch-corroborated match should not auto-complete; always check `_is_overridden(wo_id, "no-auto-complete")` before completing.