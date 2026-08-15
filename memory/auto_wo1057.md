---
name: vault-orchestrator-scoped-token
description: Orchestrator must use a policy-scoped Vault token from a dedicated volume/file, never the root token
metadata:
  type: project
---

The orchestrator authenticates to Vault with a scoped periodic token (policy `orchestrator`, limited to `secret/data/factory/secrets` and `secret/metadata/factory/secrets`), read via `services/orchestrator/vault_auth.py::load_vault_token()` from `VAULT_TOKEN` env or `/vault/keys/orchestrator_token`. It must never read `root_token`, and the orchestrator container must not mount the `vault-keys` volume (which holds root/unseal keys) — only the separate `vault-orch-token` volume mounted at `/vault/keys` inside the orchestrator (source file is `/vault/orch` in the vault container, written by `services/vault/auto-init.sh`).

Also, any script writing secrets to macOS Keychain must use `scripts/keychain_set.py` (reads secret from stdin via ctypes Security.framework calls) instead of `security add-generic-password -w <secret>`, because `-w` argv secrets are visible to any local `ps`.

**Why:** WO-1057/AF-10 hardened against a root-token leak: previously the orchestrator read `root_token` directly from the shared vault keys volume, giving it full Vault access and requiring root secrets to be in a container it doesn't need full access to. Similarly, passing secrets via `-w` on argv leaked