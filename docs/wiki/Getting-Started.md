---
title: "Getting Started"
description: "Step-by-step guide to setting up the factory from the GitHub template to your first dispatched work order"
last_verified: 2026-07-12
covers_wos: []
doc_owner: factory-team
---

# Getting Started

This page walks you from zero to a running factory with your first work order dispatched. The whole process takes about 20 minutes.

## Prerequisites

- **Docker Desktop** — the factory's dashboard, orchestrator, and PR watchdog all run in Docker
- **macOS** — secrets are stored in the macOS Keychain; Linux requires editing `.env` manually
- **GitHub account** — the factory monitors a GitHub repo and creates PRs there
- **An AI backend** — at least one of: Claude Pro/Max subscription (CLI), Cursor Pro, or an Anthropic API key

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

**Enable the Wiki tab**
Go to **Settings → Features** and check the **Wikis** checkbox. Then go to the **Wiki** tab and click **Create the first page** — type anything and save. This initializes the wiki git repo so the `wiki-sync` workflow can push to it.

## 3. First-time local setup

Run the interactive setup script. It stores secrets in macOS Keychain — no `.env` files to manage or accidentally commit.

```bash
make agent-setup
```

The script prompts for:
- **GitHub token** — format `ghp_...` or `github_pat_...`, needs `repo` and `read:org` scopes
- **GitHub repo** — `owner/repo` that the factory monitors (your product repo, or this repo itself)
- **Cursor API key** — only needed if `PREFERRED_AGENT=cursor`; press Enter to skip
- **ntfy push topic** — auto-generated; subscribe to it in the ntfy app for phone notifications
- **Slack webhook URL** — optional; press Enter to skip
- **Anthropic API key** — for the orchestrator's WO spec generation; same key as GitHub Actions
- **Agent backend** — which AI runs your work orders: claude (default) or cursor

After setup completes, the factory services start automatically and the dashboard opens in your browser.

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

## Next steps

- [Daily Workflow](Daily-Workflow) — the day-to-day loop once the factory is running
- [Work Orders](Work-Orders) — WO spec structure, priority tiers, and effort sizing
- [GitHub Integrations](GitHub-Integrations) — what each GitHub Actions workflow does
- [Customization](Customization) — tailoring the review rules and CI to your project
