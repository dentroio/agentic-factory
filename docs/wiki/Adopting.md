---
title: "Adopting the factory"
description: "Two-repo model: run this engine, point GITHUB_REPO at any product (template or BYO)"
last_verified: 2026-08-30
covers_wos: []
doc_owner: factory-team
---

# Adopting the factory

This repository (**agentic-factory**) is the **engine**: dashboard, orchestrator, runner, and the GitHub Actions that keep *this* factory healthy.

Your application lives in a **different** GitHub repo. The engine already supports that via `GITHUB_REPO` (or dashboard **Settings**). You do not need any other private product.

## Two repositories

| Repo | What it is | What you do |
|------|------------|-------------|
| [dentroio/agentic-factory](https://github.com/dentroio/agentic-factory) | Engine (this repo) | Clone, `make agent-setup`, `make up` |
| Your product | Code + Work Order specs | [Use the template](https://github.com/dentroio/agentic-factory-template) **or** [bring your own repo](../adopters/BYO.md) |

Do **not** click “Use this template” on **agentic-factory** to start a product. That copies the engine (Docker services, Vault, orchestrator). The product template is [agentic-factory-template](https://github.com/dentroio/agentic-factory-template).

## Paths in the product repo

The dashboard looks in the repo named by `GITHUB_REPO`:

- `docs/project_management/work_orders/` — WO specs
- `docs/factory/runs/` — claim files
- Optional: `docs/factory/PLAN.json`

Generic process for agents in *that* repo: [docs/adopters/PROCESS.md](../adopters/PROCESS.md) (copy to `AGENT_PROCESS.md`). Contract (labels, branches, secrets): [CONTRACT.md](../adopters/CONTRACT.md).

## GitHub Actions

| Where | What |
|-------|------|
| This engine’s `.github/workflows/` | Factory’s own CI and specialists. **Leave them.** |
| [templates/github/](../../templates/github/) | Copies to paste into **your product** if you want planning-agent, AI review, etc. |
| Template repo `github-workflows-optional/` | Same copies, already vendored next to a demo CI |

## Next

- [Getting Started](Getting-Started) — engine up + first WO on the product repo
- [Bring your own repo](../adopters/BYO.md) — existing codebase
- [Essay series](../blog/README.md) — why Work Orders look like this
