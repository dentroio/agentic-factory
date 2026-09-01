---
name: runner-admin-endpoints-master-only
description: Runner registration/revocation endpoints require master-level auth via request.state.is_master
metadata:
  type: project
---

Runner token management endpoints (`POST /api/runners/register`, `POST /api/runners/{id}/revoke`) must check `getattr(request.state, "is_master", False)` and raise 403 if false — these were previously callable by any authenticated caller, not just master, which is a security gap since runner tokens grant agent execution access.

**Why:** `request.state.is_master` is set upstream (auth middleware) to distinguish master-level callers from regular agent/runner callers; endpoints don't enforce this by default, so any new admin-style route must opt in explicitly.

**How to apply:** When adding new orchestrator endpoints that manage sensitive resources (tokens, runners, credentials), add the `request: Request` param and explicit `if not getattr(request