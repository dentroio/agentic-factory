# WO-1079 — Dispatch SQLite sync off the event loop (AF-26 remainder)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1078
**Status:** 🟡 In Progress

---

## Background

WO-1070 made `sync_runs` targeted and fail-loud, but `_db_sync_dispatch` still runs SQLite on the asyncio event loop. Heartbeats and claim/checkin share that loop. This WO snapshots `_dispatch_state` and writes on a coalescing background thread.

Startup (no running loop) stays synchronous so JSON→SQLite migration still completes before serve. A prior writer failure is raised on the next schedule so errors are not swallowed.

Do **not** start the factory or unpause.

## What to Build

1. `schedule_sync_runs` / `flush_sync_runs` in `db.py`.
2. `_db_sync_dispatch` snapshots, then schedules when a loop is running.
3. Unit tests for snapshot isolation and failure surfacing.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — `_db_sync_dispatch` body only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner
- Do not `future.result()` from sync code on the running loop

## Acceptance Criteria

- [ ] With a running event loop, dispatch SQLite writes are scheduled, not inline
- [ ] Without a running loop (startup), sync stays synchronous
- [ ] SQLite sync failures are not swallowed
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/db.py` | Background writer |
| Modify | `services/orchestrator/orchestrator.py` | Snapshot + schedule vs sync |
| Modify | `tests/unit/test_targeted_dispatch_sync.py` | Guards |
| Create | `docs/work_orders/WO-1079-sqlite-off-loop.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1078 complete, 1079 in progress |

## Execution

- **Branch:** `wo/1079-sqlite-off-loop`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1079 — dispatch SQLite sync off the event loop`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1078
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
