---
name: orchestrator-auth-middleware-non-get-only
description: Orchestrator's bearer-auth middleware only guards non-GET requests; never expose secrets via GET routes
metadata:
  type: project
---

Orchestrator's auth middleware only checks bearer auth on non-GET requests. GET /api/secrets deliberately only returns presence booleans (never raw values) because it's effectively unauthenticated. Any new endpoint that must return a raw secret (e.g. the Anthropic API key) has to use POST (or another non-GET verb) specifically so it passes through the auth check — using GET would silently expose the secret with no auth.

**Why:** This is not enforced by any check or comment near the middleware itself; a fresh agent adding a "read this secret" endpoint would naturally reach for GET and unknowingly bypass auth.

**How to apply:** When adding any orchestrator endpoint that returns a raw secret/credential (not just a boolean/presence flag), use POST/PUT/DELETE, never GET. Also remember: other in-stack services (e.g. agent-runner) can't read orchestrator's env vars or Vault directly — they must resolve secrets through such an internal orchestrator endpoint, mirroring orchestrator's own env-first-then-Vault precedence (see `_get_anthropic_key()`).