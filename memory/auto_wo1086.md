---
name: factory-agent-cursor-runs-uncommitted-checkout
description: factory-agent-cursor LaunchAgent executes runner.py directly from a shared local checkout with no Docker isolation — uncommitted local edits are already live in production
metadata:
  type: project
---

The `factory-agent-cursor` LaunchAgent runs `services/agent-runner/runner.py` directly against a shared local filesystem checkout — it is **not** containerized/isolated like other services. Any uncommitted edit made in that checkout is immediately executing in production, untested by CI and unreviewed, before it's ever committed.

**Why:** This PR recovered ~29h of work that had been silently running live this way (WO-1086/1087 conflict-advisor + gate-failure-intelligence code sat uncommitted in the checkout the LaunchAgent executes from). Divergence between the checkout's working tree and what's actually committed/reviewed was also the root cause of a related bug this PR fixes (`worktree_guard.py` — a worktree directory can be checked out to the wrong WO's branch and get silently