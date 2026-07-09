# WO-1013 — Multi-Agent Review Chain: Peer Code Review Before Human Validation

**Status:** ✅ Done
**Priority:** P2
**Effort:** L
**Services:** agent-runner
**Depends on:** WO-1009 (WO thread), WO-1010 (agent thread awareness), WO-1012 (quality gate)

---

## Problem

A single agent writing and self-reviewing code has blind spots. Adversarial review by a different model with a different training base is more valuable than the same model checking its own work. Human reviewers catch things the original author cannot see. Same principle applies to AI agents.

---

## What to Build

`services/agent-runner/review_chain.py`:

- `REVIEW_CHAIN` map: P3=[], P2=[security, correctness], P1=[security, architecture, correctness], P0=[all 4]
- `REVIEWER_CONFIG` per reviewer: backend (env-configurable), prompt template, blocking severities
- `run_review_chain()` — runs reviewers sequentially, stops on first blocking finding, posts each review to thread
- `get_worktree_diff()` — git diff HEAD~1 HEAD
- `parse_reviewer_response()` — extracts `FINDING: {...}` lines from LLM output
- `_format_review()` — renders findings as readable thread message with severity badges

Integrated into `runner.py` after quality gate passes, before `/api/validate`.

---

## Quality & Security Requirements

- [ ] `make ci-local` passes clean
- [ ] No hardcoded secrets or credentials
- [ ] All user inputs validated at system boundaries
- [ ] New API endpoints use `require_role()` dependency
- [ ] Security scanner: no CRITICAL or HIGH findings

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | P2 WOs run security + correctness reviewers before human validation |
| 2 | CRITICAL/HIGH findings block `/api/validate` |
| 3 | Each reviewer's findings posted to WO thread as `review` type messages |
| 4 | Agent receives blocking findings via `backend.inject()` for fixing |
| 5 | Thread shows "✅ All reviewers signed off" when chain passes |
| 6 | Backend per reviewer configurable via env vars |
| 7 | Accumulated findings passed to each subsequent reviewer |

---

## Execution

- **Branch:** `wo/372-review-chain`
- **PR:** #19 merged 2026-07-04
