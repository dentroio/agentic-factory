# WO-1065 — Atomic JSON writes for in-flight factory state (AF-27)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1064
**Status:** 🟡 In Progress

---

## Background

AF-27: dispatch, hold, validation, and thread files used bare `write_text`. A crash mid-write leaves truncated JSON. Loaders then `except Exception: → {}` / `[]`, which silently erases in-flight claims and WO threads.

`dispatch_control.save_pause` already uses temp-file + replace. Extend that helper to the claim-state files.

Do **not** start the factory or unpause.

## What to Build

1. `atomic_write_json` in `dispatch_control.py`.
2. `_save_dispatch`, `_save_held`, `_save_validations`, and `thread.save_thread` use it.
3. Unit tests. Do not edit other `write_text` sites (secrets, usage) in this WO.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — only the three `_save_*` helpers
- Rebuild orchestrator only. Do not recreate Vault. Do not start the runner.

## Acceptance Criteria

- [ ] Dispatch / held / validations / thread JSON is written via temp + replace
- [ ] Pause and attempt-count saves share the same helper
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/dispatch_control.py` | `atomic_write_json` |
| Modify | `services/orchestrator/orchestrator.py` | Claim-state saves |
| Modify | `services/orchestrator/thread.py` | Thread save |
| Modify | `tests/unit/test_dispatch_control.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1064 complete, 1065 in progress |

## Execution

- **Branch:** `wo/1065-atomic-state-writes`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1065 — atomic writes for in-flight factory state`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1064
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
