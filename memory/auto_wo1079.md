---
name: sqlite-write-behind-writer-state
description: services/orchestrator/db.py has a background write-behind thread for SQLite sync; tests must reset it explicitly and errors surface on the *next* call, not immediately
metadata:
  type: project
---

`db.py` now has a module-level singleton daemon thread (`_writer_thread`) plus shared state (`_pending`, `_job_id`, `_done_id`, `_error`) guarded by `_writer_cv`, used by `schedule_sync_runs()`/`flush_sync_runs()`. `_db_sync_dispatch()` in orchestrator.py picks sync vs async path via `asyncio.get_running_loop()` (RuntimeError means no loop → call