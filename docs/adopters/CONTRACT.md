# CONTRACT.md — what the factory engine expects from a product repo

Set `GITHUB_REPO` (or dashboard Settings) to your product `owner/name`. The dashboard and orchestrator read GitHub; the agent runner uses `LOCAL_REPO_PATH` for a local clone of that same repo.

This document names the **shapes** already supported. You do not need to change engine services to “enable” them.

## Paths in the product repo

| Path | Role |
|------|------|
| `docs/project_management/work_orders/WO-NNN-slug.md` | WO spec markdown (override with `WO_SPECS_DIR` if needed) |
| `docs/factory/runs/WO-NNN.json` | Claim file on the WO branch |
| `factory.yaml` | Product profile — verify, UI, Compose, patterns ([wiki](../wiki/Product-Profile.md)) |
| `docs/factory/patterns.md` | Optional patterns file referenced by `factory.yaml` |
| `docs/factory/PLAN.json` | Optional dispatch queue |
| `AGENT_PROCESS.md` | Process for agents working **in this product** |

## Branches

| Prefix | Meaning |
|--------|---------|
| `wo/NNN-slug` | Implementation of work order NNN |
| `fix/short-description` | Hotfix |
| `docs/short-description` | Docs-only |

## GitHub labels (on the **product** repo)

| Label | Used by |
|-------|---------|
| `new-wo` | Planning agent drafts a spec from an issue |
| `agent-pr` | CI auto-fix / review applier may commit back |
| `pm-sync` | Bookkeeping PRs that must not retrigger mark-done |

## Secrets (on the **product** repo, only if you paste those workflows)

| Secret | Used by |
|--------|---------|
| `ANTHROPIC_API_KEY` | Planning agent, AI review |
| `GH_PAT` | Auto-update PRs so CI re-triggers (optional) |

## Status checks

Protect `main` with a required check you actually run (template uses **CI**). The factory does not replace your language-specific CI — put the command agents must pass in `factory.yaml` → `verify:`.

## Engine vs product

| This repo (`agentic-factory`) | Product (`GITHUB_REPO`) |
|-------------------------------|-------------------------|
| Status site, orchestrator, runner | WO specs, application code, PRs |
| Keep existing workflows as-is | Optional paste-ins from `templates/github/` |
| Prefs: `GITHUB_REPO` + `LOCAL_REPO_PATH` | Root `factory.yaml` |
