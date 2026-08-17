---
name: agent-config-put-allowlist-required
description: PUT /api/config on the orchestrator must only accept allowlisted keys, never raw merge of incoming JSON
metadata:
  type: project
---

`PUT /api/config` (agent_config.json) previously did `{**existing, **incoming}` with arbitrary client JSON, letting any key (e.g. `automation_model`, or unknown reviewer slots/backends) get written to disk and take effect. This was fixed in WO-1082 via `services/orchestrator/agent_config_policy.py`, which enforces an explicit `ALLOWED_CONFIG_KEYS` set (`preferred`, `name`, `timeout`, `force_cross_llm_review`, `reviewers`), validates `reviewers` slots/backends against fixed allowlists, bounds `timeout` to [60, 86400], and requires `name` to match a hostname-safe regex.

**Why:** Config-writing endpoints that merge unvalidated JSON are a recurring injection vector in this codebase (see also the analogous `secrets_policy.py` pattern for `/api/secrets`). Silent acceptance of unknown keys (like `automation_model`) can let an attacker change which model/backend is used for automation.

**How to apply:** Any new field added to agent config must be added explicitly to `ALLOWED_CONFIG_KEYS` in `agent_config_policy.py` with its own validator — do not widen the endpoint by merging raw request JSON. Writes to `AGENT_CONFI