---
name: gh-cli-nonzero-exit-not-reliable-failure-signal
description: gh CLI commands (e.g. gh pr create) can exit non-zero even after the action succeeded server-side; never treat non-zero exit alone as definitive failure without verifying remote state.
metadata:
  type: project
---

`gh pr create` can exit non-zero due to a dropped/slow connection on the CLI's final read, even though the PR was fully created server-side. This caused WO-429 to silently skip `/api/validate` and human notification, only surfacing by luck via the orchestrator's 10-minute stale-claim sweep (which itself uses a separate recovery path that also skips `/api/validate` — still an open gap).

**Why:** Any code path that treats `gh` (or similar CLI tool) non-zero exit as ground truth for "the operation failed" can silently drop critical follow-up steps (validation, notifications) even when the underlying action succeeded.

**How to apply:** When a `gh`/CLI command reports failure but has side effects that are independently verifiable (e.g. `gh pr list --head <branch>`), check the actual remote/server state before giving up and returning a failure/empty result. Apply this pattern anywhere else in the runner or orchestrator that treats CLI non-zero exit as a hard stop — in particular, the orchestrator's stale-claim recovery path still needs the same `/api/validate` call added.