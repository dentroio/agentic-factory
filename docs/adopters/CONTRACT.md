# CONTRACT.md — what the factory engine already expects

The dashboard and orchestrator read GitHub. They do **not** require a private product repo. Set `GITHUB_REPO` (or the dashboard Settings equivalent) to **your** `owner/name`.

This document names the **shapes** already in use. Do not change factory services to “support” them — they already do.

## Paths in the target repo

| Path | Role |
|------|------|
| `docs/project_management/work_orders/WO-NNN-slug.md` | WO spec markdown (override with repo variable `WO_SPECS_DIR` if needed) |
| `docs/factory/runs/WO-NNN.json` | Claim file on the WO branch |
| `docs/factory/PLAN.json` | Optional dispatch queue |

## Branches

| Prefix | Meaning |
|--------|---------|
| `wo/NNN-slug` | Implementation of work order NNN |
| `fix/short-description` | Hotfix |
| `docs/short-description` | Docs-only |

## GitHub labels (create on the **target** repo)

| Label | Used by |
|-------|---------|
| `new-wo` | Planning agent drafts a spec from an issue |
| `agent-pr` | CI auto-fix / review applier may commit back |
| `pm-sync` | Bookkeeping PRs that must not retrigger mark-done |

## Secrets (on the **target** repo, if you enable those workflows)

| Secret | Used by |
|--------|---------|
| `ANTHROPIC_API_KEY` | Planning agent, AI review |
| `GH_PAT` | Auto-update PRs so CI re-triggers (optional) |

## Status checks

Protect `main` with a required check you actually run (often named **PR Gate**). The factory does not replace your language-specific CI.

## Engine vs target

| This repo (`agentic-factory`) | Target repo (`GITHUB_REPO`) |
|-------------------------------|-----------------------------|
| Status site, orchestrator, runner | WO specs, code, PRs |
| Keep existing workflows as-is | Copy paste-ins from `templates/github/` if you want planning-agent etc. |
