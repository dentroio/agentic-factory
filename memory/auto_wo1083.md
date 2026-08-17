---
name: runner-agent-endpoints-pause-and-allowlist
description: All /api/runner/agents/* endpoints must allowlist agent names and refuse actions that start a runner while paused
metadata:
  type: project
---

The orchestrator's runner-agent HTTP endpoints (`configure_runner_agent`, `start_runner_agent`, `stop_runner_agent`, `remove_runner_agent`) previously proxied requests to the host runner (AGENT_RUNNER_URL) without validating the `name` param or checking pause state, even though `claim` already enforced pause via a 423. This meant pause could be bypassed by directly hitting the runner-start/configure endpoints.

**Why:** Pause is a system-wide safety invariant (used e.g. during incidents/manual intervention) and every code path that can trigger a LaunchAgent to actually start work must check it — not just the primary work-claiming path. Each new endpoint that can lead to "an agent starts working" is a potential pause-bypass unless explicitly guarded.

**How to apply:** When adding/modifying any orchestrator endpoint that can result in a runner agent starting (directly via `/start`, or indirectly via `configure` with `start: true`), call `require_runner_agent(name)` from `services/orchestrator/runner_agents.py` to allowlist the agent name (`claude`, `cursor`, `codex`, `gemini` only), and call `_refuse_if_paused()` before proxying to `AGENT_RUNNER_URL`. Configure bodies