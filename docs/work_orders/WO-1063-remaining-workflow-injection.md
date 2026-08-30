# WO-1063 — Remaining workflow injection (AF-13)

**Created:** 2026-08-16
**Priority:** P0
**Effort:** S
**Services:** github-actions, docs
**Depends on:** WO-1054
**Status:** ✅ Complete

---

## Background

WO-1054 moved issue/PR fields to `env:` in `planning-agent.yml`, `dependabot-wo-bridge.yml`, and `ai-review.yml`. Three workflows still splice untrusted strings into `run:` or github-script source:

- `verifier.yml` interpolates the PR title into a shell argument and a JS template (issues:write).
- `ci-auto-fix.yml` interpolates CI log excerpts, LLM summaries, and reasons into JS string literals and a `git commit` message.
- `ci-failure-notifier.yml` interpolates log excerpts into a JS template literal.
- `ai-review-applier.yml` interpolates LLM summary/reason into JS and a commit message.

A backtick or `${` in any of those strings becomes JavaScript. A quote in a PR title becomes shell.

Do **not** start the factory or unpause.

## What to Build

1. Pass those fields only via `env:` / `process.env`.
2. Guard every workflow YAML so the old interpolations cannot return.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: do not edit `orchestrator.py`
- `if: contains(github.event.pull_request.title, 'WO-')` is GitHub expression context, not shell — leave it

## Acceptance Criteria

- [ ] `verifier.yml` does not interpolate the PR title inside `run:` or `script:`
- [ ] CI log excerpts and LLM summaries are not interpolated into JS string literals
- [ ] Unit tests fail if those interpolations return
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `.github/workflows/verifier.yml` | env: for title / SHAs |
| Modify | `.github/workflows/ci-auto-fix.yml` | env: for logs / summaries |
| Modify | `.github/workflows/ci-failure-notifier.yml` | env: for logs / summary |
| Modify | `.github/workflows/ai-review-applier.yml` | env: for LLM summary |
| Modify | `tests/unit/test_workflow_injection_guards.py` | Scan all workflows |
| Modify | `docs/project_management/PROGRESS.md` | 1061 complete, 1063 in progress |

## Execution

- **Branch:** `wo/1063-remaining-workflow-injection`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(ci): WO-1063 — stop interpolating untrusted fields into workflow scripts`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1054
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Factory stays paused.
