---
name: watchdog-auto-approves-trusted-branch-workflows
description: pr-watchdog auto-approves GitHub Actions runs for branches matching common prefixes, bypassing manual "Approve and run" gating
metadata:
  type: project
---

`services/pr-watchdog/watchdog.py` now calls `POST /repos/{repo}/actions/runs/{run_id}/approve` to auto-approve `action_required` workflow runs whose `head_branch` starts with `wo/`, `dependabot/`, `feat/`, `fix/`, `chore/`, or `docs/`. Only runs that don't match (or whose approval call fails) still generate the "needs approval" alert.

**Why:** These prefixes