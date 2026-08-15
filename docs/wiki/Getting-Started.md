---
title: "Getting Started"
description: "Step-by-step guide to setting up the factory from the GitHub template to your first dispatched work order"
last_verified: 2026-07-30
covers_wos:
  - WO-1003
  - WO-1008
  - WO-1026
  - WO-1032
  - WO-1044
doc_owner: factory-team
---

# Getting Started

This page walks you from zero to a running factory with your first work order dispatched. The whole process takes about 20 minutes.

## Prerequisites

- **Docker Desktop** — the factory's dashboard, orchestrator, and PR watchdog all run in Docker
- **macOS** — secrets are stored in the macOS Keychain; Linux requires editing `.env` manually
- **GitHub account** — the factory monitors a GitHub repo and creates PRs there
- **An AI backend** — at least one of: Claude Pro/Max subscription (CLI), Cursor Pro, Codex, Gemini Advanced, or an Anthropic API key

## 1. Create your repo from the template

Go to the `dentroio/agentic-factory` repository on GitHub and click **Use this template → Create a new repository**. Give your repo a name — this is where the factory's Docker services, GitHub Actions, and WO specs will live. It does not have to be the same repo as the product you're building; many teams keep the factory in its own repo and give it access to the product repo via a PAT.

Clone your new repo locally:

```bash
git clone https://github.com/your-org/your-factory-repo.git
cd your-factory-repo
```

## 2. Configure GitHub repo settings

These settings must be applied to your new repo before the workflows function correctly.

**Actions permissions**
Go to **Settings → Actions → General** and set:
- Actions permissions: Allow all actions and reusable workflows
- Workflow permissions: Read and write permissions
- Check "Allow GitHub Actions to create and approve pull requests"

**Branch protection**
Go to **Settings → Rules → Rulesets → New branch ruleset**. Target: `main`. Enable:
- Require a pull request before merging
- Required status checks: `Claude Code Review` (add more CI checks once your CI is configured)
- Block force pushes

**Labels**
Go to **Issues → Labels** and create these labels if they do not exist:
- `new-wo` — triggers the planning agent
- `agent-pr` — marks PRs opened by agents (enables auto-fix and review-applier)
- `documentation` — used by the doc-audit workflow
- `breaking-change` — used by the Dependabot WO bridge (optional)

**GitHub Actions secrets**
Go to **Settings → Secrets and variables → Actions → New repository secret** and add:
- `ANTHROPIC_API_KEY` — required by AI review, planning agent, verifier, memory agent, and observability workflows. Get it at [console.anthropic.com](https://console.anthropic.com/settings/keys)
- `OPENAI_API_KEY` — required if you intend to use the Codex cloud agent path (WO-1008)

**Enable the Wiki tab**
Go to **Settings → Features** and check the **Wikis** checkbox. Then go to the **Wiki** tab and click **Create the first page** — type anything and save. This initializes the wiki git repo so the `wiki-sync` workflow can push to it.

## 3. First-time local setup

Run the interactive setup script. It stores secrets in macOS Keychain — no `.env` files to manage or accidentally commit.

```bash
make agent-setup
```

The script prompts for:
- **GitHub token** — fine-grained PAT (`github_pat_...`) limited to the product repo and this factory repo. Contents, Pull requests, Issues, and Actions (read/write). No `gist`. Classic `ghp_` and GitHub CLI `gho_` tokens are rejected.
- **GitHub repo** — `owner/repo` that the factory monitors (your product repo, or this repo itself)
- **Cursor API key** — only needed if `PREFERRED_AGENT=cursor`; press Enter to skip
- **ntfy push topic** — auto-generated; subscribe to it in the ntfy app for phone notifications
- **Slack webhook URL** — optional; press Enter to skip
- **Anthropic API key** — for the orchestrator's WO spec generation; same key as GitHub Actions
- **Agent backend** — which AI runs your work orders: claude (default), cursor, codex, or gemini

After setup completes, the factory services start automatically and the dashboard opens in your browser. The script also auto-generates an `API_SECRET` bearer token and stores it in Keychain — this token secures all write endpoints on the orchestrator.

## 4. Verify the dashboard

Open [http://localhost:8099](http://localhost:8099). Go to **Settings → Authentication** and confirm:
- The GitHub token badge is green
- The Anthropic API key badge is green (if you added one)

If any badge is red, re-run `make agent-setup` to overwrite the stored value.

## 5. Install the agent runner (recommended)

The agent runner is what actually executes work orders — it runs the AI CLI on your machine and streams progress back to the dashboard. Install it as a background daemon:

```bash
make agent-install
```

This installs a launchd service that starts on login and restarts automatically if it crashes. The agent only runs when the factory has a WO to dispatch — it idles otherwise.

To verify it is running:

```bash
make agent-status
```

To tail the live log:

```bash
make agent-logs
```

## 6. Customize the AI review rules

Open `scripts/review_context.txt`. This file is loaded into the Claude system prompt on every PR review. Add checks specific to your project — patterns to flag, invariants to enforce, services to name-check. See [Customization](Customization) for the format and examples.

## 7. Create and dispatch your first work order

Open the **PM** tab at [http://localhost:8099](http://localhost:8099) and describe what you want to build in plain language. The PM drafts a structured WO spec and asks you to confirm. Say "create it" — the WO lands in the queue immediately.

If the agent runner is installed and running, it picks up the WO within seconds. Navigate to **Overview** to see the agent's live progress, or click **View thread →** to follow the step-by-step output.

When the agent finishes, you will receive a push notification (if ntfy is configured) and the Overview tab shows "Awaiting your approval." Verify the work, then approve in the thread or click the approve button. The agent commits, opens a PR, and — for P2 WOs — sets auto-merge.

## How the orchestrator manages the queue

The factory runs an **orchestrator** service (WO-1003) that polls every `POLL_INTERVAL` seconds (default: 300), reads the WO board from GitHub, and produces a dispatch advisory. It:

- Resolves WO dependencies — a WO is not dispatched until all `Depends on:` entries are marked Done
- Tracks runner capacity and will not recommend more simultaneous WOs than `MAX_PARALLEL_WOS`
- Detects circular dependencies and flags them rather than looping
- Writes `orchestrator.json`, which the dashboard reads to render the **Dispatch Queue** and **Recommendations** panels
- Optionally posts a daily board summary to a configured GitHub issue (set `DAILY_SUMMARY_HOUR` and `SUMMARY_ISSUE_NUMBER` in your `.env`)

The orchestrator is advisory in the current release — it recommends actions but does not autonomously trigger agents. The dashboard still requires a human to approve dispatch.

## Cloud agent path (Codex via GitHub Actions)

For WOs with `services: none` (docs-only or lightweight specs), the factory can dispatch work entirely in the cloud without a local agent runner (WO-1008). This path:

1. POSTs a `workflow_dispatch` event to trigger `codex-dispatch.yml` in your target repo
2. The workflow checks out a fresh branch, fetches the WO spec, runs `codex exec`, and opens a PR
3. The orchestrator's poll loop detects the new branch and PR automatically — no callback needed

To use this path, your target repo needs:
- `.github/workflows/codex-dispatch.yml` (see the factory template)
- `OPENAI_API_KEY` secret set in that repo

You can trigger it directly:

```bash
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-362","slug":"sync-in-app-help"}'
```

The orchestrator will auto-select this path when a WO spec declares `services: none`.

## Automatic PR queue management

When your target repo has auto-merge PRs queued, each merge to `main` previously required manual `gh pr update-branch` calls before remaining PRs could merge. The factory template now includes `auto-update-prs.yml` (WO-1044), a workflow that triggers on every push to `main` and automatically updates all open PRs with auto-merge enabled. Key behaviors:

- Covers both factory-dispatched PRs and Dependabot PRs
- PRs with real merge conflicts log a warning; the workflow never fails hard
- Uses `GH_PAT` (not `GITHUB_TOKEN`) so branch pushes trigger downstream CI

Ensure this workflow is present in your target repo and that `GH_PAT` is set as a repo secret.

## Automatic WO completion on PR merge

When a PR merges, the PR watchdog (WO-1026) automatically:

1. Updates the claim file (`docs/factory/runs/WO-NNN.json`) with `status: done` and `completed_at`
2. Adds `Status: ✅ Done` and a `## Merged` section to the WO spec file
3. Notifies the orchestrator to mark the dispatch entry complete

This commit is pushed directly to `main` (docs-only, no review needed per risk tier rules). If no spec file exists for the WO, a minimal stub is created from the PR title. PRs with no `WO-NNN` in their title are skipped and logged.

Manual mark-done steps are only needed if the watchdog service is not deployed.

## Next steps

- [Daily Workflow](Daily-Workflow) — the day-to-day loop once the factory is running
- [Work Orders](Work-Orders) — WO spec structure, priority tiers, and effort sizing
- [GitHub Integrations](GitHub-Integrations) — what each GitHub Actions workflow does
- [Customization](Customization) — tailoring the review rules and CI to your project