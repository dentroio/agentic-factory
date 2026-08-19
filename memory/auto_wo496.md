---
name: subprocess-wrapper-timeouts-must-exceed-inner-script-timeouts
description: External asyncio timeouts wrapping shell scripts must exceed the script's own internal retry/timeout budget, not just cover the "happy path" duration
metadata:
  type: feedback
---

In `services/agent-runner/quality_gate.py`, subprocess calls wrap shell scripts (e.g. `scripts/wait_healthy.sh`, `make smoke-test`) that have their own internal retry loops/timeouts. If the external `_run(..., timeout=N)` wrapper is shorter than the script's own timeout, the subprocess gets killed mid-retry and the gate reports a generic "CI tests failed" — even though the underlying code/service is fine and would have passed if the script's own retry logic had been allowed to finish. This exact bug (120s wrapper vs. wait_healthy.sh's 300s default) caused multiple work orders (WO-496, 497, 500, 443, 513) to fail spuriously under concurrent-agent host load, and manual reruns of the identical checks passed.

**Why:** A shorter external timeout doesn't just add safety margin — it changes failure semantics from "script exhausted its own retries and gave up" to "we impatiently killed a script that was still legitimately retrying," producing false negatives that look identical to real failures.

**How to apply:** When adding or reviewing an `asyncio`/subprocess timeout wrapper around any script, check the wrapped script's own timeout/retry-loop