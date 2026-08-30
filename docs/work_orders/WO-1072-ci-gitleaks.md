# WO-1072 — CI must scan for committed secrets (AF-05)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** ci, docs
**Depends on:** WO-1071
**Status:** ✅ Complete

---

## Background

AF-05: `ci.yml` is pytest only. The template's Gitleaks job was never restored. Docs and `CAPABILITY_STATUS.md` claim secret detection blocks PRs; it does not.

This WO adds the Gitleaks job and a matching `make secrets` target so `make ci-local` still mirrors CI. Lint and build jobs stay out of scope (need AF-42).

Do **not** start the factory or unpause. Do **not** add the check to the ruleset until this PR is on main (a required check that has never run blocks every PR).

## What to Build

1. `secrets` job in `ci.yml` — Gitleaks on committed history.
2. `make secrets` + `ci-local` composes it.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Workflow-only — no orchestrator rebuild
- Scan git history, not the working tree, so a local gitignored `.env` does not fail the gate
- Do not start the runner

## Acceptance Criteria

- [ ] `ci.yml` has a Secret Detection (Gitleaks) job
- [ ] `make ci-local` runs `secrets`
- [ ] Factory stays paused
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/ci.yml` | Gitleaks job |
| Modify | `Makefile` | `secrets` target |
| Modify | `tests/unit/test_ci_local_mirrors_ci.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1071 complete, 1072 in progress |

## Execution

- **Branch:** `wo/1072-ci-gitleaks`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(ci): WO-1072 — scan committed secrets with Gitleaks`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1071
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Workflow-only. Confirm pause is still on and `/api/next` still drains.
