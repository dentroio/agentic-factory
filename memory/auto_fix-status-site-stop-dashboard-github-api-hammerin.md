---
name: status-site-github-rate-limit-invariants
description: Constraints on GitHub API usage in services/status-site to avoid rate-limit storms
metadata:
  type: project
---

The status-site dashboard has strict invariants around GitHub API usage, established after a rate-limit incident:

1. **Never fan out per-PR check-run calls (`gh.get_pr_checks`) on Overview/PM board loads** (`_load_open_prs`). That endpoint costs 2 API calls per PR and, multiplied by auto-refresh + multiple board views, was the main cause of rate-limit exhaustion. CI detail belongs only on `/ci`, and even there it's capped via `MAX_PR_CHECK_FETCH` (currently 8 PRs).
2. **`LOCAL_REPO_MOUNT` can drift from the default branch** (e.g. when mounted on a