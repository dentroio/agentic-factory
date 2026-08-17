# WO-1080 — Allowlist keys on PUT /api/secrets

**Created:** 2026-08-16
**Priority:** P0
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1079
**Status:** 🟡 In Progress

---

## Background

AF-28 remainder: `put_secrets` parses a raw JSON body and writes every key into Vault (or `secrets.json`) with no allowlist. `API_SECRET` and arbitrary env-shaped names can land next to the factory's real credentials. `GITHUB_TOKEN` is not checked against the fine-grained PAT rule from WO-1058.

Do **not** start the factory or unpause.

## What to Build

1. `secrets_policy.apply_secret_updates` — known keys only, strings only, `github_pat_` for `GITHUB_TOKEN`.
2. `put_secrets` uses it and returns 400 on rejection.
3. File fallback uses `atomic_write_json`.
4. Unit tests. Do not PUT a real token on the live factory.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — `put_secrets` body and one import
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner
- Live verify with a rejected key only — do not overwrite Vault secrets

## Acceptance Criteria

- [ ] Unknown keys (including `API_SECRET`) return 400 and are not stored
- [ ] Classic `ghp_` / OAuth `gho_` GitHub tokens return 400
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/secrets_policy.py` | Allowlist + validation |
| Modify | `services/orchestrator/orchestrator.py` | `put_secrets` uses the policy |
| Create | `tests/unit/test_secrets_allowlist.py` | Guards |
| Create | `docs/work_orders/WO-1080-secrets-allowlist.md` | This spec |
| Modify | `docs/project_management/PROGRESS.md` | 1079 complete, 1080 in progress |

## Execution

- **Branch:** `wo/1080-secrets-allowlist`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1080 — allowlist keys on PUT /api/secrets`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1079
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on. `PUT /api/secrets` with `{"NOT_A_KEY":"x"}` returns 400. Do not write a live token.
