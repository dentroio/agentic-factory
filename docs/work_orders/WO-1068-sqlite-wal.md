# WO-1068 — SQLite WAL, busy timeout, and closed connections (AF-26)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1067
**Status:** ✅ Complete

---

## Background

AF-26: 33 `sqlite3.connect(DB_PATH)` sites with no WAL, no busy timeout, and no close. Writers block readers; `SQLITE_BUSY` is swallowed; handles leak until GC.

This WO adds one connection factory. It does **not** replace the full-table `_db_sync_dispatch` rewrite (follow-up).

Do **not** start the factory or unpause.

## What to Build

1. `db.connect(path)` — WAL, `busy_timeout=30000`, commit/rollback, close.
2. Every orchestrator `sqlite3.connect(DB_PATH)` goes through `_db()`.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — mechanical connect replacement only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] No bare `sqlite3.connect(DB_PATH)` in `orchestrator.py`
- [ ] Connections use WAL and a 30s busy timeout and are closed
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/db.py` | Connection factory |
| Modify | `services/orchestrator/orchestrator.py` | Use `_db()` |
| Create | `tests/unit/test_sqlite_wal.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1067 complete, 1068 in progress |

## Execution

- **Branch:** `wo/1068-sqlite-wal`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1068 — SQLite WAL and closed connections`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1067
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
