---
title: "Adopting the factory"
description: "Two-repo model: engine vs product, template vs BYO, what to copy and what not to"
last_verified: 2026-09-10
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

Changing the local path used to require a full `make restart` (which rebuilds images) before Docker picked up the new mount. Get Started and Settings → Authentication now show a **Remount Docker** button whenever `restart_required` is set: it calls `POST /api/product/remount` on the agent-runner host (bearer-gated, proxied through the orchestrator), which recreates the compose stack against the current env — no image rebuild, just a fast recreate so the new `LOCAL_REPO_PATH` mount takes effect. Full `make restart` is still the fallback for changes that do need a rebuild (e.g. code changes to the engine itself).

WO-1092 also fixed a port clash where Cursor, Codex, and Gemini agent-runners all defaulted to the same draft-server port and stepped on each other (`Address already in use`), which could leave the orchestrator talking to a stale draft server and `/api/product` returning 404. Each agent now binds a distinct `DRAFT_PORT` (cursor 8101, claude 8102, codex 8103, gemini 8104), so multiple agents can run against the same product concurrently.

## CLI path: `factory doctor` and `factory init`

For scripting, CI, or if you prefer the terminal:

```bash
# Scaffold a fresh or existing product repo
make init            # wraps scripts/factory_init.py
# or non-interactively:
python3 scripts/factory_init.py --path ~/code/your-app --name "Your App" --non-interactive

# Check that everything is wired correctly
make doctor          # wraps scripts/factory_doctor.py
```

`factory init` scaffolds:

- `docs/project_management/work_orders/`
- `docs/factory/runs/.gitkeep`
- `docs/factory/patterns.md`
- a root `factory.yaml`
- `AGENT_PROCESS.md` (copied from the engine's `docs/adopters/PROCESS.md`)
- optionally a sample `WO-001-hello.md` with `--sample-wo`

It refuses to overwrite existing files unless you pass `--force`, and prints next steps (labels to create, how to point the engine's prefs at the new repo, and to run `make doctor` afterward).

`factory doctor` checks, in order:

- `GITHUB_REPO` is set and shaped like `owner/name`
- `LOCAL_REPO_PATH` exists and is a real git checkout
- the local checkout's remote matches `GITHUB_REPO` (hard fail on mismatch — this is the #1 cause of "wired to the wrong repo")
- the product's `factory.yaml` (or `docs/factory/profile.yaml`) loads
- the configured `verify` command is runnable, or a matching Makefile target exists
- the WO specs directory is present
- `gh` reachability, if available, for labels and WO path

It exits non-zero only on hard failures and prints a fix hint for each one. Use `--product PATH` to doctor a product tree directly (useful in CI, or before you've pointed the engine's prefs anywhere).

## Template vs BYO

You can adopt the factory two ways:

- **Template**: start a new product from the adopter kit as a clean starting point, then run `factory init` inside it.
- **BYO (bring your own)**: point the engine at an existing repo and run `factory init` (or the UI's "Prepare files" step) to add just the missing adopter files — WO directory, `factory.yaml`, `AGENT_PROCESS.md`, `patterns.md`. Nothing else in your repo is touched.

Either way, the adopter surface is intentionally small: a WO directory, a `factory.yaml`/profile, and a patterns file the agents read before making changes. See `docs/adopters/BYO.md` for the step-by-step checklist.

## Stranger-clone guarantee

The default (non-legacy) profile and patterns file ship with **zero references to Clarion** — verified by a dedicated regression test (`tests/unit/test_stranger_clone.py`) that fails CI if any Clarion-specific string leaks into the default path (`agent-setup.sh`, `prompt_builder.py`, root `README.md`, or the default patterns file). Someone cloning `agentic-factory` fresh and pointing it at their own repo gets a genuinely blank slate.

The one exception is the live Dentro/Clarion instance itself, which still loads `clarion_patterns.md` via `FACTORY_LEGACY_PRODUCT` — that legacy path is intentionally preserved and does not affect anyone else's adoption.

## GitHub token requirements

Store a **fine-grained GitHub PAT** (`github_pat_...`) in Keychain, scoped to the repos you're adopting (your product, plus `agentic-factory` if you're contributing back). Grant Contents, Pull requests, Issues, and Actions permissions.

The factory's tooling actively rejects other token shapes:

- Classic PATs (`ghp_...`) are refused — they can write every repo the token owner can reach, which is far broader than the factory needs.
- GitHub CLI OAuth tokens (`gho_...`) are refused for the same reason.
- Don't grant `gist` — it isn't used and is an unnecessary exfiltration channel.

GitHub does not expose a "Checks" permission on fine-grained PATs (that's App-only). Contents is sufficient for the factory to read check runs, so don't go looking for a Checks scope that doesn't exist.

`scripts/github_token.py --store` validates the token prefix and writes it to Keychain via stdin, e.g.:

```bash
pbpaste | python3 scripts/github_token.py --store
```

Never pass the token as a CLI argument or paste it into chat/logs.

## Cloud agent path (docs-only / no-services WOs)

Not every Work Order needs a local Docker worktree and a developer machine running Claude/Cursor/Codex. For WOs with `services: none` (typically docs-only or small P3 changes), the orchestrator can dispatch straight to GitHub Actions instead:

```
POST /api/dispatch-codex
{ "wo": "WO-362", "repo": "you/app", "ref": "main", "slug": "your-wo-slug" }
```

This pre-claims the WO as `codex-gh-actions`, triggers a `workflow_dispatch` event against a `codex-dispatch.yml` workflow in your product repo, and lets the existing poll loop detect the resulting branch/PR — no callback needed. The target repo needs a `codex-dispatch.yml` workflow (checkout, branch, run Codex, open PR) and an `OPENAI_API_KEY` secret; `GITHUB_TOKEN` is provided automatically by Actions. On dispatch failure