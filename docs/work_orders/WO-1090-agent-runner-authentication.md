# WO-1090 — Agent Runner Authentication & Zero-Trust Hardening

**Created:** 2026-08-30
**Priority:** P2
**Effort:** M
**Services:** orchestrator, agent-runner, status-site, docs
**Depends on:** WO-1089
**Status:** 🟡 In Progress

---

## Background

Previously, the factory relied solely on a shared `API_SECRET` machine credential for all components. While this prevented unauthenticated external access, it lacked per-runner identity verification: any client presenting `API_SECRET` could claim as any arbitrary agent name, forge heartbeats, or mark work orders complete without proof of identity. Additionally, revoking an individual runner required rotating the master `API_SECRET` across the entire factory.

This WO introduces per-runner token provisioning, SHA-256 token hashing, agent identity enforcement on claims/check-ins, and runner management in the dashboard settings.

## What to Build

1. **Runner Token Registry (`services/orchestrator/orchestrator.py`)**:
   - Manage runner tokens in `/data/runner_tokens.json` (or SQLite `agent_runners` table).
   - Store `id`, `agent_name`, `backend`, `workstation`, `token_hash` (SHA-256), `status` (`active` / `revoked`), `created_at`, and `last_seen`.
   - Generate cryptographically secure tokens with prefix `rn_` (`secrets.token_urlsafe(32)`).

2. **Authentication Middleware & Identity Binding (`services/orchestrator/orchestrator.py`)**:
   - Update `_bearer_auth` to validate bearer tokens against both master `API_SECRET` and active runner tokens.
   - Attach runner metadata to `request.state.runner`.
   - In `/api/claim`, `/api/checkin`, and `/api/complete`, verify that the caller's requested `agent` matches `request.state.runner["agent_name"]` if authenticated via a runner token (returning 403 on mismatch).

3. **Runner Management Endpoints (`services/orchestrator/orchestrator.py`)**:
   - `GET /api/runners`: List registered runner tokens with masked prefixes (`rn_...***`), assigned agents, and last-seen timestamps.
   - `POST /api/runners/register`: Provision a new token for an agent runner. Returns the plaintext token once.
   - `POST /api/runners/{runner_id}/revoke`: Revoke a runner token immediately.

4. **Dashboard Settings UI (`services/status-site/`)**:
   - Add **Runner Tokens & Auth** tab to `/settings/agents` allowing operators to view active runners, generate new tokens, and revoke credentials.
   - Add status site API proxy routes for runner management.

5. **Agent Runner Client (`services/agent-runner/`)**:
   - Support `RUNNER_TOKEN` in `config.py`, `orchestrator_client.py`, and `thread_monitor.py`, falling back to `API_SECRET`.

## Requirements

```yaml
requires:
  connectors: []
  services:
    - orchestrator
    - status-site
    - agent-runner
```

## Acceptance Criteria

- [ ] `POST /api/runners/register` creates a new runner token, securely hashes it, and stores it in `/data/runner_tokens.json`.
- [ ] Requests using a valid `Bearer rn_...` token authenticate successfully.
- [ ] Requests using a revoked or invalid runner token return 401 Unauthorized.
- [ ] A runner token bound to `claude-01` claiming as `cursor-02` returns 403 Forbidden.
- [ ] Master `API_SECRET` continues to work for internal service calls.
- [ ] `/settings/agents` UI displays registered runners and allows generating and revoking tokens.
- [ ] `make ci-local` passes with full test coverage.

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/work_orders/WO-1090-agent-runner-authentication.md` | This spec |
| Modify | `services/orchestrator/orchestrator.py` | Runner token registry, auth middleware, and API endpoints |
| Modify | `services/status-site/main.py` | Status site proxy routes for runner management |
| Modify | `services/status-site/templates/settings_agents.html` | UI for managing runner tokens |
| Modify | `services/agent-runner/config.py` | Support RUNNER_TOKEN |
| Modify | `services/agent-runner/orchestrator_client.py` | Support RUNNER_TOKEN |
| Create | `tests/unit/test_runner_auth.py` | Unit tests for runner authentication and identity binding |
| Modify | `docs/project_management/PROGRESS.md` | Track WO-1090 |
| Modify | `docs/project_management/CAPABILITY_STATUS.md` | Track WO-1090 capability |

## Execution

- **Branch:** `wo/1090-agent-runner-authentication`
- **Risk tier:** P2 — auto-merge after CI
- **PR title:** `feat(orchestrator,agent-runner): WO-1090 — agent runner authentication and zero-trust hardening`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1089
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
