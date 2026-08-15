# WO-1058 — Fine-grained GitHub PAT only

**Created:** 2026-08-15
**Priority:** P1
**Effort:** S
**Services:** docs, scripts
**Depends on:** WO-1057
**Status:** 🟡 In Progress

---

## Background

AF-11: the factory documented and accepted a classic PAT with `repo` + `gist`. Classic `repo` writes every repository the owner can reach. `gist` is unused and is an exfiltration channel. Keychain currently holds a GitHub CLI `gho_` OAuth token with those scopes even though a fine-grained PAT already exists for `dentroio/clarion` and `dentroio/agentic-factory`.

GitHub does not offer a **Checks** permission on fine-grained PATs (Apps only). The factory only reads check runs; Contents is enough. Do not document Checks as a required PAT permission.

## What to Build

1. Classify GitHub tokens by prefix. Factory Keychain accepts only `github_pat_`. Reject `ghp_` (classic) and `gho_` (GitHub CLI OAuth).
2. `agent-setup.sh` refuses to store a rejected token. `scripts/github_token.py --store` writes a validated token to Keychain via stdin (no `security -w` argv).
3. Update `.env.example`, service examples, and operator wiki: fine-grained PAT, selected repos, Contents + Pull requests + Issues + Actions. No `gist`. No `repo` + `read:org`.

Do **not** start the factory, run `make agent-setup` (it starts compose), or unpause dispatch. Do not put a live token in the repo or in chat.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Operator still must paste the existing `github_pat_` into Keychain after this merges
- Conflict-magnet: none. Do not edit `orchestrator.py`

## Acceptance Criteria

- [ ] `agent-setup.sh` and `.env.example` do not require `repo` + `read:org` or `gist`
- [ ] Classic `ghp_` and OAuth `gho_` prefixes are rejected
- [ ] Fine-grained `github_pat_` prefix is accepted
- [ ] Wiki Getting-Started and Dashboard-Guide match
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `scripts/github_token.py` | Classify / reject / store |
| Create | `tests/unit/test_github_token.py` | Guards |
| Modify | `scripts/agent-setup.sh` | Prompt + reject |
| Modify | `.env.example` | Fine-grained placeholder |
| Modify | `services/*/ .env.example` | Same |
| Modify | `docs/wiki/Getting-Started.md` | Operator docs |
| Modify | `docs/wiki/Dashboard-Guide.md` | Operator docs |

## Execution

- **Branch:** `wo/1058-fine-grained-github-pat`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(security): WO-1058 — require a fine-grained GitHub PAT`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1057
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI changes. Confirm `make ci-local` passes. Do not run `make agent-setup` or `make up`. After merge, store the existing fine-grained token with `pbpaste | python3 scripts/github_token.py --store` (token on stdin, never in argv or chat).
