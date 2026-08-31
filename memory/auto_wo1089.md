---
name: orchestrator-multi-repo-scoping
description: Multi-repo dispatch in orchestrator.py — repo config precedence and per-repo isolation of conflict guards
metadata:
  type: project
---

The orchestrator dispatches WOs across multiple repositories, not just `GITHUB_REPO`. Configured repositories come from three sources merged in `_get_configured_repos()`, in this precedence order: (1) primary `GITHUB_REPO`/`WO_PATH`/`PLAN_PATH` env vars, (2) `/config/factory-config.json` projects list, (3) `SECONDARY_REPOS` env var. Dispatch queues, runtime plan overlays, and `_poll_github()` operate concurrently across all repositories, with `files_in_flight_by_repo` and `services_in_flight_by_repo` scoping collision checks per repository so same-named files in different repositories do not falsely block each other.
