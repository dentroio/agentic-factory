---
name: agent-runner-blocking-calls-need-double-timeout
description: All blocking/thread-offloaded calls in agent-runner (subprocess, SDK/HTTP clients) must be bounded by both a client-level timeout and an outer asyncio.wait_for using the shared ASK budget.
metadata:
  type: project
---

In `services/agent-runner`, any blocking call run via `asyncio.to_thread` (e.g. `anthropic.Anthropic(...).messages.create`, subprocess `.communicate()`) can hang `run_wo` indefinitely if not bounded on two levels: (1) the underlying client/library must be given an explicit timeout (e.g. `anthropic.Anthropic(api_key=..., timeout=float(ASK))`), and (2) the `asyncio.to_thread(...)` call must itself be wrapped in `asyncio.wait_for(..., timeout=ASK)` — a client-side timeout alone doesn't protect the async caller if the thread never returns control cleanly.

`ASK` is the shared 120s timeout budget imported from `proc.py` and is the project-standard constant for this pur