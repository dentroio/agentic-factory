---
title: "Doc Writer Agent"
description: "Optional engine workflow that refreshes wiki pages; adopters do not need it"
last_verified: 2026-08-31
covers_wos:
  - WO-1052
doc_owner: factory-team
---

# Doc Writer Agent

**Adopters: skip this page** unless you are operating a long-lived fork of **this engine** and want automated wiki rewrites. Pointing the factory at the [template](https://github.com/dentroio/agentic-factory-template) or a [BYO](../adopters/BYO.md) product does **not** require `doc-writer.yml`.

The workflow `.github/workflows/doc-writer.yml` (daily + manual) finds stale or WO-uncovered pages under `docs/wiki/`, gathers related WO specs, and asks Claude to propose updates.

**Cost note:** each page costs roughly $0.10–0.20 (large WO context), paid even when Claude decides no change is needed. Defaults are conservative (`max-pages` ≈ 2, once daily).

## Jobs

| Job | Updates | When it runs |
|-----|---------|--------------|
| Product wiki (optional) | `wiki/docs/` in a **second** repo | Only if repo variable `CLARION_REPO` (legacy name) is set to `owner/name`. **Unset = skip.** Stranger forks must leave it unset so they never push to someone else’s product. |
| Factory wiki (self) | `docs/wiki/` in this engine | Always available; opens a PR (main is protected) |

## Required secret: `GH_PAT`

Fine-grained PAT on **this engine repo** with Contents + Pull requests write. If you enable the optional product-wiki job, the same PAT (or another) must also reach that product repo.

Without `GH_PAT`, jobs that push fail at checkout — scheduled failures are easy to miss. See [GitHub Integrations](GitHub-Integrations).

## Why the factory-wiki job needs a PAT

This engine’s `main` requires a PR. PRs opened with the default `GITHUB_TOKEN` often do not retrigger required checks (anti-recursion). A user-scoped `GH_PAT` opens a normal PR, waits for **Unit Tests**, then squash-merges (or leaves the PR open on failure).

## Manual runs

```bash
gh workflow run "Doc Writer — Update Product + Factory Wikis" --repo OWNER/agentic-factory \
  -f max_pages=3 \
  -f dry_run=true
```

## Related

- [GitHub Integrations](GitHub-Integrations)
- [Adopting](Adopting) — you do not need this for a normal product adoption
