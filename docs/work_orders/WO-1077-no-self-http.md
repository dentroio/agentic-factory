# WO-1077 — Stop unauthenticated self-HTTP in the orchestrator

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1076
**Status:** 🟡 In Progress

---

## Background

AF-09 requires `Authorization: Bearer <API_SECRET>` on every orchestrator request, GET included. Three PM-chat paths still `httpx` to `http://localhost:{API_PORT}/...` with no header:

1. `dispatch_wo` → `POST /api/pm/dispatch` — **does not check the status code**, then reports success. After AF-09 this is a 401 and `_pm_dispatch` is never set.
2. `reset_wo` → `POST /api/dispatch/{wo}/reset` — 401, reported as failure.
3. `pm_chat` → `GET /api/backends` — 401, swallowed; the PM prompt never sees live backend status.

These are already inside an authenticated request. Call the handlers directly.

Do **not** start the factory or unpause.

## What to Build

1. `dispatch_wo` calls `pm_dispatch_wo(...)` then wakes the runner (runner call still uses `_runner_headers()`).
2. `reset_wo` calls `reset_dispatch(...)` and maps `HTTPException`.
3. `pm_chat` calls `get_backends()`.
4. Unit test: `localhost:{API_PORT}` is gone from `orchestrator.py`.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — replace the three self-HTTP blocks only
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] No `localhost:{API_PORT}` HTTP in `orchestrator.py`
- [ ] `dispatch_wo` cannot report success unless `pm_dispatch_wo` ran
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/orchestrator.py` | Direct handler calls |
| Create | `tests/unit/test_no_self_http.py` | Guard |
| Modify | `docs/project_management/PROGRESS.md` | 1076 complete, 1077 in progress |

## Execution

- **Branch:** `wo/1077-no-self-http`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1077 — PM tools must not HTTP-round-trip to self`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1076
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
