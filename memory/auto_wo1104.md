---
name: reviewer-stale-pr-cleanup-canonical-branch-guard
description: agent-runner's stale-PR auto-closer must never close a PR on a canonical wo/{num}-* branch, even if dispatch marks the WO "complete"
metadata:
  type: project
---

In `services/agent-runner/reviewer.py`, `_cleanup_stale_prs()` auto-closes open PRs it believes are orphaned duplicates of an already-completed WO (based on dispatch entry `status == "complete"`). This previously caused a real bug: a canonical implementation PR on branch `wo/{N}-...` got auto-closed just because dispatch/queue state said the WO was "complete" via a different (e.g. docs "mark-done") PR.

**Why:** Dispatch/queue "complete" status is automation bookkeeping, not proof that no further legitimate work exists. A PR on the