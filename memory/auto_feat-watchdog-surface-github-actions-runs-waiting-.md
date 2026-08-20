---
name: github-action-required-runs-are-not-cleaned-up
description: GitHub Actions runs stuck in action_required state persist forever even after the PR closes or gets superseded, and omit pull_requests field
metadata:
  type: project
---

GitHub Actions workflow runs in the `action_required` state (waiting on manual "Approve and run") are never cleaned up by GitHub when the associated PR closes or gets superseded by a new push — they remain queryable via `GET /repos/{repo}/actions/runs?status=action_required` indefinitely. Also, GitHub omits the `pull_requests` field on these runs (most visible for Dependabot branches), so you cannot rely on `run.pull_requests` to find the associated PR.

**Why:** Without filtering, stale runs from weeks-old closed/superseded branches show up as "needs approval" alerts with nothing actually actionable — pr-watchdog initially surfaced 8 raw pending runs when only 1 was real.

**How to apply:** When working with `action_required` runs, cross-reference `run.head_branch` against the list of currently open PRs (built from a separate PR fetch) and drop any run whose branch has no open PR. Also group runs by branch/PR rather than alerting per-run, since one PR can trigger multiple workflow files (CI, AI Code Review, etc.) that each land in `action_required` separately.