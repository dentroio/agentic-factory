# WO-1076 — Draft server requires a bearer token (AF-07)

**Created:** 2026-08-16
**Priority:** P0
**Effort:** S
**Services:** agent-runner, orchestrator, docs
**Depends on:** WO-1075
**Status:** 🟡 In Progress

---

## Background

AF-07 bind-to-loopback is already in `draft_server.py`. The assessment also required a bearer token as defense in depth. The handler still has none: any local process can `POST /dispatch`, `POST /api/draft`, or `PUT /api/agents/{name}` (rewrite launchd plists, including API keys).

The orchestrator already holds `API_SECRET` and is the only legitimate client. It currently calls the draft server with no `Authorization` header.

Do **not** start the factory, the runner, or unpause.

## What to Build

1. `draft_auth.is_authorized(secret, authorization)` — fail closed if the secret is missing; `hmac.compare_digest` against `Bearer <secret>`.
2. Every draft-server method (`GET`/`POST`/`PUT`/`DELETE`) returns 401 unless authorized.
3. Orchestrator sends `Authorization: Bearer <API_SECRET>` on every call to `AGENT_RUNNER_URL`.
4. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Do not start the runner to verify
- Do not recreate Vault
- Conflict-magnet: `orchestrator.py` — add `_runner_headers()` and pass it at existing call sites only

## Acceptance Criteria

- [ ] Missing or wrong bearer → 401 on draft-server routes
- [ ] Empty `API_SECRET` is not treated as authorized
- [ ] Every orchestrator call to `AGENT_RUNNER_URL` includes `_runner_headers()`
- [ ] Factory stays paused; runner stays down
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/agent-runner/draft_auth.py` | Bearer check |
| Modify | `services/agent-runner/draft_server.py` | Gate every method |
| Modify | `services/orchestrator/orchestrator.py` | Send bearer to the runner |
| Create | `tests/unit/test_draft_server_auth.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1075 complete, 1076 in progress |

## Execution

- **Branch:** `wo/1076-draft-server-bearer`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(runner): WO-1076 — draft server requires a bearer token`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1075
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Do not start the runner. Confirm pause is still on and `/api/next` still drains.
