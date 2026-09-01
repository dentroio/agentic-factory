---
title: "Getting Started"
description: "Run the engine, point GITHUB_REPO at a product (template or BYO), dispatch the first work order"
last_verified: 2026-08-30
covers_wos:
  - WO-1003
  - WO-1008
  - WO-1026
  - WO-1032
  - WO-1044
doc_owner: factory-team
---

# Getting Started

Two pieces: **this engine** (clone and run), and a **product GitHub repo** the engine watches. You do not copy this repository to start an app. See [Adopting](Adopting) for the split.

The whole process takes about 20 minutes.

## Prerequisites

- **Docker Desktop** — dashboard, orchestrator, and PR watchdog run in Docker
- **macOS** — secrets live in Keychain; Linux requires editing `.env` manually
- **GitHub account** — the factory opens PRs on the **product** repo
- **An AI backend** — at least one of: Claude Pro/Max (CLI), Cursor Pro, Codex, Gemini Advanced, or an Anthropic API key

## 1. Product repo (template or BYO)

**Fastest:** GitHub → [dentroio/agentic-factory-template](https://github.com/dentroio/agentic-factory-template) → **Use this template**. That gives you a tiny demo app, sample Work Orders, `PROCESS.md`, and `SETUP.md`.

**Existing app:** follow [Bring your own repo](../adopters/BYO.md) — add a WO folder, claim-file folder, labels, and copy [PROCESS.md](../adopters/PROCESS.md) to `AGENT_PROCESS.md`.

Clone the **product** repo wherever you work on the app. Clone **this** engine separately:

```bash
git clone https://github.com/dentroio/agentic-factory.git
cd agentic-factory
```

## 2. Labels and protection on the **product** repo

Apply these to `owner/your-product` (the repo you will put in `GITHUB_REPO`), not only to the engine.

**Labels** (Issues → Labels): `new-wo`, `agent-pr`, `pm-sync`. Optional: `documentation`, `breaking-change`.

**Branch protection** on `main`: require a pull request; add your product CI as a required check (the template’s job is named `CI`).

**Actions** (if you paste workflows from [templates/github/](../../templates/github/) into the product): allow Actions, read/write workflow permissions, and “Allow GitHub Actions to create and approve pull requests.” Secrets: `ANTHROPIC_API_KEY` (planning / AI review), optional `GH_PAT` (auto-update PRs), optional `OPENAI_API_KEY` (cloud Codex).

You do **not** need to enable a Wiki tab on the product for the factory to run. Wiki sync on this engine is optional (see [Doc Writer Agent](Doc-Writer-Agent)).

## 3. First-time engine setup

From the **agentic-factory** clone:

```bash
make agent-setup
```

The script stores secrets in macOS Keychain. When it asks for **GitHub repo**, enter the **product** `owner/name` (the template clone or your app) — not `dentroio/agentic-factory` unless you are developing the engine itself.

It also prompts for:

- **GitHub token** — fine-grained PAT (`github_pat_...`) limited to the product repo and this engine. Contents, Pull requests, Issues, and Actions (read/write). No `gist`. Classic `ghp_` and GitHub CLI `gho_` tokens are rejected.
- **Cursor API key** — only if `PREFERRED_AGENT=cursor`; press Enter to skip
- **ntfy** / **Slack** — optional
- **Anthropic API key** — WO spec generation in the orchestrator
- **Agent backend** — claude (default), cursor, codex, or gemini

Services start after setup; the dashboard opens in the browser. An `API_SECRET` bearer token is generated and stored in Keychain for orchestrator writes.

## 4. Verify the dashboard

Open [http://localhost:8099](http://localhost:8099). **Settings → Authentication**: GitHub token and Anthropic key badges should be green. If not, re-run `make agent-setup`.

Confirm the dashboard is listing Work Orders from the **product** repo (template sample WOs, or yours).

## 5. Install the agent runner (recommended)

```bash
make agent-install
make agent-status
make agent-logs
```

The runner executes WOs on your machine against the product checkout the engine is configured for. It idles when the queue is empty.

## 6. Review rules (optional)

`scripts/review_context.txt` in **this** engine is used by workflows that run **here**. If you paste `ai-review.yml` into the **product** repo, put project-specific checks in that repo (copy the script or the file next to the workflow). See [Customization](Customization).

## 7. First work order

**Template demo:** open `docs/project_management/work_orders/WO-001-change-greeting.md` in the product repo. An agent claims it, changes the heading, you open http://localhost:8765 (`make run` in the template), then the PR.

**Any product:** open the **PM** tab at [http://localhost:8099](http://localhost:8099) and describe what you want. Confirm the spec. With the runner installed, watch **Overview**.

When the agent asks you to verify the running product, do that **before** it commits. P2 WOs may auto-merge after CI.

## How the orchestrator manages the queue

The **orchestrator** (WO-1003) polls every `POLL_INTERVAL` seconds (default: 300), reads the WO board from GitHub (`GITHUB_REPO`), and produces a dispatch advisory. It:

- Resolves WO dependencies — a WO is not dispatched until all `Depends on:` entries are marked Done
- Tracks runner capacity (`MAX_PARALLEL_WOS`)
- Detects circular dependencies
- Writes `orchestrator.json` for the **Dispatch Queue** and **Recommendations** panels
- Optionally posts a daily board summary (`DAILY_SUMMARY_HOUR` and `SUMMARY_ISSUE_NUMBER` in your `.env`)

The orchestrator is advisory in the current release — it recommends actions but does not always autonomously trigger agents. The dashboard still requires a human to approve dispatch when configured that way.

## Cloud agent path (Codex via GitHub Actions)

For WOs with `services: none` (docs-only or lightweight specs), the factory can dispatch work in the cloud without a local runner (WO-1008):

1. POST `workflow_dispatch` to `codex-dispatch.yml` in the **product** repo
2. The workflow checks out a branch, runs `codex exec`, opens a PR
3. The orchestrator’s poll loop sees the branch and PR

The product repo needs `.github/workflows/codex-dispatch.yml` and `OPENAI_API_KEY`. Trigger:

```bash
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-001","slug":"change-greeting"}'
```

## Automatic PR queue management

`auto-update-prs.yml` (WO-1044) lives in this engine and as a [paste-in](../../templates/github/auto-update-prs.yml) for the product. On push to `main` it updates open auto-merge PRs. Use `GH_PAT` so pushes retrigger CI.

## Automatic WO completion on PR merge

When a PR with `WO-NNN` in the title merges, the PR watchdog (WO-1026) updates the claim file and spec on the **product** repo.

## Next steps

- [Adopting](Adopting) — engine vs product, what not to copy
- [Daily Workflow](Daily-Workflow) — day-to-day loop
- [Work Orders](Work-Orders) — spec shape and queue
- [GitHub Integrations](GitHub-Integrations) — engine workflows vs product paste-ins
- [Customization](Customization) — review rules and CI
- [Adopter kit](../adopters/README.md) — PROCESS, contract, BYO
