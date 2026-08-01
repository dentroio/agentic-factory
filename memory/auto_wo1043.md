---
name: wo-reservation-not-truly-atomic
description: The WO number reservation API is not truly atomic under concurrent HTTP requests — it relies on single-threaded FastAPI event loop ordering, not a lock
metadata:
  type: project
---

The `/api/wos/reserve` endpoint achieves concurrency safety only because FastAPI runs handlers in a single-threaded async event loop — there is no explicit mutex, database transaction, or file lock. Two simultaneous HTTP requests that both reach `_next_wo_number()` before either writes to `_reserved` would still produce a collision.

**Why:** This was a deliberate pragmatic tradeoff: the primary concurrency problem being solved was the intelligence loop and the status-site/scripts making reservations milliseconds apart, not true simultaneous HTTP floods. The in-process `_reserved` dict is mutated and persisted synchronously within a single `await`-free code path, which is safe under the GIL within one process but not across multiple orchestrator replicas or truly concurrent requests.

**How to apply:** If the orchestrator is ever scaled to multiple replicas or if load patterns produce genuine simultaneous reservation requests, replace the in-memory dict + file approach with an atomic file-lock (e.g. `fcntl.flock`) or a SQLite transaction. Do not assume the current implementation handles true concurrency — it handles the *typical* case of staggered callers well, but a proper lock is absent by design (kept simple intentionally).