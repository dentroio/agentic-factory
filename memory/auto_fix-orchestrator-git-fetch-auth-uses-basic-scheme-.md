---
name: git-https-auth-requires-basic-not-bearer
description: GitHub's smart-HTTP git transport requires Basic auth scheme (base64 "x-access-token:<PAT>"), not Bearer, or fetches silently fail
metadata:
  type: project
---

GitHub's git-over-HTTPS smart transport only accepts `Authorization: Basic base64(username:PAT)` — sending `Authorization: Bearer <token>` gets a 401 with `WWW-Authenticate: Basic`, which git then reports as a misleading "could not read Username ... terminal prompts disabled" error instead of a clean auth failure. This silently broke `_sync_local_repo()` in the orchestrator for an unknown period (every poll cycle failed to refresh origin/main or origin/wo/*), and the failure mode gave no indication auth was the actual problem.

**Why:** REST/GraphQL API calls to GitHub do accept Bearer tokens, so it's easy to assume the git HTTP transport works the same way — it doesn't. This is GitHub-specific behavior, not a general git constraint.

**How to apply:** When constructing `Authorization` headers for `git fetch`/`clone`/`push` over HTTPS to GitHub (e.g. via `GIT_CONFIG_KEY_0=http.extraHeader`), always use `Basic <base64(any-username:PAT)>` (e.g. `x-access-token:<PAT>`), never `Bearer <PAT>`. If you see git fail with "could