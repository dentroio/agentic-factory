---
name: orchestrator-multi-repo-polling-invariants
description: Orchestrator poll() multi-repo fetch invariants — LOCAL_REPO_MOUNT is primary-repo-only, and configured_projects must be loaded before combining specs/branches/PRs
metadata:
  type: project
---

`poll()` in `services/orchestrator/orchestrator.py` must load `configured_projects = _get_configured_repos()` and gather parallel `specs_results` / `branch_results` / `pr_results` before the multi-repo combine loop. Leaving those names undefined crashes every 60s poll with `NameError`, so `/data/orchestrator.json` is never written and `/api/plan` stays empty.

`_fetch_active_branches` may use `LOCAL_REPO_MOUNT` only when `repo == GITHUB_REPO`. Secondary repos must hit the GitHub API — the local mount is the primary product checkout, not every configured project.
