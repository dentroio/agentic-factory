---
name: factory-profile-duplicated-across-services
description: factory_profile.py is copy-pasted identically into services/agent-runner and services/orchestrator (no shared package) — must be updated in both places
metadata:
  type: project
---

`factory_profile.py` (the product-agnostic profile loader for `factory.yaml`) exists as two byte-identical copies: `services/agent-runner/factory_profile.py` and `services/orchestrator/factory_profile.py`. There is no shared package importing one from the other — each service vendors its own copy because they're deployed/run independently.

**Why:** The runner and orchestrator are separate deployables and don't share a common Python package path, so a shared module would require packaging work that wasn't done here. Introduced in PR #294 which removed Clarion hardcoding via this profile loader.

**How to apply:** Any future fix or feature to profile loading (new fields