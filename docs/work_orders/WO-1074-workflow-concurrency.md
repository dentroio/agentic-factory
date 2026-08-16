# WO-1074 — Workflow concurrency groups (AF-44)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** ci, docs
**Depends on:** WO-1073
**Status:** 🟡 In Progress

---

## Background

AF-44 timeouts are already on every job. Concurrency is not: 15 workflows can stack (cron overruns, overlapping `git push --force-with-lease`, stacked Anthropic calls).

Do **not** start the factory or unpause. Do **not** change `risk-tier-approval.yml` (`cancel-in-progress: false` is required after PR #224).

## What to Build

1. A `concurrency:` group on every workflow that lacks one.
2. Unit test that every `.github/workflows/*.yml` declares concurrency.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Workflow-only — no orchestrator rebuild
- Risk Tier gate stays `cancel-in-progress: false`

## Acceptance Criteria

- [ ] Every workflow YAML has a `concurrency:` block
- [ ] Risk Tier still does not cancel in-progress runs
- [ ] Factory stays paused
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/*.yml` | Add missing concurrency |
| Create | `tests/unit/test_workflow_concurrency.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1073 complete, 1074 in progress |

## Execution

- **Branch:** `wo/1074-workflow-concurrency`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(ci): WO-1074 — concurrency groups on every workflow`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1073
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Workflow-only. Confirm pause is still on and `/api/next` still drains.
