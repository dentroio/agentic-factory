---
name: claude-cli-subprocess-invocation-invariant
description: Every subprocess call to the claude CLI binary in agent-runner must pin --model AGENT_MODEL and use env=_subscription_env()
metadata:
  type: project
---

Any place in services/agent-runner/ that spawns the `claude` CLI binary (not just the primary claude backend, but also fallback paths in other backends like cursor.py) must pass `--model AGENT_MODEL` and `env=_subscription_env()` (both from `backends.claude`). Omitting either leaks the subscription API key into the subprocess env and/or lets claude pick a default model, causing misattributed errors (e.g. a cursor-assigned work order showing a claude-attributed error).

This bug was fixed piecemeal across PRs #62, #63, and #64 — six call sites, then a seventh fallback site found only via a full grep sweep for `claude`/`claude_bin` references.

**Why:** Fallback/secondary code paths that shell out to the claude CLI are easy to miss since they're not the "main" backend and don't obviously resemble each other.

**How to apply:** Before merging any PR that adds/modifies a `create_subprocess_exec` call invoking a claude binary in agent-runner, grep the whole `services/agent-runner/` tree for `claude_bin`/`claude` subprocess calls and verify each one sets `--model AGENT_MODEL` and `env=_subscription_env()`.