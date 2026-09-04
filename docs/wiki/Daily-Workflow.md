---
title: "Daily Workflow"
description: "Day-to-day loop: start the engine, dispatch Work Orders on your product, review, merge"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Daily Workflow

This is the loop **after** setup. First time: [Getting Started](Getting-Started). Two-repo model: [Adopting](Adopting). Product verify/UI: [Product Profile](Product-Profile).

The engine remembers queue state for the **product** (`GITHUB_REPO`): open WOs, claims, PR watchdog signals. Agents implement in the product clone at `LOCAL_REPO_PATH`.

## Start the day

```bash
make up
open http://localhost:8099
make agent-status    # launchd runner; or make agent-run for a foreground session
```

Orchestrator polls product GitHub (~5 min). Dashboard refreshes ~60s. If WOs list but nothing implements, check `LOCAL_REPO_PATH` — [Troubleshooting](Troubleshooting).

First machine only:

```bash
make agent-setup
make up
make agent-install
```

Confirm **Settings → Authentication** badges are green.

## Queue health (Plan + Overview)

**Plan** — priority queue, phases, milestones, hold (⏸) badges.  
**Overview** — active claim, agent step, stale checkins (amber after ~10 min; auto-release after `CLAIM_TIMEOUT_SECONDS`, default 600).

Empty queue → wrong `GITHUB_REPO`, missing specs under `docs/project_management/work_orders/`, or PAT cannot read the product.

## Create work

Fastest: **PM** tab — describe the change in plain language, confirm the draft, create.  
Or **Settings → Plan → Create WO**.  
Or label a product issue `new-wo` if you pasted `planning-agent.yml`.

Specs: [Work Orders](Work-Orders). Chat: [PM Chat](PM-Chat).

## Dispatch

With the runner installed, it claims the next eligible WO automatically. To force one now via PM:

> Start WO-375 with Cursor.

### Pre-dispatch approval

Priorities in `REQUIRE_APPROVAL_FOR` (default `P1`) enter **pending approval** on Overview: **Approve** / **Skip** (24h cooldown) / **Hold**. P2/P3 skip this unless you widen the env var.

### Cloud Codex (optional)

Docs-only WOs with `services: none` can run via product `codex-dispatch.yml` + `OPENAI_API_KEY` on that repo — see [Agent Backends](Agent-Backends). Local CLI backends still need `LOCAL_REPO_PATH`.

## Watch progress

Open `/wo/NNN` (thread link from Overview/PM):

- Live agent feed and lifecycle messages  
- Your Q&A with the agent  
- Optional screenshots from browser tools you connect  

Audience views: `/` (floor), `/pm` (programs/velocity), `/ci` (runners and flaky checks).

## Human checkpoint

Before commit on P0-P2 work, the agent asks you to verify the **running product** (URL/hints from [`factory.yaml`](Product-Profile)). Approve in the thread when correct; describe fixes when not — the agent iterates. P3 docs-only work skips this because no running behavior changed.

## After approval

1. Agent commits and opens a PR on the **product**  
2. P2: often `--auto` merge after CI + review because the product checkpoint already happened  
3. P3: often `--auto` merge after CI; no product checkpoint  
4. P0/P1: you merge  
5. Verifier / memory agents may follow on the engine or product workflows you enabled  

## End of day

Leave Docker up overnight if you want the watchdog. Or `make down` — queue and threads live in the Docker volume and survive restart.
