# WO-1081 — Do not put the GitHub token in git argv

**Created:** 2026-08-16
**Priority:** P0
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1080
**Status:** 🟡 In Progress

---

## Background

AF-12 remainder: `_sync_local_repo` fetches Clarion with
`https://x-access-token:{token}@github.com/...`. That URL is process argv.
`docker top` / `ps` can read the fine-grained PAT. Git stderr is also printed
on failure and can echo the same URL.

Do **not** start the factory or unpause.

## What to Build

1. Fetch `https://github.com/{repo}.git` with auth in `GIT_CONFIG_*` env, not argv.
2. Redact the token from git stderr before logging.
3. Unit tests. Do not print a live token.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — `_sync_local_repo` body and one import
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner
- Do not write the token into `.git/config` on the Clarion mount

## Acceptance Criteria

- [ ] `x-access-token:` is gone from orchestrator source
- [ ] Fetch argv is a token-free GitHub HTTPS URL
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/git_https.py` | Env auth + redact |
| Modify | `services/orchestrator/orchestrator.py` | `_sync_local_repo` |
| Create | `tests/unit/test_git_fetch_no_token_argv.py` | Guards |
| Create | `docs/work_orders/WO-1081-git-fetch-no-token-argv.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1080 complete, 1081 in progress |

## Execution

- **Branch:** `wo/1081-git-fetch-no-token-argv`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1081 — do not put the GitHub token in git argv`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1080
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on. Confirm container source has no `x-access-token:`. Do not print process listings that might contain a token.
