---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-09-03
covers_wos:
  - WO-1008
  - WO-1052
  - WO-1058
doc_owner: factory-team
---

# Adopting the factory

**agentic-factory** is an **engine**: dashboard, orchestrator, agent runner, and GitHub Actions that keep *the engine* healthy.

Your **product** is a separate GitHub repository. The engine already supports any repo via `GITHUB_REPO`. You do not need access to Dentro's (or anyone else's) private application.

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
| `agentic-factory` (engine) | Dashboard, orchestrator, agent-runner, and the GitHub Actions that keep the engine itself healthy | Clone it once and run it — do not fork or duplicate it per product. Keep it updated from upstream. |
| `you/app` (product) | Your actual application — where Work Orders, code, and PRs live | Point the engine at it with `GITHUB_REPO` (for the orchestrator/status site) and `LOCAL_REPO_PATH` (for the local agent-runner). This can be a brand-new repo created for the factory or an existing repo you already maintain (bring-your-own). |

## What to copy vs. what not to copy

- **Do not** copy dashboard, orchestrator, or agent-runner code into your product repo — those stay in the engine and are pointed at your repo via config, not vendored into it.
- **Do** copy any product-side workflow files the engine needs to act on your repo — for example the Codex dispatch workflow (see below) if you want cloud-agent dispatch for docs-only Work Orders.
- Work Order specs, `factory.yaml`, and CI configuration