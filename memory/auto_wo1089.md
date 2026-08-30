---
name: orchestrator-multi-repo-scoping
description: Multi-repo dispatch in orchestrator.py — repo config precedence and per-repo isolation of conflict guards
metadata:
  type: project
---

The orchestrator now dispatches WOs across multiple repos, not just GITHUB_REPO. Configured repos come from three sources merged in `_get_configured_repos()`, in this precedence order: (1) primary `GITHUB_REPO`/`WO_PATH`/`PLAN_PATH` env vars, (