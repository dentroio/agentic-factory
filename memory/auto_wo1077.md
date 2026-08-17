---
name: orchestrator-no-self-http-calls
description: Orchestrator must call its own endpoint handler functions directly, never HTTP-round-trip to its own API via localhost/127.0.0.1
metadata:
  type: project
---

Since AF-09 added auth middleware, any HTTP call from the orchestrator process to its own API (e.g. `http://localhost:{API_PORT}/...`) now returns 401 because the request carries no auth token. Previously this went unnoticed because callers (e.g. `dispatch_wo`, `reset_dispatch` PM tools, `pm_chat`'s backend-status lookup) ignored the response status and reported success regardless.

**Why:** Self-HTTP-calls are fragile — they depend on the server's own auth/middleware stack and add pointless network round-trips. Silent failures (ignored status codes) can make broken functionality look like it's working.

**How to apply:** When or