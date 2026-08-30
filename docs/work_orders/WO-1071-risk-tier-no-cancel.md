# WO-1071 — Risk Tier gate must not cancel in-progress runs

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** ci, docs
**Depends on:** WO-1070
**Status:** ✅ Complete

---

## Background

PR #224 opened and then received `risk-tier-approved` in the same second. Two `pull_request` runs started; `cancel-in-progress: true` cancelled one. GitHub treats a **cancelled** required check as blocking even when the surviving run is green. Merge stayed `BLOCKED` until the cancelled job was rerun.

Do **not** start the factory or unpause.

## What to Build

1. Stop cancelling in-progress Risk Tier runs.
2. Retry label/review lookup for a short window so `opened` absorbs create-then-label.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Workflow-only — no orchestrator rebuild
- Do not start the runner

## Acceptance Criteria

- [ ] `risk-tier-approval.yml` does not cancel in-progress runs
- [ ] P0/P1 waits briefly for `risk-tier-approved` before failing
- [ ] Factory stays paused
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/risk-tier-approval.yml` | No cancel-in-progress |
| Modify | `scripts/check_risk_tier_approval.py` | Retry label/review |
| Modify | `tests/unit/test_risk_tier_approval.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1070 complete, 1071 in progress |

## Execution

- **Branch:** `wo/1071-risk-tier-no-cancel`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(ci): WO-1071 — Risk Tier gate must not cancel in-progress runs`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1070
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Workflow-only. Confirm pause is still on and `/api/next` still drains.
