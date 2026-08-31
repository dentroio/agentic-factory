---
name: runner-auth-and-identity-binding
description: Per-runner authentication, SHA-256 token hashing, and zero-trust identity verification on work order lifecycle endpoints
metadata:
  type: project
---

The orchestrator's `_bearer_auth` middleware (`services/orchestrator/orchestrator.py` & `runner_auth.py`) accepts both the master `API_SECRET` and per-runner tokens (`rn_...`). When a request authenticates via a runner token, `_enforce_agent_identity` strictly verifies that the caller's requested `agent` matches the registered identity bound to that token across `/api/claim`, `/api/checkin`, `/api/validate`, and `/api/complete`. Furthermore, administrative endpoints (`/api/runners/register` and `/api/runners/{id}/revoke`) enforce master-only access.
