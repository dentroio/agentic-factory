---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-09-26
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
| `you/app` (product) | Your actual application: source code, tests, CI, and a `factory.yaml` (or `docs/factory/profile.yaml`) that tells the engine how to build/verify it. | Create or reuse an existing repo, add the small set of adopter files (below), and let Work Orders land there as branches/PRs. |

The engine never needs write access to anything beyond `GITHUB_REPO`. There is no hidden dependency on a specific private repo — the default profile ships with **no product-specific patterns** (no Clarion, no Dentro internals) baked in.

## Fastest path: UI-first onboarding

As of WO-1091, you don't need to hand-edit prefs files to wire up a product.

Go to **Settings → Authentication** in the dashboard:

- Set the **local path** for your product's clone (or trigger a clone from `GITHUB_REPO` directly from the UI).
- Click **prepare files** to scaffold the adopter kit (`factory.yaml`, `docs/factory/patterns.md`, WO spec directory) into that checkout without leaving the browser.
- Saving the product repo in Settings updates `GITHUB_REPO` live for the running orchestrator (no restart needed to pick up the new repo for most read paths). When Docker still has the old path mounted, the UI shows a **Remount Docker** button (WO-1092) that recreates the containers with the new mount in place — no need to run `make restart` by hand.
- Each local agent (Cursor, Claude, Codex, Gemini) binds to its own draft port, so switching products or running multiple agents at once no longer trips `Address already in use` errors.
- If your product isn't wired up yet, the **Overview** page shows a setup CTA linking straight back to Authentication.

This flow is driven by `product_setup.py` on the agent-runner host, proxied through the orchestrator as `GET/PUT /api/product`, `POST /api/product/clone`, and `POST /api/product/remount` — all bearer-token gated, same as the rest of the admin API.

## BYO path: scripts for the terminal

If you prefer the command line, or you're scripting a fresh box:

```bash
# Scaffold a brand-new or existing product repo with the adopter kit
python3 scripts/factory_init.py --path /path/to/app --name myapp \
  --verify "make test" --ui-url "http://localhost:3000"
make init   # same thing, defaults to $LOCAL_REPO_PATH / cwd

# Verify the engine is wired correctly before you trust it with Work Orders
python3 scripts/factory_doctor.py
make doctor
```

`factory_init.py` creates `docs/project_management/work_orders/`, `docs/factory/runs/.gitkeep`, `docs/factory/patterns.md`, a root `factory.yaml`, and copies `docs/adopters/PROCESS.md` into your product as `AGENT_PROCESS.md`. Pass `--sample-wo` to also drop a minimal `WO-001-hello.md`. It refuses to overwrite existing files unless you pass `--force`.

`factory_doctor.py` checks that `GITHUB_REPO` is shaped correctly, `LOCAL_REPO_PATH` exists and is a git checkout whose remote actually matches `GITHUB_REPO`, the product's `factory.yaml` loads, the configured `verify` command or Makef