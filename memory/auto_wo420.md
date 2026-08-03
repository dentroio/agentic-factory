---
name: orchestrator-max-retry-notify-reachable-paths
description: Exhaustion detection must live in /api/dispatch/{wo}/retry and the stale-claim sweep, not in /api/claim, because /api/next filters out WOs at MAX_RETRY_ATTEMPTS
metadata:
  type: project
---

In services/orchestrator/orchestrator.py, `/api/next`'s queue filter deliberately skips any WO with `attempt_count >= MAX_RETRY_ATTEMPTS` (so an exhausted WO doesn't stay the top recommendation forever). This makes `/api/claim` unreachable for an already-exhausted WO — no runner will ever call claim for it again.

**Why:** A max-retry notification block that lives inside `/api/claim` looks correct but is dead code for