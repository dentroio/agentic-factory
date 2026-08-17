---
name: git-auth-no-token-in-argv
description: GitHub PAT auth for git commands must use GIT_CONFIG env vars, never embedded in the remote URL
metadata:
  type: project
---

Any subprocess git command (fetch/clone/push) that authenticates with a GitHub token must NOT embed the token in the URL passed as argv (e.g. `https://x-access-token:{token}@github.com/...`), since process argv is visible via `ps`/`docker top` to other users/containers on the host.

**Why:** WO-1081 fixed exactly this leak in orchestrator's `_sync_local_repo`. The fix pattern is in `services/orchestrator/git_https.py`: build a plain `https://github.com/{repo}.git` URL, and pass auth via `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=http.extraHeader`, `GIT_CONFIG_VALUE_0=Authorization: Bearer {token}` as subprocess env vars instead. Also redact the token from any captured stderr/exception text before logging (`redact_secret`), since git error messages can echo back the URL with credentials.

**How to apply:** Reuse `git_https.github_https_url()` / `git_fetch_env()` / `redact_secret()` helpers for any new git subprocess auth code rather than reinventing URL-embedded tokens. When writing tests for secret-handling code, use non-matching placeholder strings (not real-looking patterns like `github_pat_...` or