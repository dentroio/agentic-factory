---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Adopting the factory

**agentic-factory** is an **engine**: dashboard, orchestrator, agent runner, and GitHub Actions that keep *the engine* healthy.

Your **product** is a separate GitHub repository. The engine already supports any repo via `GITHUB_REPO`. You do not need access to Dentro’s (or anyone else’s) private application.

## Mental model

```text
┌─────────────────────────────┐     GITHUB_REPO=you/app
│  agentic-factory (engine)   │ ──────────────────────────►  you/app (product)
│  localhost:8099 dashboard   │     reads WO specs           Work Orders, code, PRs
│  localhost:8100 API         │     LOCAL_REPO_PATH          factory.yaml, CI
│  launchd agent-runner       │ ──────────────────────────►  local clone of you/app
└─────────────────────────────┘
```

| Repo | What it is | What you do |
|------|------------|-------------|
| [dentroio/agentic-factory](https://github.com/dentroio/agentic-factory) | Engine | Clone, `make agent-setup`, `make up`, `make agent-install` |
| Your product | Application + WO specs | [Use the template](https://github.com/dentroio/agentic-factory-template) **or** [BYO](../adopters/BYO.md) |

**Do not** click “Use this template” on **agentic-factory** to start an app. That copies Docker/Vault/orchestrator. The product starter is [agentic-factory-template](https://github.com/dentroio/agentic-factory-template).

## Paths the engine expects in the product

| Path | Role |
|------|------|
| `docs/project_management/work_orders/` | Work Order markdown specs |
| `docs/factory/runs/` | Claim JSON files on WO branches |
| `factory.yaml` (repo root) | Verify command, UI URL, Compose project, patterns — see [Product Profile](Product-Profile) |
| `AGENT_PROCESS.md` (or copy of adopters PROCESS) | How agents behave in *that* repo |
| Optional `docs/factory/PLAN.json` | Dispatch queue extras |

Contract details (labels, branches, secrets): [CONTRACT.md](../adopters/CONTRACT.md).

## GitHub Actions: where they live

| Location | Purpose |
|----------|---------|
| Engine `.github/workflows/` | Engine CI and specialists. **Leave them alone.** |
| [templates/github/](../../templates/github/) | Optional copies to paste into the **product** |
| Template `github-workflows-optional/` | Same copies, vendored beside the demo |

## Adoption paths

| Path | When | Start here |
|------|------|------------|
| **Template demo** | First time, learning the loop | [Getting Started](Getting-Started) + template WO-001 |
| **BYO** | Existing codebase | [BYO.md](../adopters/BYO.md) + [Product Profile](Product-Profile) |
| **Essays** | Want the “why” | [docs/blog](../blog/README.md) |

## Checklist (print this)

- [ ] Product repo exists (template or BYO) with WO folder + labels + branch protection  
- [ ] Product has `factory.yaml` with a real `verify:` command  
- [ ] Engine cloned; `make agent-setup` with product `owner/name`  
- [ ] `LOCAL_REPO_PATH` points at the product clone  
- [ ] Dashboard shows product WOs; runner installed  
- [ ] One WO completed with human UI verify before commit  

## Next

→ [Getting Started](Getting-Started)
