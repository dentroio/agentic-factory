---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-09-14
covers_wos:
  - WO-1008
  - WO-1052
  - WO-1058
  - WO-1091
  - WO-1092
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
| `you/app` (product) | Your actual application: source code, tests, CI, and a `factory.yaml` (or `docs/factory/profile.yaml`) that tells the engine how to build/verify it. | Create or reuse an existing repo, add the small set of adopter files (below), and let Work Orders land there as branches/PRs. |

The engine never needs write access to anything beyond `GITHUB_REPO`. There is no hidden dependency on a specific private repo — the default profile ships with **no product-specific patterns** (no Clarion, no Dentro internals) baked in.

## Fastest path: UI-first onboarding

As of WO-1091, you don't need to hand-edit prefs files to wire up a product. In the dashboard:

1. Open **Settings → Authentication**.
2. Set the **local path** for your product's clone (or use the built-in **Clone** action to check it out from `GITHUB_REPO`).
3. Use **Prepare files** to scaffold the adopter files your product is missing (see `factory init` below — this calls the same scaffolder).
4. Restart when prompted so the orchestrator and agent-runner pick up the new path.

The **Overview** page shows a setup banner/CTA whenever the product isn't fully wired (no local path, no `factory.yaml`, etc.), linking straight back to Settings → Authentication.

Under the hood, the agent-runner host exposes `GET/PUT /api/product` and `POST /api/product/clone`, proxied through the orchestrator. Updating `GITHUB_REPO` via the Secrets UI takes effect immediately — no restart required just to point at a different repo (a restart is still needed to remount the local path).

### One-click remount (WO-1092)

Chang