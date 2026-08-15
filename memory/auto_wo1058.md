---
name: factory-github-token-must-be-fine-grained-pat
description: Factory GitHub token in Keychain must be a fine-grained github_pat_ token; classic ghp_ and CLI gho_/ghu_ tokens are rejected
metadata:
  type: project
---

The factory's GitHub token (Keychain entry `dentroio-factory`/`GITHUB_TOKEN`) must be a fine-grained PAT (`github_pat_...`) scoped to specific repos with Contents/PR/Issues/Actions permissions. Classic PATs (`ghp_...`) and GitHub CLI OAuth tokens (`gho_...`, `ghu_...`) are explicitly rejected by `scripts/github_token.py` because they carry broad `repo`+`gist`/`read:org` scope, which is a security risk (AF-11/WO-1058).

**Why:** A gho_ token from `gh auth login` looks like a valid credential and "just works," but has far broader scope (including gist access) than the factory should hold — this was a discovered security gap, not an obvious API constraint.

**How to apply:** When setting up or debugging factory GitHub auth, always mint a fine-grained PAT via github.com/settings/personal-access-tokens (not `gh auth token` or a classic PAT), and store it with `scripts/github_token.py --store` (reads from stdin, never argv). Docs/scripts/tests all assert no mention of `read:org`, "classic PAT", or `repo, read:org` scopes — don't reintro