---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-11-10
covers_wos:
  - WO-1008
  - WO-1052
  - WO-1091
  - WO-1092
  - WO-1103
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
| `agentic-factory` (engine) | Dashboard, orchestrator, agent runner, launchd/CI plumbing. Kept generic and product-agnostic. | Clone once. Point it at your product via `GITHUB_REPO` / `LOCAL_REPO_PATH`. Rarely edited after setup. |
| `you/app` (product) | Your actual application: source code, tests, CI, a root `factory.yaml` (or `docs/factory/profile.yaml`), a `docs/project_management/work_orders/` directory of WO specs, and `docs/factory/patterns.md` for house style/patterns the agents should follow. | Author Work Orders here, run `make doctor` / `make init` from the engine against this path, let agents open PRs against it. |

The default profile ships with **no product baked in** — a stranger clone of `agentic-factory` has no Clarion (or any other product) references in its agent-facing prompts, patterns, or README. A legacy `clarion_patterns.md` loader still exists for Dentro's own running instance, gated behind `FACTORY_LEGACY_PRODUCT`; it is never loaded unless that env var matches the configured `GITHUB_REPO`.

## Fastest path: UI-first onboarding

Settings → **Authentication** has a product section that does the wiring for you:

1. Enter (or browse to) the local checkout path for your product repo.
2. Use **Clone** if you don't have a local checkout yet — the host clones `GITHUB_REPO` for you.
3. Use **Prepare files** to scaffold the product-side files (`factory.yaml`, WO specs dir, `docs/factory/patterns.md`, `AGENT_PROCESS.md`) without leaving the dashboard.
4. Save — `GITHUB_REPO` updates live on the orchestrator; you'll be prompted to restart (`make restart`) to pick up the new path everywhere.

If your product isn't ready yet, the Overview page shows a setup CTA linking straight to this flow instead of a confusing empty queue.

## `factory doctor` and `factory init` (CLI alternative)

Prefer the terminal? Two Makefile targets cover the same ground:

- **`make doctor`** (`scripts/factory_doctor.py`) — checks that everything is wired correctly:
  - `GITHUB_REPO` is shaped like `owner/name`
  - `LOCAL_REPO_PATH` exists and is a git checkout whose remote matches `GITHUB_REPO` (hard fail on mismatch)
  - product `factory.yaml` (or `docs/factory/profile.yaml`) loads
  - the `verify` command/Makefile target is runnable
  - the WO specs directory is present
  - `gh` is reachable for labels / WO paths (optional)

  Exits 0 only when hard checks pass, with fix hints printed for each failure. Use `--product PATH` to doctor a tree without relying on saved prefs (handy in CI).

- **`make init`** (`scripts/factory_init.py`) — scaffolds a brand-new product repo: `docs/project_management/work_orders/`, `docs/factory/runs/.gitkeep`, `docs/factory/patterns.md`, a root `factory.yaml`, and `AGENT_PROCESS.md` (copied from `docs/adopters/PROCESS.md`). Supports `--sample-wo` to drop a minimal `WO-001-hello.md`, plus non-interactive flags `--name`, `--verify`, `--ui-url`, `--force`. Refuses to overwrite existing files unless `--force` is passed, and prints next steps (labels, pointing engine prefs at the repo, `make doctor`).

## Template vs BYO

- **Template path** — start from the adopter kit (`docs/adopters/`) and let `make init` lay down the expected files in a fresh repo.
- **BYO (bring your own) path** — point the engine at an existing product repo. Run `make doctor` first to see exactly what's missing, then `make init --path <repo>` (or the Auth UI "Prepare files" button) to fill the gaps without clobbering anything you already have.

## What to copy vs not copy

- **Copy into your product:**