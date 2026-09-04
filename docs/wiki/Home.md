---
title: "Agentic Engineering Factory"
description: "Overview: engine vs product, how it works, where to start"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Agentic Engineering Factory

This repository is the **engine**: Docker services and a host agent runner that orchestrate AI agents (Claude, Cursor, Codex, Gemini) to implement **Work Orders** in a GitHub repo **you** choose.

You describe a change. The PM can draft a spec. An agent claims it, writes code, runs your product’s verify command, and asks you to confirm the running product before commit. Then it opens a PR. P2 work can auto-merge after the human product checkpoint, CI, and review; P3 docs-only work can auto-merge after CI; P0/P1 wait for you.

| | |
|-|-|
| Dashboard | [http://localhost:8099](http://localhost:8099) |
| Orchestrator API | [http://localhost:8100](http://localhost:8100) (localhost + bearer token) |

**Your application is not this repo.** Point `GITHUB_REPO` at the [product template](https://github.com/dentroio/agentic-factory-template) or [your own repo](../adopters/BYO.md). See [Adopting](Adopting).

## Start here

1. **[Adopting](Adopting)** — two-repo mental model (2 min)  
2. **[Getting Started](Getting-Started)** — setup through first WO (20–30 min)  
3. **[Product Profile](Product-Profile)** — `factory.yaml` for verify / UI / patterns  

## What it is not

- Not an autonomous product owner — it executes the queue you define  
- Not a substitute for cloning your product locally (`LOCAL_REPO_PATH`)  
- Not started by clicking “Use this template” on **this** engine repo — use [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) for an app  

## Navigation

| Page | Contents |
|------|----------|
| [Adopting](Adopting) | Engine vs product, checklist |
| [Getting Started](Getting-Started) | Full setup |
| [Product Profile](Product-Profile) | `factory.yaml` |
| [Daily Workflow](Daily-Workflow) | Day-to-day loop |
| [PM Chat](PM-Chat) | AI project lead |
| [Work Orders](Work-Orders) | Specs, tiers, lifecycle |
| [Phases and Milestones](Phases-and-Milestones) | Dispatch order |
| [Dashboard Guide](Dashboard-Guide) | UI tabs |
| [Agent Backends](Agent-Backends) | Claude, Cursor, Codex, Gemini |
| [GitHub Integrations](GitHub-Integrations) | Engine Actions vs product paste-ins |
| [Customization](Customization) | Review rules, thresholds |
| [Troubleshooting](Troubleshooting) | Empty queue, offline runner |
| [Reliability](Reliability) | Security / monitoring |
| [Notifications](Notifications) | ntfy / Slack |

Process for **product** agents: [docs/adopters/PROCESS.md](../adopters/PROCESS.md).
