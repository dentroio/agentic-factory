# WO-1099 — Settings UI: METRICS_ENDPOINT (observability)

**Created:** 2026-09-12
**Priority:** P2
**Effort:** S
**Services:** orchestrator, status-site, docs
**Depends on:** WO-1095
**Status:** 🟡 In Progress

---

## Problem

`METRICS_ENDPOINT` is the last gap reported by `factory_status.py` / `ENGINEER.md`.
Operators must still open GitHub → Settings → Variables to set it. WO-1095
explicitly left this out of Deploy & Harness as a follow-up.

Without the variable, `observability.yml` skips silently every 15 minutes and
never closes the production-anomaly → WO loop.

## What to Build

1. Extend `GET/PUT /api/settings/deploy` to read/write/clear `METRICS_ENDPOINT`
   on the engine repo (same `_get/_set/_delete_repo_variable` helpers as CD).
2. Add an **Observability** section on Settings → Deploy & Harness:
   - URL field (https health/metrics JSON endpoint reachable from GitHub Actions)
   - Clear / leave blank to delete the variable
   - Short hint that localhost is not reachable from Actions
3. Update inline `?` help, BACKLOG (check off item 3), CAPABILITY_STATUS,
   Customization / Getting-Started notes as needed.
4. Unit tests (source guards) for the new API + template surface.

## Out of scope

- Installing self-hosted runners / enabling `FACTORY_CD_ENABLED` (still operator)
- Exact LLM billing (BACKLOG item 6)
- Oryntra (WO-1048 / WO-1049 — other agent)
- Editing `observability_thresholds.json` from the UI

## Acceptance Criteria

- [ ] Deploy & Harness page shows current `METRICS_ENDPOINT` (or empty)
- [ ] Saving a URL persists the Actions variable on the engine repo
- [ ] Saving blank clears / deletes the variable
- [ ] Help map documents the Observability section
- [ ] BACKLOG item 3 marked done / removed from Next
- [ ] `make ci-local` passes

## Execution

- **Branch:** `wo/1099-metrics-endpoint-settings`
- **Risk tier:** P2 — auto-merge after human UI verify
- **PR title:** `feat(settings): WO-1099 — METRICS_ENDPOINT on Deploy & Harness`
- **PM docs:** PROGRESS.md, CAPABILITY_STATUS.md, BACKLOG.md

### UI Verification

1. Open `http://localhost:8099/settings/deploy-harness`
2. Scroll to **Observability** — see METRICS_ENDPOINT field
3. Save a test URL (or clear) — expected: success toast; `gh variable list` reflects change
4. No DevTools console errors
