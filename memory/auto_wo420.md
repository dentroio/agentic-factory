---
name: concurrency-cap-only-counts-resource-holding-states
description: MAX_PARALLEL_WOS capacity check in orchestrator must count only claimed/in_progress, not all active_statuses
metadata:
  type: project
---

In `services/orchestrator/orchestrator.py`'s `/api/next` handler, `MAX_PARALLEL_WOS` exists specifically to protect the shared CI lock and Docker containers from overload — it is NOT a general "how many WOs are in flight" limiter. Only `claimed` and `in_progress` dispatch statuses actually touch those shared resources. Other non-complete statuses (`awaiting_human`, `awaiting_commit`, etc.) represent WOs idling on human review and consume zero CI/container resources.

The broader `active_statuses` set is still correct and used elsewhere in the same function (skip-already-claimed checks, file-conflict tracking) — those legitimately should include `awaiting_human` etc. Do not "simplify" by reusing `active_statuses - {"complete"}` for the capacity check.

**Why:** Using the broad status set for capacity counting caused a real incident: 3 WOs simultaneously parked in `awaiting_human` fully occupied the cap and blocked all new dispatch, even though nothing was contending for CI/containers.

**How to apply:** When touching WO capacity/concurrency logic, first ask what resource the cap is protecting, then hardcode the exact statuses that hold that resource rather than reusing a general "active" status set.