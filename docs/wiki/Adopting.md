---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-09-04
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

The orchestrator reads WO spec files from a configurable path in the product repo (`WO_PATH`, default `docs/project_management/work_orders`) — set this if your product keeps specs somewhere else.

## What to copy vs. what not to copy

- **Do not** copy dashboard, orchestrator, or agent-runner code into your product repo — those stay in the engine and are pointed at your repo via config, not vendored into it.
- **Do** copy any product-side workflow files the engine needs to act on your repo — for example the Codex dispatch workflow (see below) if you want cloud-agent dispatch for docs-only Work Orders.
- Work Order specs, `factory.yaml`, and CI configuration live in the product repo, not the engine.

## Cloud agent dispatch for docs-only Work Orders

The local agent-runner needs Docker, a worktree, and a developer machine. For Work Orders with `services: none` (docs-only, P3-style changes), that overhead isn't needed — the orchestrator can instead dispatch the work to GitHub Actions.

`POST /api/dispatch-codex` on the orchestrator:

```json
{ "wo": "WO-362", "repo": "you/app", "ref": "main", "slug": "sync-in-app-help" }
```

This pre-claims the WO as `codex-gh-actions`, then triggers a `workflow_dispatch` event against a workflow file in your **product** repo (default name `codex-dispatch.yml`, configurable via `CODEX_WORKFLOW_FILE`). That workflow checks out a branch, runs Codex against the WO prompt, and opens a PR — the orchestrator's existing poll loop then picks up the new branch/PR automatically, no callback required.

To adopt this path, copy a `codex-dispatch.yml` workflow into your product repo's `.github/workflows/` and add these secrets there:

| Secret | Purpose |
|--------|---------|
| `OPENAI_API_KEY` | Runs Codex inside the Action |
| `GITHUB_TOKEN` | Provided automatically by GitHub Actions |

If a claim already exists for that WO, dispatch returns `409`. If the `workflow_dispatch` call itself fails (bad repo, workflow not found), the claim is rolled back and the request returns `502`.

## WO numbering across repos

WO number reservation (`/api/wos/reserve` and `/api/plan/next-wo-number`) is **per-repo aware** — it always computes the next number from that specific repo's own spec files (plus any live in-memory reservations for that repo), not from whichever repo happens to be the orchestrator's default.

This matters once you're running the factory against more than one product repo (or against both a product repo and `agentic-factory`'s own WO directory): two repos can have overlapping WO number ranges without colliding, and reserving a number in one repo never consumes or blocks a number in the other.

- Pass `repo` (and `wo_path`, if the product repo keeps specs somewhere non-default) on reservation calls to target a specific product repo instead of the orchestrator's configured default.
- `POST /api/factory/wos` (creating a WO spec directly) has always numbered from that repo's actual spec files and is unaffected by this — it's only the separate reservation endpoints that needed to become repo-aware.