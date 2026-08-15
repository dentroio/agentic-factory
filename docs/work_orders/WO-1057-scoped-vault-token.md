# WO-1057 — Scoped Vault token for the orchestrator

**Created:** 2026-08-15
**Priority:** P1
**Effort:** S
**Services:** vault, orchestrator, docs
**Depends on:** WO-1056
**Status:** 🟡 In Progress

---

## Background

AF-10: Vault is administered with its root token and adds no privilege boundary.

1. The orchestrator reads `/vault/keys/root_token` from the same volume that holds the unseal key (`docker-compose.status.yml`). Anything that can read that mount can unseal Vault and fully administer it.
2. `make vault-export-keys` copies the unseal key and root token into the macOS Keychain with `security … -w "$TOKEN"`, putting both values in process argv (`ps`).
3. `tls_disable = true` is a separate finding; this WO does not turn TLS on (needs certs and URL changes).

## What to Build

1. Vault policy limited to KV v2 path `secret/data/factory/secrets`. On init and every start, issue an orphan periodic token with that policy and write it to a **separate** volume. Root token and unseal key stay on `vault-keys`, mounted only into the vault container.
2. Orchestrator loads `VAULT_TOKEN` or `/vault/keys/orchestrator_token`. Never read `root_token`.
3. `make vault-export-keys` backs up the unseal key via stdin (no `-w` argv). Do not copy the root token to Keychain; delete any existing `VAULT_ROOT_TOKEN` Keychain item.

Do **not** start the factory, rebuild running containers, or unpause dispatch.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Do not `make up`, `make restart`, or `make vault-export-keys` as part of this WO
- Conflict-magnet: `services/orchestrator/orchestrator.py` — change only the token load
- Existing deployments pick this up on the next vault container recreate (auto-init issues the scoped token after unseal)

## Acceptance Criteria

- [ ] Orchestrator compose mount is `vault-orch-token`, not `vault-keys`
- [ ] Orchestrator token loader never reads `root_token`
- [ ] `auto-init.sh` writes a policy-scoped token to `/vault/orch/orchestrator_token`
- [ ] `make vault-export-keys` does not pass secrets via `security -w`
- [ ] `make vault-export-keys` does not store `VAULT_ROOT_TOKEN`
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/vault/orchestrator-policy.hcl` | KV path policy |
| Create | `services/orchestrator/vault_auth.py` | Token load helper |
| Create | `scripts/keychain_set.py` | Keychain write from stdin |
| Create | `tests/unit/test_scoped_vault_token.py` | Guards |
| Modify | `services/vault/auto-init.sh` | Issue scoped token |
| Modify | `services/vault/Dockerfile` | Copy policy, orch dir |
| Modify | `docker-compose.status.yml` | Split volumes |
| Modify | `services/orchestrator/orchestrator.py` | Use helper |
| Modify | `Makefile` | Safe unseal-key export |

## Execution

- **Branch:** `wo/1057-scoped-vault-token`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(security): WO-1057 — scoped Vault token, root token offline`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1056
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI changes. Confirm `make ci-local` passes. Do not run `make up` or `make vault-export-keys` as part of verification (those would start services or touch Keychain).
