# WO-1054 — Factory audit closeout (no autonomous development)

**Created:** 2026-08-15
**Priority:** P0
**Effort:** L
**Services:** orchestrator, agent-runner, docs
**Depends on:** —

**Status:** 🟡 In Progress

---

## Background

The 15 August 2026 audit (delta from AF-01–AF-48) found the factory idle: the agent runner has been down since 9 August after fail-closed orchestrator auth, P0 merge-authority and workflow-injection findings are still open, and PM chat can still squash-merge from free text. The operator asked to close these out **without letting the factory start any development** — no WO claims, no auto-dispatch, no health-agent revival of the runner.

## What to Build

1. **Dispatch pause** — persisted flag. `/api/next` and `/api/claim` refuse work while paused. Default off for new templates; this instance is set paused after deploy.
2. **Claim lease** — fencing token issued on claim; checkin/validate/complete/heartbeat return 409 on mismatch; runner aborts and does not release a claim it no longer holds.
3. **PM privileged actions** — free-text `[PR:merge:]`, `[RESET:]`, `[DISPATCH:]`, `[DEPENDABOT:approve-merge:]` must not execute. `merge_pr` only for P2/P3 WOs (unknown tier = deny).
4. **Workflow hardening** — untrusted GitHub fields only via `env:`; privileged scripts executed from the default branch, not the PR tree.
5. **Runner auth** — `run-local.sh` refuses to start without `API_SECRET`. Do **not** start the daemon as part of this WO.
6. **Ruleset / label / status script** — required checks include Risk Tier Approval Gate and Claude Code Review; `new-wo` label exists; `factory_status.py` recognizes the live ruleset name `Protect main`.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `services/orchestrator/orchestrator.py`
- Do not `make agent-start` or bootstrap the factory-agent LaunchAgent
- Health agent reloads a dead runner — it must stay unloaded while paused

## Acceptance Criteria

- [x] `GET /api/next` returns `wo: null` with reason `factory paused — drain mode active` while pause is on
- [x] `POST /api/claim` returns 423 while pause is on
- [x] Claim response includes `claim_token`; checkin without it returns 409
- [x] Checkin with the wrong token returns 409
- [x] Runner `checkin` treats 409 as a lost lease and does not call `release_dispatch`
- [x] `planning-agent.yml` does not interpolate `github.event.issue.title` inside a `run:` script (only via `env:`)
- [x] `ci-auto-fix.yml` and `ai-review-applier.yml` run `python3 trusted-scripts/scripts/...` not `scripts/...` from the PR checkout
- [x] Free-text `[PR:merge:N]` does not call the GitHub merge API
- [x] `run-local.sh` exits non-zero when `API_SECRET` is empty
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/dispatch_control.py` | Pause + claim-lease helpers |
| Create | `tests/unit/test_dispatch_control.py` | Lease/pause unit tests |
| Create | `tests/unit/test_workflow_injection_guards.py` | Workflow file guards |
| Modify | `services/orchestrator/orchestrator.py` | Pause, lease, PM action gating |
| Modify | `services/agent-runner/orchestrator_client.py` | Send lease header; surface 409 |
| Modify | `services/agent-runner/runner.py` | Abort on lost lease |
| Modify | `services/agent-runner/run-local.sh` | Fail closed without API_SECRET |
| Modify | `services/agent-runner/health_agent.py` | Skip re-dispatch when paused |
| Modify | `.github/workflows/planning-agent.yml` | env: for issue fields |
| Modify | `.github/workflows/ci-auto-fix.yml` | trusted scripts + env: |
| Modify | `.github/workflows/ai-review-applier.yml` | trusted scripts + env: |
| Modify | `.github/workflows/dependabot-wo-bridge.yml` | env: for PR fields |
| Modify | `.github/workflows/ai-review.yml` | run reviewer from trusted-scripts |
| Modify | `scripts/factory_status.py` | Recognize `Protect main` |
| Modify | `AGENT_PROCESS.md` | Required checks list |
| Modify | `docs/project_management/PROGRESS.md` | Tracker refresh |
| Modify | `docs/project_management/CAPABILITY_STATUS.md` | Pause + lease capabilities |

## Execution

- **Branch:** `wo/1054-factory-audit-closeout`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(factory): WO-1054 — audit closeout without autonomous dispatch`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** none
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md

### UI Verification

No UI changes — backend / API only. Confirm:

1. Dashboard at http://localhost:8099 still loads
2. `GET /api/factory/pause` shows `{"paused": true}`
3. Agent runner is **not** running (`lsof -iTCP:8101` empty)
