# WO-1073 — Activate Dependabot (AF-43)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** ci, docs
**Depends on:** WO-1072
**Status:** ✅ Complete

---

## Background

AF-43: GitHub never reads `.github/dependabot.yml.template`, so no dependency PRs arrive. `dependabot-wo-bridge.yml` waits on PRs that will never exist. Floor-only pins and missing lockfiles are a follow-up; this WO only **activates** Dependabot.

Do **not** start the factory or unpause.

## What to Build

1. `.github/dependabot.yml` covering the four service `requirements.txt` trees plus GitHub Actions.
2. Monthly cadence, grouped minor/patch, majors ignored, rebase disabled.
3. Unit tests.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- No npm ecosystem — this repo has no `package.json`
- Do not start the runner
- Lockfiles / exact pins are out of scope

## Acceptance Criteria

- [ ] GitHub will read `.github/dependabot.yml`
- [ ] All four `services/*/requirements.txt` directories are listed
- [ ] Factory stays paused
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `.github/dependabot.yml` | Activate Dependabot |
| Create | `tests/unit/test_dependabot_config.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1072 complete, 1073 in progress |

## Execution

- **Branch:** `wo/1073-dependabot`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(ci): WO-1073 — activate Dependabot for Python services and Actions`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1072
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Config-only. Confirm pause is still on and `/api/next` still drains.
