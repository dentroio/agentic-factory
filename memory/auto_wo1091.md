---
name: product-setup-host-only-and-path-guard
description: agent-runner (not orchestrator/Docker) owns product wiring; LOCAL_REPO_PATH is restricted to under $HOME unless overridden
metadata:
  type: project
---

`services/agent-runner/product_setup.py` (host-side, launched