# WO-1056 — Do not write factory secrets to disk or logs

**Created:** 2026-08-15
**Priority:** P1
**Effort:** S
**Services:** agent-runner, docs
**Depends on:** WO-1055
**Status:** 🟡 In Progress

---

## Background

AF-12: factory secrets land in cleartext on disk and in stdout.

1. `make up` and `scripts/agent-setup.sh` write Keychain secrets to `.env.runtime` at the repo root, then delete it. If compose fails in between, the file stays. Mode is umask-default (often world-readable).
2. `scripts/publish_to_gdrive.py --auth` prints `GDRIVE_REFRESH_TOKEN` and `GDRIVE_CLIENT_SECRET` to stdout — CI logs if ever run in Actions.
3. `draft_server.py` writes API keys into LaunchAgent plists created as `-rw-r--r--`, and builds XML with an f-string so `<` / `&` in a value corrupts the file. `agent-install.sh` has the same 0644 plist problem.

## What to Build

1. `scripts/compose-with-env.sh` — write the env file with `mktemp` under `$TMPDIR`, `chmod 600`, `trap` delete on EXIT, then `docker compose --env-file`. `Makefile` `up`/`restart` and `agent-setup.sh` call it. No `.env.runtime` in the repo.
2. `publish_to_gdrive.py --auth` writes tokens to `~/.config/factory-agent/gdrive-oauth.env` mode 0600 and prints the path, not the values.
3. `draft_server.py` writes plists via `plistlib` (escaped XML) and `os.open(..., 0o600)`. Same chmod in `agent-install.sh`.

Do **not** start the agent runner or unpause the factory.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Do not `make agent-start` or `make up` as part of this WO
- Conflict-magnet: `Makefile` `up` target is used by operators; keep the dashboard URL echo

## Acceptance Criteria

- [ ] `Makefile` `up` and `scripts/agent-setup.sh` do not write `.env.runtime` in the repo
- [ ] compose env file is created 0600 in a temp dir and deleted on exit
- [ ] `publish_to_gdrive.py` does not print refresh token or client secret values
- [ ] New/updated LaunchAgent plists from `draft_server` are mode 0600
- [ ] Plist values containing `<` and `&` round-trip via plistlib
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `scripts/compose-with-env.sh` | Temp 0600 env file for compose |
| Create | `tests/unit/test_secrets_not_on_disk.py` | Guards |
| Modify | `Makefile` | `up` / `restart` use the helper |
| Modify | `scripts/agent-setup.sh` | Use the helper |
| Modify | `scripts/factory-env.sh` | Usage comment |
| Modify | `scripts/publish_to_gdrive.py` | No secret stdout |
| Modify | `services/agent-runner/draft_server.py` | Secure plist write |
| Modify | `scripts/agent-install.sh` | chmod 600 plists |

## Execution

- **Branch:** `wo/1056-secrets-not-on-disk`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(security): WO-1056 — stop writing factory secrets to disk and logs`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1055
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI changes. Confirm `make ci-local` passes. Do not run `make up` or `make agent-install` as part of verification (those would start services).
