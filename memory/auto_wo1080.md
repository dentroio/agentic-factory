---
name: secrets-api-allowlist-invariant
description: PUT /api/secrets only accepts keys in secrets_policy.ALLOWED_SECRET_KEYS; new secret types must be added there explicitly
metadata:
  type: project
---

`PUT /api/secrets` in services/orchestrator/orchestrator.py does not accept arbitrary JSON keys — it delegates to `secrets_policy.apply_secret_updates()`, which rejects any key not in `ALLOWED_SECRET_KEYS` (a closed allowlist) and enforces per-key rules, e.g. `GITHUB_TOKEN` must start with `github_pat_` (fine-grained PAT); classic `ghp_`/`gho_` tokens are rejected.

**Why:** Before this fix (WO-1080), the endpoint blindly merged any incoming JSON key into the secrets store/Vault, so a caller could smuggle unrelated keys (e