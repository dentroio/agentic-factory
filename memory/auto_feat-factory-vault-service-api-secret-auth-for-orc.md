---
name: orchestrator-bearer-auth-exempt-reads
description: The orchestrator's API_SECRET bearer auth middleware only enforces auth on write methods — GET/HEAD/OPTIONS are always public
metadata:
  type: project
---

The orchestrator's `_bearer_auth` middleware enforces `Authorization: Bearer <API_SECRET>` only on HTTP methods that are NOT `GET`, `HEAD`, or `OPTIONS`. Read endpoints remain unauthenticated by design.

**Why:** The status site and other consumers need to read orchestrator state without credentials, but all state-mutating calls (POST, PUT, DELETE) must be authenticated to prevent unauthorized agents or external callers from modifying factory state.

**How to apply:** When adding new orchestrator endpoints, classify them carefully: any endpoint that modifies state (even if it seems "informational") must be a POST/PUT/DELETE to get automatic auth enforcement. A new GET endpoint that triggers side effects would silently bypass auth — don't do it. When writing client code that calls orchestrator, only write-method calls need the `_orch_headers()` / `_AUTH` header; GET calls can omit it, but including it doesn't hurt.