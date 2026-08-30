# WO-1085 — Closeout docs: Gitleaks required check

**Created:** 2026-08-16
**Priority:** P3
**Effort:** S
**Services:** docs
**Depends on:** WO-1084
**Status:** ✅ Complete

---

## Background

WO-1072 added a Gitleaks CI job (`Secret Detection (Gitleaks)`). `setup_factory.py` already lists it. `ENGINEER.md` and `factory_status.py` still expect only Claude / Risk Tier / Unit Tests, so a new factory can ship without Gitleaks as a required check.

Docs only. Do **not** start the factory, the runner, or unpause. Do not change the GitHub ruleset from this WO — the operator adds the check in Settings if it is missing.

## What to Build

1. Mark WO-1084 complete in PROGRESS.md.
2. Add `Secret Detection (Gitleaks)` to ENGINEER.md, AGENT_PROCESS.md, and factory_status.py.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- P3 — no deploy
- Do not start the runner

## Acceptance Criteria

- [ ] PROGRESS.md marks WO-1084 complete
- [ ] ENGINEER.md, AGENT_PROCESS.md, and factory_status.py name `Secret Detection (Gitleaks)`
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `docs/project_management/PROGRESS.md` | 1084 complete, 1085 in progress |
| Modify | `ENGINEER.md` | Required-check list |
| Modify | `AGENT_PROCESS.md` | Required-check list |
| Modify | `scripts/factory_status.py` | Status check list |
| Create | `docs/work_orders/WO-1085-closeout-docs.md` | This spec |

## Execution

- **Branch:** `wo/1085-closeout-docs`
- **Risk tier:** P3 — auto-merge after CI
- **PR title:** `docs: WO-1085 — add Gitleaks to required-check list`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1084
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Docs only. No deploy.
