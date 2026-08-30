# WO-1070 — Targeted dispatch upserts, no swallowed SQLite writes (AF-26)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1069
**Status:** ✅ Complete

---

## Background

WO-1068 added WAL, a busy timeout, and explicit close. The rest of AF-26 is still open: `_db_sync_dispatch` rewrites **every** `runs` row on every save, and failures are `print`ed and swallowed — a lost write with no alert.

This WO upserts only changed rows and deletes only missing ones. Write failures propagate. It does **not** move the sync off the event loop (follow-up).

Do **not** start the factory or unpause.

## What to Build

1. `db.sync_runs(path, records)` — fingerprint cache, targeted upsert/delete, no swallow.
2. `_load_state` remembers fingerprints after a SQLite load so the first save is a no-op if nothing changed.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — replace `_db_sync_dispatch` body only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] Unchanged dispatch state does not rewrite the `runs` table
- [ ] SQLite sync failures are not swallowed
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/db.py` | `sync_runs` / `remember_runs` |
| Modify | `services/orchestrator/orchestrator.py` | Thin wrapper, remember on load |
| Create | `tests/unit/test_targeted_dispatch_sync.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1069 complete, 1070 in progress |

## Execution

- **Branch:** `wo/1070-targeted-dispatch-sync`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1070 — targeted dispatch upserts, no swallowed SQLite writes`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1069
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
