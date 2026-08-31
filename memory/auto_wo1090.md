---
name: runner-auth-privilege-escalation-gap
description: /api/runners/register and /api/runners/{id}/revoke are reachable by any active runner token, not just the master API_SECRET
metadata:
  type: project
---

The orchestrator's `_bearer_auth` middleware (services/orchestrator/orchestrator.py) accepts either the master `API_