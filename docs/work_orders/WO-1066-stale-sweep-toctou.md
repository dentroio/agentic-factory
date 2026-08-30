# WO-1066 — Stale sweep must not abort poll on a vanished claim (AF-22)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1065
**Status:** ✅ Complete

---

## Background

AF-22: `poll()` snapshots stale claims, **awaits a GitHub PR lookup**, then writes `_dispatch_state[wo_id]["status"]`. During that await, `DELETE /api/dispatch/{wo}` or a checkin can remove or finish the key. The write raises `KeyError` and aborts the rest of `poll()` — merged-PR reconciliation, plan overlay, stuck detection, and the output snapshot skip for that cycle.

The preflight retry sweep has the same shape: `await preflight_check` then `del _preflight_held[wo_id]`.

Do **not** start the factory or unpause.

## What to Build

1. `live_claim(state, wo_id)` — None if the key vanished or is no longer `claimed`/`in_progress`.
2. Stale sweep re-reads via that helper and wraps each WO in `try/except` so one failure cannot abort `poll()`.
3. Preflight retry re-gets the held entry after the await; use `.pop` not `del`.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — only the stale and preflight loops inside `poll()`
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] Vanished claims are skipped, not `KeyError`
- [ ] One stale-sweep failure does not prevent the rest of `poll()`
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/dispatch_control.py` | `live_claim` |
| Modify | `services/orchestrator/orchestrator.py` | Stale + preflight loops |
| Modify | `tests/unit/test_dispatch_control.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1065 complete, 1066 in progress |

## Execution

- **Branch:** `wo/1066-stale-sweep-toctou`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1066 — stale sweep must not abort poll`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1065
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
