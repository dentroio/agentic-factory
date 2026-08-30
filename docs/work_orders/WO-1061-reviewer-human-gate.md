# WO-1061 — AI reviewer cannot satisfy the human validation gate (AF-17)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** agent-runner, docs
**Depends on:** WO-1060
**Status:** ✅ Complete

---

## Background

AF-17: `reviewer.py` polls pending validations and can `POST /api/validations/{wo}/approve` from a `claude -p` verdict. The PR diff is pasted into that prompt as instructions-shaped text. A diff that says `APPROVE:` can collapse the **human** validation gate. Backend-only P0/P1 WOs currently auto-approve and the thread says the PR will merge automatically.

UI/API changes already wait for a human. P0/P1 must wait even when the change is backend-only. The diff must be framed as data, same as WO-1055.

Do **not** start or restart the reviewer LaunchAgent. Do not unpause dispatch.

## What to Build

1. `may_auto_approve(priority, has_ui, has_api_surface)` — false for UI, API surface, P0, or P1.
2. `_claude_review` wraps the diff with `wrap_untrusted`.
3. `review_one` uses that helper; P0/P1 backend-only posts a thread and leaves the validation pending.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: do not edit `orchestrator.py`
- Reviewer is a host process; do not `launchctl kickstart` it

## Acceptance Criteria

- [ ] P0 and P1 never auto-approve
- [ ] UI or API-surface changes never auto-approve
- [ ] P2/P3 backend-only may still auto-approve
- [ ] Diff is wrapped as DATA, not instructions
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/agent-runner/reviewer.py` | Gate + untrusted diff |
| Create | `tests/unit/test_reviewer_gate.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1060 complete, 1061 in progress |

## Execution

- **Branch:** `wo/1061-reviewer-human-gate`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(reviewer): WO-1061 — P0/P1 validations stay human`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1060
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. Do not start the reviewer. Factory stays paused.
