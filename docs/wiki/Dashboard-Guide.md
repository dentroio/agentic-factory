---
title: "Dashboard Guide"
description: "Tabs and settings at localhost:8099 — Overview, PM, Engineering, Plan, Factory, WO threads"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Dashboard Guide

Open [http://127.0.0.1:8099](http://127.0.0.1:8099) (loopback only). No human login. `API_SECRET` is a machine bearer for scripts/orchestrator — browser same-origin writes are allowed; bare `curl` writes get 401. Page auto-refreshes ~60s.

Data is for the product in `GITHUB_REPO`. Wrong repo → empty or foreign WOs. First-time setup: **[Settings → Get Started](http://127.0.0.1:8099/settings/get-started)** (GitHub, product checkout, agent/LLM).

## Overview

- **Get Started banner** — shown until product + preferred agent + runner look ready; links to the interactive wizard  
- **Health banner** — HEALTHY / DEGRADED / CRITICAL; agent count, PRs, weekly completions  
- **Alerts** — watchdog issues (hidden when empty)  
- **Active WO** — claim, backend, step, age, last push, CI badge  
- **Pending validation** — human checkpoint waiting  
- **Pending approval** — P1 (etc.) pre-dispatch Approve / Skip / Hold  
- **Agent-runner** — online if draft server `:8101` answers  
- **WO board / PR queue / CI / Dispatch queue** — enriched cards and checks  

## PM

Chat plus program roll-up, blocked alerts, velocity, milestones, recommendations, active agents. Fastest path for create/dispatch/merge — [PM Chat](PM-Chat).

## Engineering

Open PRs with per-check CI, runner jobs, queue depth, flaky checks, timing, stale PRs. Use when diagnosing product CI without hunting on GitHub.

## Plan

Milestone cards, phase progress, full priority queue: edit ✎, hold ⏸, resume ▶, **Create WO**. Day-to-day queue surgery lives here. Planning structures: [Phases and Milestones](Phases-and-Milestones).

## Factory

Runner status line, **Active Jobs**, **Live Feed** (filter `?wo=WO-NNN`), Dependabot panel, API usage. Per-backend “working” cards were removed — status comes from live jobs.

## WO threads (`/wo/NNN`)

No separate Threads tab. From Overview/PM “View thread →”:

- Spec  
- Agent + system messages  
- Optional screenshots from connected tools  
- Peer-review findings after the quality gate  

## Settings → Get Started

Interactive four-step wizard: GitHub token/repo → product checkout (path/clone/scaffold) → agent/LLM (detect CLI, set preferred, start daemon) → ready checklist with **PM chat** (agent helps) or self-serve remaining GitHub steps. Overview shows a banner until onboarding looks complete.

## Settings → Authentication

| Field | Role |
|-------|------|
| GitHub fine-grained PAT (`github_pat_...`) | Product + engine: Contents, PRs, Issues, Actions. No `gist`. Classic `ghp_` / `gho_` rejected |
| Repository (`owner/name`) | Product repo for WO specs and PRs — saved via orchestrator secrets and mirrored to host prefs |
| Local directory / Clone / Prepare files | Host product checkout — written by the agent-runner into `~/.config/factory-agent/prefs`; optional `factory.yaml` scaffold |
| Anthropic API key | `claude-api`, PM, drafting, many Actions scripts (managed under Settings → Agents for presence) |
| ntfy / Slack webhook / Slack bot tokens | [Notifications](Notifications) |

Presence badges only for secret values — tokens stay in Vault. Changing **Local directory** requires `make restart` so Docker remounts `${LOCAL_REPO_PATH}`. For first-time users prefer **Get Started** over editing these fields piecemeal.

## Settings → Agents

- **LLM Providers** — which CLIs exist and how to install them  
- **Automation Model** — Anthropic model for PM / drafting / Actions (`ANTHROPIC_MODEL` repo variable on the product)  
- **Review Model** — optional override for review scripts  
- **Preferred backend**, agent display name, timeout  
- **Force cross-LLM review** + per-role backends  
- Pre-dispatch priorities via orchestrator `REQUIRE_APPROVAL_FOR`  

Model changes apply on next use. Product repo and local path are managed under Settings → Authentication (path changes still need `make restart` for Docker remount).

## Settings → Plan

Queue list from product plan/specs, Create WO form, Add/Delete phase & milestone (orchestrator DB — immediate, no PR).

**Create WO form** writes a product WO under `docs/project_management/work_orders/` (and may open a PR depending on configuration). Use the adopters [WO_SPEC_FORMAT](../adopters/WO_SPEC_FORMAT.md) shape.

## Orchestrator env (compose)

| Variable | Default | Meaning |
|----------|---------|---------|
| `POLL_INTERVAL` | `300` | Seconds between loops |
| `MAX_PARALLEL_WOS` | `2` | Soft parallel cap |
| `REQUIRE_APPROVAL_FOR` | `P1` | Priorities needing Approve |
| `WO_PATH` | `docs/project_management/work_orders` | Spec directory in product |
| `DAILY_SUMMARY_HOUR` / `SUMMARY_ISSUE_NUMBER` | unset | Optional daily GitHub summary comment |

## Pre-dispatch approval

```text
queue → pending_approval → claimed → in_progress → awaiting_human → complete
```

Overview cards: Approve / Skip (24h) / Hold. P2/P3 skip unless you expand `REQUIRE_APPROVAL_FOR`.

## Advisory panels

Orchestrator writes `orchestrator.json` for dispatch/holding queues and PM recommendations. It does **not** write product branches by itself. Offline orchestrator → panels show “data unavailable,” not a hard crash.
