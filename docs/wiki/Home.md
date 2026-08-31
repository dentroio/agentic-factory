---
title: "Agentic Engineering Factory"
description: "Overview of the factory: engine vs product repo, how it works, navigation"
last_verified: 2026-08-30
covers_wos: []
doc_owner: factory-team
---

# Agentic Engineering Factory

This repository is the **engine**: a Docker-based system that orchestrates AI agents (Claude, Cursor, Codex, Gemini) to implement **Work Orders** in a GitHub repo you choose.

You describe a change. The PM drafts a spec. An agent claims it, writes the code, runs CI, gets a peer review, and opens a PR. For low-risk work, the PR can merge itself.

The dashboard at `http://localhost:8099` shows the queue, agents, and PRs. The orchestrator at `http://localhost:8100` is the API agents talk to.

**Your application is not this repo.** Point `GITHUB_REPO` at [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) or at [your own repo](../adopters/BYO.md). Full split: [Adopting](Adopting).

## What it is not

The factory does not write code on its own initiative. It executes what you queue. It will not merge P0/P1 work without your approval. Agents own the mechanics — branching, coding, testing, PRs — but you set priorities and verify the product works.

It is not a substitute for cloning your product. Do not use **this** GitHub repo’s “Use this template” button to start an app; use the [product template](https://github.com/dentroio/agentic-factory-template).

## Navigation

| Page | What's in it |
|------|-------------|
| [Adopting](Adopting) | Engine vs product, template vs BYO, what not to copy |
| [Getting Started](Getting-Started) | Engine setup, `GITHUB_REPO`, first WO |
| [Daily Workflow](Daily-Workflow) | Day-to-day loop |
| [PM Chat](PM-Chat) | AI project lead |
| [Work Orders](Work-Orders) | Specs, tiers, queue lifecycle |
| [Phases and Milestones](Phases-and-Milestones) | Dispatch order and gates |
| [Dashboard Guide](Dashboard-Guide) | Tab-by-tab UI |
| [Agent Backends](Agent-Backends) | Claude, Cursor, Codex, Gemini |
| [GitHub Integrations](GitHub-Integrations) | Engine Actions vs product paste-ins |
| [Notifications](Notifications) | ntfy and Slack |
| [Customization](Customization) | Review rules, CI, process docs |
| [Troubleshooting](Troubleshooting) | Common failures |

Process cheatsheet for **product** agents: [docs/adopters/PROCESS.md](../adopters/PROCESS.md). Essays: [docs/blog](../blog/README.md).
