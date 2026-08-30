# WO-1060 — Persist retry attempts across dispatch deletion (AF-21)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1059
**Status:** ✅ Complete

---

## Background

AF-21: `MAX_RETRY_ATTEMPTS` (3) is enforced in `/api/claim` from `attempt_count` on the dispatch record. The health agent’s stuck-WO path `DELETE /api/dispatch/{wo_id}` then re-dispatches. Delete removes the record, so the next claim starts at 1. `retry_dispatch` already preserves the counter; the delete path defeats it.

A WO can be reassigned indefinitely, each cycle a full agent run, never reaching the ceiling that alerts a human.

## What to Build

1. Persist attempt counts in a file that **survives** dispatch-record deletion (`/data/attempt_counts.json`), next to pause/held state.
2. `/api/claim` takes `max(persisted, dispatch record)` then increments. Refuse at the ceiling without recording a new attempt.
3. `POST /api/dispatch/{wo_id}/reset` is the only path that clears the persisted counter for that WO.
4. Do **not** start the runner or unpause.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — load, claim increment, reset clear only
- Helpers live in `dispatch_control.py` (already the pause/lease module)
- Health agent may keep using DELETE; claim must still see the count

## Acceptance Criteria

- [ ] Deleting a dispatch record does not zero the next claim’s attempt count
- [ ] `/reset` clears the persisted counter
- [ ] Ceiling still 429 after MAX attempts
- [ ] Factory stays paused
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/dispatch_control.py` | Load/save/record attempt counts |
| Modify | `services/orchestrator/orchestrator.py` | Claim + reset + load |
| Modify | `tests/unit/test_dispatch_control.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1059 complete, 1060 in progress |

## Execution

- **Branch:** `wo/1060-persist-attempt-count`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1060 — persist retry attempts across dispatch delete`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1059
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Confirm pause still `{"paused": true}` and `/api/claim` still 423 while paused. Do not unpause.
