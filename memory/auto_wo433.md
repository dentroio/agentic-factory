```
---
name: shared-compose-project-requires-per-service-locking
description: All agent-runner worktrees share COMPOSE_PROJECT_NAME=clarion, so container rebuilds across concurrent WOs must be serialized per-service
metadata:
  type: project
---

All worktrees in agent-runner share `COMPOSE_PROJECT_NAME=clarion` (containers are NOT duplicated per-runner/worktree). This means any code that does `docker compose build` + `up -d` for a service must assume another concurrent WO could be rebuilding/recreating the *same* container at the *same* time.

**Why:** Two WOs quality-gating the same service concurrently raced on build+up — one run's `up -d --no-deps` recreated the container out from under another run's already-resolved container ID mid-attach, causing "No such container" failures even though builds succeeded. This was hard to diagnose because it looked like a build/attach bug, not a concurrency bug, and it stalled WO-433/WO-444.

**How to apply:** Any new code path that rebuilds/restarts a shared service container must acquire the per-service file lock at `/tmp/factory-compose-{svc}.lock` (see `_with_compose_lock` in quality_gate.py) around the build+up block. Reuse the existing stale-PID self-heal lock pattern (same as `/tmp/factory-ci-local.lock`) rather than inventing a new locking mechanism — a lock held by a killed process must not block forever.
```