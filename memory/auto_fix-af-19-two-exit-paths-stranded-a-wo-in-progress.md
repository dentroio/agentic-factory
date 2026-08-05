---
name: runner-py-release-dispatch-on-every-early-return
description: Every early `return` in runner.py's run_wo (after checkin sets in_progress) must call release_dispatch(wo_id) — bare returns aren't caught by any safety net.
metadata:
  type: project
---

In `services/agent-runner/runner.py`, `run_wo` calls `checkin(wo_id, ...)` which marks the WO `in_progress` and claims a `MAX_PARALLEL_WOS` slot. There is no generic safety net that releases this claim on a bare `return` — only `except Exception` in `main()` catches unhandled exceptions, and that's not triggered by a normal early return. Any code path that returns early after checkin (nothing committed, PR creation failed, orchestrator rejected validation, etc.) must explicitly call `await release_dispatch(wo_id)` first, or the WO sits `in_progress` holding a slot until the stale-claim timeout, then wastes a retry attempt on a WO that was never actually broken.

Also: distinguish "the backend truly failed" from "nothing happened and control fell through" using a dedicated exception (e.g. `_AllBackendsFailed`), not a generic `RuntimeError`/log-and-return. If a helper like `_run_with_fallback` just logs and returns on total failure, callers can't tell success from