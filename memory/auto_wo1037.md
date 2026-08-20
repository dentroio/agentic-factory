---
name: orchestrator-proxy-routes-require-auth-header
description: All status-site proxy calls to the orchestrator must include _orch_headers() or they silently 401
metadata:
  type: project
---

Since WO-1037, the orchestrator's bearer-auth middleware requires `Authorization: Bearer` on every request, including GETs and SSE streams. Any new proxy route in services/status-site/main.py that calls the orchestrator (via httpx) must pass `headers=_orch_headers()` explicitly — it's not applied automatically by any shared client, so it's easy to add a new proxy call and forget it. This exact bug (missing header on `/api/runner/log/stream` → `/api/log/stream`) silently broke the Live Feed for an unknown period, since the failure mode is a 401 on the backend call, not a visible frontend error.

**Why:** There's no global httpx client wrapper enforcing auth headers; each call site must add them individually, and missing headers fail silently (SSE stream just appears empty/broken) rather than crashing loudly.

**How to apply:** When adding or modifying any status-site route that proxies to `ORCHESTRATOR_URL`, always pass `headers=_orch_headers()` to the httpx call, and verify against the live orchestrator (not just local/mocked) that it doesn't 401.