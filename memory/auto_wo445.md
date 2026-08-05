---
name: orchestrator-requires-bearer-auth-on-all-methods
description: orchestrator now requires API_SECRET and a Bearer token on every request including GET; any new code calling its API must send the header or get 401
metadata:
  type: project
---

The orchestrator's `_bearer_auth` middleware (services/orchestrator/orchestrator.py) now requires a valid `Authorization: Bearer {API_SECRET}` header on **every** request, GET included — not just writes. The app also refuses to start at all if `API_SECRET` is unset (`RuntimeError` at import time). This was a deliberate fix for AF-09: previously GET was exempt unconditionally and API_SECRET was empty in the deployed .env, so the live orchestrator was fully unauthenticated.

**Why:** Any new consumer of the orchestrator API (new agent script, new status-site route, a new daemon) that doesn't send this header will get