# Agentic Engineering Factory

The agentic factory is a Docker-based system that orchestrates AI agents — Claude, Cursor, Codex, Gemini — to implement software work orders autonomously. You write a work order spec describing what to build. An agent claims it, writes the code, runs CI, gets a peer review from another model, and opens a PR. For low-risk work, the PR merges itself.

The factory runs alongside your project. The dashboard at `http://localhost:8099` shows everything: what's running, what's queued, PR health, and notification settings. The orchestrator at `http://localhost:8100` is the REST API that agents talk to.

The PM tab hosts an AI assistant that knows the full context of your queue, PRs, and WO specs. You can talk to it in plain language to create work orders, dispatch them, merge PRs, manage Dependabot, and build out your roadmap.

## What it is not

The factory does not write code on its own initiative. It executes what you queue. It will not merge P0/P1 work (schema changes, core features) without your explicit approval. Agents own the mechanics — branching, coding, testing, PRs, cleanup — but you set priorities and verify the product works.

## Navigation

| Page | What's in it |
|------|-------------|
| [Daily Workflow](Daily-Workflow) | Start here — the day-to-day loop from starting the factory to merging a WO |
| [PM Chat](PM-Chat) | The AI PM assistant: what it knows and what it can do |
| [Work Orders](Work-Orders) | WO specs, priority tiers, effort sizes, queue lifecycle |
| [Phases and Milestones](Phases-and-Milestones) | Controlling dispatch order and declaring delivery gates |
| [Dashboard Guide](Dashboard-Guide) | Tab-by-tab breakdown of the web UI |
| [Agent Backends](Agent-Backends) | Claude, Cursor, Codex, Gemini — when to use each, how the review chain works |
| [GitHub Integrations](GitHub-Integrations) | The GitHub Actions workflows and what each one does |
| [Notifications](Notifications) | ntfy push notifications and Slack webhook setup |
| [Troubleshooting](Troubleshooting) | Common failures and how to fix them |
