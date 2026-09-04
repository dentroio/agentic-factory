---
title: "Getting Started"
description: "From zero to first Work Order: UI product setup, engine, LOCAL_REPO_PATH, factory.yaml"
last_verified: 2026-09-04
covers_wos:
  - WO-1091
doc_owner: factory-team
---

# Getting Started

Goal: in about **15–20 minutes**, run the factory engine, point it at a product repo from the dashboard, and complete (or watch) one Work Order.

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
2. Note the `owner/name` — you will paste it in the dashboard (or let the factory clone it).
3. In that repo: labels `new-wo`, `agent-pr`, `pm-sync`; protect `main` requiring the **CI** check (see template [SETUP.md](https://github.com/dentroio/agentic-factory-template/blob/main/SETUP.md)).

**Existing app:** you can skip cloning yourself — the dashboard can clone into `~/src/<repo>` (or point at an existing path). See [Bring your own repo](../adopters/BYO.md).

## Step 2 — Clone and set up the engine

```bash
git clone https://github.com/dentroio/agentic-factory.git
cd agentic-factory
make agent-setup   # optional if you prefer to enter secrets only in the UI
make up
make agent-install
open http://localhost:8099
```

`make agent-setup` can store a token and a default repo; you can also finish entirely in the UI.

## Step 3 — Interactive Get Started (preferred)

1. Open **Settings → Get Started** (or the Overview banner).
2. **GitHub** — paste fine-grained PAT + `owner/your-product`.
3. **Product** — set a local directory **or** clone; leave Prepare factory files checked when needed.
4. **Agent / LLM** — pick Claude / Cursor / Codex / Gemini (CLI detected when possible) and start the daemon.
5. **Ready** — either open **PM chat** and ask the agent to finish remaining setup (labels, first WO), or follow the self-serve checklist.
6. If the path changed, run `make restart` when prompted, then `make doctor`.

You should **not** need to hand-edit prefs or `.env` for day-to-day adoption.

## Step 4 — Confirm the dashboard

Open [http://localhost:8099](http://localhost:8099).

1. **Settings → Authentication** — GitHub token and product checkout look healthy.
2. **Overview / Plan** — you see Work Orders from the **product** (template ships WO-001 … WO-004).
3. If the list is empty: wrong repo, missing specs under `docs/project_management/work_orders/`, or token cannot read that repo.

## Step 5 — Agent runner

```bash
make agent-status
make agent-logs   # optional: watch claims
```

One-shot test without the daemon:

```bash
make agent-once
```

## Step 6 — Product profile

The UI **Prepare factory files** step writes a root `factory.yaml` when missing. Confirm it:

```yaml
name: my-app
verify: "make ci-local"
ui_url: "http://localhost:8765"
ui_verify_hint: "Open the demo; confirm the change matches the WO."
compose_project: ""
patterns_file: "docs/factory/patterns.md"
```

CLI fallback (power users):

```bash
make init PRODUCT=/absolute/path/to/your-product INIT_ARGS='--sample-wo'
make doctor DOCTOR_ARGS="--product /absolute/path/to/your-product --skip-network"
```

Details: [Product Profile](Product-Profile).

## Step 7 — First Work Order (template demo)

1. In the **product** repo, open `docs/project_management/work_orders/WO-001-change-greeting.md` (or the smoke WO from init).
2. With the runner installed, wait for a claim (or dispatch from the PM / Overview UI).
3. When the agent asks you to verify: in the product clone run `make run`, open the UI URL from `factory.yaml`, confirm the change.
4. Approve; the agent opens a PR on the **product** repo (not on agentic-factory).

## What success looks like

| Check | OK when |
|-------|---------|
| Dashboard | Lists product WOs; Auth product checkout “ready” |
| Runner | `make agent-status` shows loaded; logs show polling |
| First WO | PR opens on **product** GitHub; verify URL is your app |
| Doctor | `make doctor` hard checks pass |

## Next reading

- [Daily Workflow](Daily-Workflow) — day-to-day loop
- [Work Orders](Work-Orders) — specs and risk tiers
- [Product Profile](Product-Profile) — `factory.yaml`
- [Troubleshooting](Troubleshooting) — empty queue, offline runner, auth

## Optional: paste product GitHub Actions

Planning-agent, AI review, etc. are **optional**. Copy from [templates/github/](../../templates/github/) into the **product** `.github/workflows/` only. Never replace this engine’s live workflows with those files.
