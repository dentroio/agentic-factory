---
name: draft-server-bearer-auth-required
description: All agent-runner HTTP endpoints require API_SECRET bearer auth; orchestrator must send it on every call, enforced by a source-scanning test
metadata:
  type: project
---
The host draft server (`services/agent-runner/draft_server.py`) now requires `Authorization: Bearer <API_SECRET>` on every request (GET/POST/PUT/DELETE), via `_require_auth()` calling `draft_auth.is_authorized()`. This reversed an earlier decision (WO before this one) that loopback binding alone was sufficient — it wasn't, since any local process could still hit `/dispatch`.

**Why:** `tests/unit/test_draft_server_auth.py::test_orchestrator_sends_bearer_to_the_runner` scans `orchestrator.py` source text for every `f"{AGENT_R