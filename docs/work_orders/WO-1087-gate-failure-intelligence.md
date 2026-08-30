# WO-1087 — Gate-failure intelligence: classify, retry infra, one code-fix pass

**Created:** 2026-08-18
**Priority:** P1
**Effort:** M
**Services:** agent-runner, status-site, docs
**Depends on:** WO-1086
**Status:** ✅ Complete

---

## Background

Park-on-close-out (occupancy hotfix) stopped silent retry, which was correct for visibility. It also removed the fix loop. Five Clarion WOs parked as `awaiting_commit` after the quality gate, the PM view labeled them **in review**, and there was no Approve path because no PR existed.

Thread forensics (18 Aug 2026):

| Class | Example | Agent can fix? |
|-------|---------|----------------|
| `lock_timeout` | `CI lock wait timed out` | No — retry the gate |
| `node_modules` | `lucide-react` unresolvable in a worktree | No — repair install, retry gate |
| `timeout` | `make timed out after 1800s` while Jest `--runInBand` runs 20–70 min, including data-service-only diffs | No — skip `frontend-check` when `frontend/` did not change; keep a long budget when it did |
| `code` | WO-496: one pytest assertion vs new same-value suppression | Yes — one in-session fix pass |

The thread still said “the agent will fix this automatically”, then parked. `_analyze_failure` ran `claude -p` in the factory checkout and often blamed factory files that are not in the Clarion worktree. `format_prior_context` only loaded the thread when a validation rejection existed, so Factory **Retry** on a parked WO did not inject the CI excerpt.

## What to Build

1. `gate_failure.py` — classify CI output (`lock_timeout`, `node_modules`, `timeout`, `code`, `unknown`).
2. Quality gate: if the branch/worktree did not touch `frontend/`, run lint+unit+migrations+RBAC+pre-pr-check (no `frontend-check`). If it did, keep `make ci-local` with the existing 1800s budget (lock wait stays 1800s).
3. On gate fail: infra classes retry the **gate** (repair `node_modules` when classified) up to 2 times. `code`/`unknown` get **one** in-session agent pass with the CI excerpt, then park. Honest thread text. Analyze with worktree context, not factory cwd.
4. Always load thread messages into the retry prompt (CI analysis without a validation rejection).
5. Board: `awaiting_commit` whose step is a quality-gate fail lands in **Stalled**, not In Review.

Do **not** dispatch new Clarion WOs until the parked set drains. Hold the rest of the queue.

## Acceptance Criteria

- [ ] Lock-timeout / missing `node_modules` retry the gate without an agent rewrite
- [ ] A pytest `FAILED tests/` line triggers one agent fix pass, then park if still failing
- [ ] Data-service-only diffs do not run Clarion `frontend-check`
- [ ] Thread never says the agent will fix automatically unless a fix pass is queued
- [ ] Parked gate-fail WOs are Stalled on the PM board, not In Review
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/agent-runner/gate_failure.py` | Classify + excerpt |
| Create | `tests/unit/test_gate_failure.py` | Class table from live logs |
| Modify | `services/agent-runner/quality_gate.py` | Skip frontend-check when unused |
| Modify | `services/agent-runner/runner.py` | Infra retry, one code-fix pass |
| Modify | `services/agent-runner/prompt_builder.py` | Retry prompt from thread CI |
| Modify | `services/status-site/wo_reconcile.py` | Failed park → stalled |
| Modify | `docs/wiki/Intelligence-Loop.md` | Close-out pass |
| Create | `docs/work_orders/WO-1087-gate-failure-intelligence.md` | This spec |

## Execution

- **Branch:** `wo/1086-conflict-advisor` (same working tree as occupancy + WO-1086)
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `feat(runner): WO-1087 — classify quality-gate failures and complete a fix pass`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1086 occupancy/advisor (uncommitted on this branch)
- **PM docs to update:** PROGRESS.md

### UI Verification

1. Open http://127.0.0.1:8099 PM view — parked gate-fail WOs are **Stalled**, not In Review
2. Factory dispatch: Retry still on rows whose step contains `failed`
3. After Retry of WO-496: agent gets a RETRY / CI excerpt prompt, not a blank first attempt
4. No new queue WO claims while 495/498/501/503/506/508 stay held
