---
title: "Doc Writer Agent"
description: "Autonomous agent that keeps Clarion and factory wiki pages up to date, running daily via GitHub Actions"
last_verified: 2026-07-30
covers_wos:
  - WO-1052
doc_owner: factory-team
---

# Doc Writer Agent

**Adopters:** you do not need this workflow. It is how **this engine instance** keeps its wiki current and, optionally, a second product wiki. Using the factory with [the template](https://github.com/dentroio/agentic-factory-template) or [BYO](../adopters/BYO.md) does not require `doc-writer.yml`.

The factory can maintain documentation without a human triggering it. `scripts/doc_writer.py`, run by `.github/workflows/doc-writer.yml` once daily, finds stale or WO-uncovered wiki pages, reads relevant WO specs, and asks Claude to write updated content.

**Cost note:** each page costs roughly $0.10–0.20 (it stuffs up to 5 WO specs, up to 64KB each, into context) — paid even when Claude decides the page doesn't need changing. Clarion's wiki had 182 of 189 pages flagged "uncovered" (empty `covers_wos`) when this was tuned 2026-07-30 — most predate the `covers_wos` convention and don't actually need rewrites, they're just untagged. `max-pages` defaults to 2/run and the schedule is daily specifically to cap spend while that backlog exists, rather than burning through it at full throughput. Consider relaxing the "uncovered" trigger (only fire on real `last_verified` staleness) before raising `max-pages` back up.

It has two independent jobs in the same workflow:

| Job | Updates | Repo pushed to |
|-----|---------|----------------|
| `update-clarion-wiki` | `wiki/docs/` in `dentroio/clarion` | Clarion (cross-repo) |
| `update-factory-wiki` | `docs/wiki/` in this repo | This repo (self-maintenance) |

## What it does each run

1. Scans wiki pages for staleness (`last_verified` older than 180 days) or an empty `covers_wos` frontmatter field.
2. For each candidate page (up to `--max-pages`, default 2), gathers the WO specs and design docs that look relevant by keyword match.
3. Sends the current page + that context to Claude, with instructions to only document shipped (✅ Complete) features, never invent facts, and set `last_verified` to today.
4. If Claude's response doesn't parse as valid frontmatter (it sometimes wraps the answer in a ` ```markdown ` fence despite being told not to — `strip_code_fence()` handles this), or if it returns the page unchanged, the page is skipped.
5. Commits whatever changed.

## Required secret: `GH_PAT`

Both jobs need `GH_PAT` set on **this repo's** GitHub secrets — a fine-grained PAT with:

- **Repository access:** this repo (`dentroio/agentic-factory`) *and* the Clarion repo (`dentroio/clarion`), or whichever repo `CLARION_REPO` points at
- **Permissions:** Contents (Read and write), Pull requests (Read and write)

Set it in **Settings → Secrets and variables → Actions → New repository secret** on this repo.

Without it, the Clarion job fails immediately at checkout (`Input required and not supplied: token`) — silently, since a scheduled workflow's failures don't page anyone by default. This ran unnoticed for the agent's entire life until fixed 2026-07-29 (WO-1052 investigation): 0 of the last 30 scheduled runs had succeeded.

## Why the factory-wiki job needs a PAT, not just `GITHUB_TOKEN`

This repo's `main` branch requires a pull request for every change (no direct pushes, for any token). PRs opened using the default `GITHUB_TOKEN` don't trigger `pull_request`-event workflows — a GitHub anti-recursion protection — so the required `Unit Tests` check would never run and the PR would sit stuck forever. Worse, `GITHUB_TOKEN` is also blocked outright from creating PRs unless "Allow GitHub Actions to create and approve pull requests" is enabled repo-wide (Settings → Actions → General) — a guardrail intentionally left off here.

`GH_PAT` (a real user identity) sidesteps both: it's not subject to the anti-recursion rule, and it's not the "Actions bot" the create/approve restriction targets. The factory-wiki job commits to a branch, opens a PR, waits (up to 5 minutes, polling every 15s) for the `Unit Tests` check to report pass, then squash-merges and deletes its own branch. On failure or timeout, it leaves the PR open for a human instead of forcing anything.

## Manual runs

```
gh workflow run doc-writer.yml --repo dentroio/agentic-factory \
  -f max_pages=3 \
  -f page=operator/secure/groups.md \
  -f dry_run=true
```

All inputs are optional. `dry_run=true` runs the full pipeline and logs what would change, without committing.

## Related

- [GitHub Integrations](GitHub-Integrations) — the other automated GitHub write paths (WO creation, PR watchdog)
