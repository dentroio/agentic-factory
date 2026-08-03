---
name: backend-inject-does-not-work
description: backend.inject() cannot deliver follow-up feedback to a running agent — it's a no-op for all backends
metadata:
  type: project
---

`backend.inject()` in agent-runner appears to let you send follow-up messages to an in-progress agent, but it structurally cannot: every backend's `run()` (`claude --print`, `agent --print --force`, `codex exec -`, `gemini --yolo -p`) is a one-shot CLI invocation that has already exited by the time any post-run code (e.g. review-chain failure handling) executes. `inject()` only appends to a queue on the *current* backend object, and `get_backend()` hands out a brand-new object on the next claim anyway, so nothing is ever there to read the injected message. This silently dropped review-chain feedback (WO-420, WO-440) with the WO just sitting claimed until the orchestrator's 10-minute stale-claim timeout re-queued it from scratch.

**Why:** Backends are one-shot CLI processes, not long-lived sessions — there is no listener for `inject()` to reach, on any backend.

**How to apply:** To feed an agent new information after it has finished a run, build a new promp