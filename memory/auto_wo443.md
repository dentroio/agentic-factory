---
name: ci-local-timeout-contention-recurring
description: quality_gate.py's _CI_RUN_TIMEOUT/_CI_LOCK_TIMEOUT bumps are symptom fixes, not root-cause fixes — expect recurrence under host contention
metadata:
  type: project
---

`_CI_RUN_TIMEOUT`/`_CI_LOCK_TIMEOUT` in `services/agent-runner/quality_gate.py` have been raised at least twice (1800s → 2700s in WO-443) because concurrent agents/worktrees rebuilding containers simultaneously push host load average past 45, causing `make ci-local` to blow through even generously-padded (2x worst-observed) timeouts.

**Why:** The actual bug is unbounded concurrency of heavy builds across worktrees, not the timeout value itself. Bumping the timeout only buys headroom until the next contention spike; it doesn't fix the underlying issue. There's tracked work (see `occupancy.py`) intended to add real concurrency/capacity control.

**How to apply:** If a WO/PR hits "make timed out after Ns" and the fix under discussion is "just raise the timeout," treat that as a temporary patch — note in the PR/lesson that root cause is unaddressed. Don't silently shrink these timeouts back down (there's a regression test enforcing `_CI_RUN_TIMEOUT > 1800`). If this recurs a third time, push for the concurrency-control fix (occupancy.py) rather than another