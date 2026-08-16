# WO-1062 — CI AI review treats the PR diff as data (AF-17)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** scripts, docs
**Depends on:** WO-1061
**Status:** 🟡 In Progress

---

## Background

AF-17 remaining hole: `scripts/ai_review.py` wrapped the PR diff in a markdown ` ```diff ` fence. A diff line containing a closing fence can escape that block and inject instructions into the reviewer prompt. The verdict is parsed from the model's prose. Trusted-scripts already stop a PR from rewriting `ai_review.py`; this WO stops the diff itself from rewriting the prompt.

Do **not** start the factory or unpause.

## What to Build

1. `wrap_untrusted` in `scripts/ai_review.py` (same sentinels as WO-1055). Strip sentinels and triple-backticks from the payload. Do not wrap the diff in a markdown fence.
2. Unit tests with no API calls.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- This script runs from `trusted-scripts/` in CI. Do not import `services/agent-runner`.
- Conflict-magnet: do not edit `orchestrator.py`

## Acceptance Criteria

- [ ] `ai_review.py` has no ` ```diff ` wrapper around the chunk
- [ ] Closing fences and sentinels inside a diff cannot close the wrapper
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `scripts/ai_review.py` | Untrusted wrap |
| Modify | `tests/unit/test_ai_review_chunking.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1061 complete, 1062 in progress |

## Execution

- **Branch:** `wo/1062-ai-review-untrusted-diff`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(review): WO-1062 — treat the PR diff as data in AI review`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1061
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI.
