---
name: factory-smoke-orchestrator-401-is-healthy
description: factory_smoke.py treats orchestrator HTTP 401 (no token) as a passing health check, not a failure
metadata:
  type: project
---

`scripts/factory_smoke.py` (post-deploy smoke checks) accepts HTTP 401 from the orchestrator's `/health` endpoint as success when no bearer token is supplied — `/health` is behind auth middleware, so 401 just proves the process is up and answering. Only a genuinely unreachable connection or non-(200|401) status is treated as a failure. If a token is provided, 200 is required.

**Why:** Orchestrator `/health` requires `Authorization: Bearer <API_SECRET>`. CD smoke