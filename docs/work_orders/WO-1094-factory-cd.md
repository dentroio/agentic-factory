# WO-1094 — Factory engine Continuous Deployment

**Created:** 2026-09-07
**Priority:** P1
**Effort:** M
**Services:** docs, ci, scripts
**Depends on:** none
**Status:** 🟡 In Progress

---

## Problem

`factory_status.py` still warns that `deploy.yml` is not configured. After a PR merges to
`main`, operators must manually rebuild Docker services. The factory loop stops at merge —
no automated deploy, smoke, or incident issue on failure.

## Goal

An engine-specific CD path: optional auto-deploy of `docker-compose.status.yml` on a
self-hosted runner, with smoke checks and incident issues — gated so merges do not fail
red until an operator enables CD.

## Scope

**In scope:**
- `.github/workflows/deploy.yml` for this engine (not the product Clarion stack)
- `scripts/factory_smoke.py` + `make smoke`
- Gate: push-to-main deploy only when repo variable `FACTORY_CD_ENABLED=true`;
  `workflow_dispatch` always allowed when a matching runner is online
- Close out stale PROGRESS rows for WO-1090 / WO-1093
- Update CAPABILITY_STATUS + CD plan pointer for the engine

**Out of scope:**
- Registering the self-hosted runner on the operator machine (documented steps only)
- Product-app CD (Clarion / adopters use their own `deploy.yml`)
- Image registry / multi-environment promotion

## Approach

- `runs-on: [self-hosted, factory-deploy]`
- Rebuild: `docker compose -f docker-compose.status.yml build && up -d`
- Smoke: status-site `:8099/health` must be 200; orchestrator `:8100/health` must respond
  (200 or 401 — auth middleware covers all routes)
- On failure: open GitHub issue with `incident` label

## Acceptance Criteria

- [x] `.github/workflows/deploy.yml` exists with no `{{PLACEHOLDER}}` tokens
- [x] `python3 scripts/factory_status.py` reports ✅ for deploy.yml
- [x] `make smoke` / `scripts/factory_smoke.py` checks local factory health
- [x] Push-to-main deploy is skipped unless `FACTORY_CD_ENABLED=true`
- [x] Failure path creates an incident issue (scripted in workflow)
- [x] WO-1090 and WO-1093 marked complete in PROGRESS
- [x] `make ci-local` passes

## Verification Steps

```bash
python3 scripts/factory_status.py   # CD section green
make smoke                          # against local stack
# After runner labeled factory-deploy is online:
gh workflow run deploy.yml
```

---

## Execution

**Branch:** `wo/1094-factory-cd`
**Risk tier:** P1 — human merge (touches deploy automation)
**PR title:** `feat(cd): WO-1094 — factory engine continuous deployment`
**Auto-merge:** no

**PM docs to update after merge:**
- `docs/project_management/PROGRESS.md`
- `docs/project_management/CAPABILITY_STATUS.md`

### UI Verification

No UI changes — workflow / scripts / docs only.

---

## Operator setup (after merge)

1. GitHub → Settings → Actions → Runners → New self-hosted runner
2. Add label `factory-deploy`
3. Ensure Docker can run `docker compose -f docker-compose.status.yml` on that host
4. Set Actions variable `FACTORY_CD_ENABLED=true` when ready for push-to-main deploys
5. Until then, use **Actions → Deploy → Run workflow**
