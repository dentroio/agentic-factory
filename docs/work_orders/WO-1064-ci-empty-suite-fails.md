# WO-1064 — Empty unit-test suite must fail CI (AF-05)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** ci, docs
**Depends on:** WO-1063
**Status:** ✅ Complete

---

## Background

AF-05: `.github/workflows/ci.yml` swallows pytest exit code 5 (`no tests collected`). If `tests/unit/` is emptied, renamed, or collection hides every test, **CI is green**. `make test` copies the same swallow so `make ci-local` agrees with GitHub.

This WO closes that hole. It does **not** restore the template's lint / Gitleaks / build jobs — those need tool config and would fail the existing tree. Follow-up.

Do **not** start the factory or unpause.

## What to Build

1. Remove the exit-5 swallow from `ci.yml` and the Makefile `test` target.
2. Assert at least 20 `test_*.py` files exist so deleting the suite still fails even if pytest's exit codes change.
3. Guard both in `tests/unit/test_ci_local_mirrors_ci.py`.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: do not edit `orchestrator.py`
- The pytest invocation line in `ci.yml` and `make test` must stay identical (`test_make_test_matches_the_pytest_invocation_in_ci`)

## Acceptance Criteria

- [ ] `ci.yml` and `make test` do not treat pytest exit 5 as success
- [ ] Both require at least 20 unit test files
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/ci.yml` | Drop exit-5; add file floor |
| Modify | `Makefile` | Mirror CI |
| Modify | `tests/unit/test_ci_local_mirrors_ci.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1063 complete, 1064 in progress |

## Execution

- **Branch:** `wo/1064-ci-empty-suite-fails`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(ci): WO-1064 — empty unit-test suite must fail the gate`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1063
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Factory stays paused.
