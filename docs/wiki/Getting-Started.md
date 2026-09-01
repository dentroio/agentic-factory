---
title: "Getting Started"
description: "From zero to first Work Order: product repo, engine setup, LOCAL_REPO_PATH, factory.yaml"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Getting Started

Goal: in about **20–30 minutes**, run the factory engine, point it at a product repo, and complete (or watch) one Work Order.

You need **two** Git checkouts:

| Checkout | Repo | Role |
|----------|------|------|
| Engine | [dentroio/agentic-factory](https://github.com/dentroio/agentic-factory) | Dashboard, orchestrator, agent runner |
| Product | Your app (or the [template](https://github.com/dentroio/agentic-factory-template)) | Code + Work Order specs + PRs |

If that split is unclear, read [Adopting](Adopting) first.

## Prerequisites

| Need | Why |
|------|-----|
| **macOS + Docker Desktop** | Supported path today. Secrets go in Keychain; services run in Docker |
| **GitHub account** | Agents open PRs on the **product** repo |
| **Fine-grained PAT** (`github_pat_...`) | Contents, Pull requests, Issues, Actions on the product repo **and** this engine. No `gist`. Classic `ghp_` tokens are rejected |
| **One AI backend** | Claude Pro/Max CLI (recommended), or Cursor / Codex / Gemini, or an Anthropic API key |

Linux: you can run Docker services, but you must put secrets in `.env` yourself — there is no Keychain helper yet.

## Step 1 — Create the product repo

**Fastest path (recommended for first time):**

1. Open [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) → **Use this template**.
2. Clone **your** new repo somewhere you will edit code, e.g. `~/src/my-factory-demo`.
3. In that repo: labels `new-wo`, `agent-pr`, `pm-sync`; protect `main` requiring the **CI** check (see template [SETUP.md](https://github.com/dentroio/agentic-factory-template/blob/main/SETUP.md)).

**Existing app:** follow [Bring your own repo](../adopters/BYO.md) — WO folder, claim files, `AGENT_PROCESS.md`, labels, and a root [`factory.yaml`](Product-Profile).

## Step 2 — Clone and set up the engine

```bash
git clone https://github.com/dentroio/agentic-factory.git
cd agentic-factory
make agent-setup
```

When prompted for **GitHub repo**, enter the **product** `owner/name` (the template-derived repo or your app) — **not** `dentroio/agentic-factory` unless you are developing the engine itself.

Also provide:

- Fine-grained GitHub PAT
- Optional Cursor / Slack / ntfy
- Anthropic API key (PM + WO drafting)
- Preferred agent backend (`claude` is the default)

`make agent-setup` starts Docker services and opens the dashboard.

## Step 3 — Point the runner at your product checkout

The dashboard lists Work Orders from GitHub. The **agent runner** needs a **local clone** of that same product to create worktrees and run `verify`.

Set this once (prefs file — not Keychain):

```bash
# ~/.config/factory-agent/prefs  (created by agent-setup)
GITHUB_REPO=you/your-product
LOCAL_REPO_PATH=/absolute/path/to/your-product-clone
PREFERRED_AGENT=claude
```

Or set `LOCAL_REPO_PATH` in the environment before `make agent-install` / `make agent-once`.

If `LOCAL_REPO_PATH` is wrong or empty, agents cannot implement WOs even when the dashboard shows them.

## Step 4 — Confirm the dashboard

Open [http://localhost:8099](http://localhost:8099).

1. **Settings → Authentication** — GitHub token and Anthropic key look healthy.
2. **Overview / Plan** — you see Work Orders from the **product** (template ships WO-001 … WO-004).
3. If the list is empty: wrong `GITHUB_REPO`, missing specs under `docs/project_management/work_orders/`, or token cannot read that repo.

## Step 5 — Install the agent runner

```bash
make agent-install
make agent-status
make agent-logs   # optional: watch claims
```

The runner polls the orchestrator and claims open WOs. It idles when the queue is empty.

One-shot test without the daemon:

```bash
make agent-once
```

## Step 6 — Product profile

At the root of the **product** repo, keep a `factory.yaml`. The template already has one. Confirm it before the first WO:

```yaml
name: my-app
verify: "make ci-local"
ui_url: "http://localhost:8765"
ui_verify_hint: "Open the demo; confirm the change matches the WO."
compose_project: ""
patterns_file: "docs/factory/patterns.md"
```

Details and optional fields: [Product Profile](Product-Profile). Agent prompts use these fields — never another company’s product name or login.

## Step 7 — First Work Order (template demo)

1. In the **product** repo, open `docs/project_management/work_orders/WO-001-change-greeting.md`.
2. With the runner installed, wait for a claim (or dispatch from the PM / Overview UI).
3. When the agent asks you to verify: in the product clone run `make run`, open [http://localhost:8765](http://localhost:8765), confirm the heading.
4. Approve; the agent opens a PR on the **product** repo (not on agentic-factory).

## What success looks like

| Check | OK when |
|-------|---------|
| Dashboard | Lists product WOs; settings green |
| Runner | `make agent-status` shows loaded; logs show polling |
| First WO | PR opens on **product** GitHub; verify URL is your app |
| Engine prefs | `GITHUB_REPO` is your product, not a random private app |

## Next reading

- [Daily Workflow](Daily-Workflow) — day-to-day loop
- [Work Orders](Work-Orders) — specs and risk tiers
- [Product Profile](Product-Profile) — `factory.yaml`
- [Troubleshooting](Troubleshooting) — empty queue, offline runner, auth
- [Essay series](../blog/README.md) — why Work Orders look like this

## Optional: paste product GitHub Actions

Planning-agent, AI review, etc. are **optional**. Copy from [templates/github/](../../templates/github/) into the **product** `.github/workflows/` only. Never replace this engine’s live workflows with those files.
