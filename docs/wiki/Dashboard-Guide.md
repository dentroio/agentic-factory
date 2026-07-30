---
title: "Dashboard Guide"
description: "Factory dashboard tabs, settings, and controls at localhost:8099"
last_verified: 2026-07-30
covers_wos:
  - WO-1002
  - WO-1003
  - WO-1014
  - WO-1035
  - WO-1036
doc_owner: factory-team
---

# Dashboard Guide

The factory dashboard runs at `http://localhost:8099`. It has six main tabs and a Settings section. The page auto-refreshes every 60 seconds.

## Overview

The landing page. Shows:

- **Health score banner** — a single line at the top indicating overall system state: `● HEALTHY`, `⚠ DEGRADED`, or `✖ CRITICAL`. Derived from watchdog data and runner state. Includes active agent count, PRs in flight, WOs completed this week, and runner utilization.
- **Alert panel** — appears below the header only when alerts exist. Each alert shows severity, PR number, rule label, and duration (e.g., `[ERROR] #204 pytest-asyncio — CI failing for 127m`). Collapses if more than 5 alerts; hidden entirely when no alerts are present.
- **Active WO card** — the WO currently claimed by an agent, which agent backend is running it, what step it is on, how long it has been running, the last git push time, and an inline CI badge if a PR exists. Clicking the WO number goes to the thread detail page.
- **Pending validation badge** — when an agent has requested human review and is waiting for your approval, this badge appears here. Click it to go to the WO thread.
- **Pending approval panel** — if any P1 WOs are waiting for pre-dispatch approval, they appear here with **Approve**, **Skip**, and **Hold** buttons. The panel is hidden when there are no pending approvals.
- **Agent-runner status** — online/offline indicator. Online means the draft server on port 8101 is responding.
- **WO board (enriched kanban)** — each WO card shows an age badge (`2d`, `5d`, `14d` — green to amber to red past 7 days), the assigned agent name or `unassigned`, the current step, a block reason if applicable, and a direct PR link.
- **PR queue (enriched table)** — all open PRs with per-check CI icons (✅ ❌ ⏳), auto-merge indicator, merge conflict badge, age color, and inline watchdog flags.
- **CI Health panel** — runner utilization bar, queue depth, average CI time, and 7-day rolling pass rate.
- **Dispatch Queue panel** — WOs ready to start (from `orchestrator.json`), shown in priority order. Includes WOs that are holding due to unmet dependencies.
- **Quick stats** — WOs completed this week, active PRs, queue depth.
- **Recent completions** — last few WOs that reached `done`, with PR links.

If you are waiting on a notification, this tab tells you the current state at a glance without having to dig into threads.

## PM

The PM — your AI project lead — lives here. Left panel is the chat interface. Right panel shows:

- **Program roll-up table** — WOs grouped by program label, with total WOs, done, in-progress, blocked, open, and completion percentage. WOs without a program field appear under "Standalone."
- **Blocked alerts** — WOs stuck on dependencies or CI failures, with how long they have been blocked
- **Velocity bar chart** — WOs completed per week over the last 8 weeks
- **Milestone progress** — which milestones are approaching and how many blocking WOs remain
- **Recommendations panel** — plain-text advisory from the orchestrator (e.g., "WO-1001 is ready to start — no dependencies, P2 priority"), timestamped so you know when the last advisory ran
- **Active agents table** — which agents are working, on which WO, what step, when they started, and for how long

The PM is the fastest way to do most things: create WOs, dispatch agents, merge PRs, manage phases and milestones. See [PM Chat](PM-Chat) for the full reference.

## Engineering

PR health and CI state. Shows:

- **All open PRs** for the repository — per-check CI breakdown (one icon per check instead of a single state label), staleness, auto-merge eligibility, merge conflict warning, and watchdog alert flags
- **Runner panel** — live runner names, current job, and how long each job has been running
- **Queue panel** — jobs waiting for a runner, with job type, branch, and how long they have been queued
- **PR CI breakdown table** — one row per check per PR, with state, duration, and attempt count
- **Flaky detection** — checks that have `attempts > 1` but eventually passed are flagged `⚠ flaky` and summarized at the top of the tab
- **CI timing panel** — average, fastest, and slowest CI times from the last 20 runs, broken down by check
- **Pass rate** — 7-day rolling pass rate
- **Stale PR list** — PRs with no activity in the configured staleness window (default: 3 days), populated by the PR watchdog

Use this tab when you want to diagnose pipeline issues or check the state of all in-flight PRs without clicking around GitHub.

## Plan

The planning hub. Shows:

- **Milestone cards** — progress bar per milestone, target date, number of blocking WOs remaining
- **Phase progress** — WOs per phase and their statuses
- **Priority queue** — full WO queue sorted by phase and position, with priority, effort, phase assignment, hold status, and action buttons
- **Add Phase / Add Milestone** buttons

From the queue table you can:
- Click ✎ to edit a WO spec
- Click ⏸ to hold a WO (prevents dispatch)
- Click ▶ to resume a held WO
- Click **Create WO** to go to the new WO form

This is the right tab for day-to-day queue management: reordering, holding WOs that are waiting on a dependency, and checking milestone progress.

## Factory

The Factory tab shows agent activity and the live log feed.

- **Status bar** — one line showing runner health (● online / ✖ offline), active WO count, the configured backend (e.g., `Cursor`), and the pause button. Replaces the old per-backend agent cards, which showed stale state.
- **Active Jobs list** (left column) — WOs currently being worked on.
- **Live Feed** (right column) — streaming log output from the agent runner. Filter by WO using the dropdown (e.g., select `WO-407` to see only that WO's log lines). The SSE endpoint accepts `?wo=WO-NNN`.
- **Dependabot PR panel** — Dependabot PRs and their CI state.
- **API usage banner** — current API usage indicators.

> **Note:** The per-backend agent cards (Claude / Cursor / Codex / Gemini) were removed in WO-1035. Stale dispatch state no longer causes misleading "Claude: working" displays.

## WO Thread pages

There is no dedicated Threads tab. Instead, each WO has its own detail page at `/wo/NNN`, accessible via **"View thread →"** links that appear on the Overview tab and in the PM tab next to active WOs.

The WO thread page shows:

- The structured WO spec (title, problem, acceptance criteria, etc.)
- The message thread — agent status updates, system messages on lifecycle transitions, and any Q&A between the agent and the orchestrator
- Any annotated screenshots posted from connected browser tools
- The review findings from the peer review chain (after the quality gate runs)

Use these pages when you want to check what an agent is doing mid-run, or review what the AI reviewers flagged before approving a merge.

## Settings

The settings hub links to four sub-pages.

### Settings → Authentication

Manage all credentials:

- **GitHub token** — classic PAT with `repo` and `read:org` scopes. Required for everything.
- **Anthropic API key** — required for the `claude-api` draft backend and for GitHub Actions AI workflows.
- **ntfy push notifications** — your auto-generated topic URL and server. Buttons to copy the subscribe URL, generate a new topic, and send a test notification.
- **Slack webhook** — for Slack channel notifications. Set it here to enable Slack alongside ntfy.
- **Slack bot tokens** — `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` for the conversational Slack bot (optional, separate from the webhook).

All credentials are stored in the orchestrator's secrets vault (`/data/secrets.json`). The page only shows presence badges (set/not set), never actual values.

### Settings → Agents

Configure how agents run:

- **LLM Providers** — the CLI-based backends available to execute WOs (Claude Code, Cursor, etc.): name, auth type (subscription/API key/both), CLI command, and — for subscription auth — the setup steps shown to whoever installs that agent. Purely descriptive/local config, stored on this dashboard only (not synced to any repo).
- **Automation Model** — the Claude model used by everything that calls the Anthropic API directly rather than through a CLI backend: WO drafting, PM chat, and the GitHub Actions scripts (`ai_review`, `planning_agent`, `doc_writer`, etc.). Separate from Execution Backend below, which is about *which tool* writes the code, not which model powers the surrounding automation. Persisted as a GitHub repo variable (`ANTHROPIC_MODEL`) on the repo this factory instance builds — the only thing readable by both this dashboard and the GitHub-Actions-run scripts, which have no network path back to your machine. Changing it here takes effect immediately for local calls (PM chat, WO drafting); GitHub Actions scripts pick it up on their next run.
- **Review Model** *(optional)* — overrides Automation Model specifically for code/merge review scripts (`ai_review`, `merge_advisor`). Exists because a single shared model can't express "sonnet for most things, but a cheaper/faster model for the review that runs on every single PR." Leave blank to inherit Automation Model. Persisted the same way, as `ANTHROPIC_MODEL_REVIEW`.
- **Preferred backend** — which AI backend executes WOs (Claude, Cursor, Codex, Gemini, or claude-api)
- **Agent name** — display name shown in the dashboard
- **Timeout** — seconds before a WO run is forcibly stopped (default: 7200)
- **Force cross-LLM review** toggle — when on (the default), reviewer roles are automatically assigned to different AI models from the one that wrote the code. When off, you assign reviewers manually using the per-reviewer dropdowns below.
- **Per-reviewer backend dropdowns** — only relevant when the force cross-LLM toggle is off. Set which backend runs each of the four reviewers: security, architecture, correctness, performance.
- **Pre-dispatch approval** — controlled by `REQUIRE_APPROVAL_FOR` on the orchestrator (default: `P1`). P1 WOs enter a `pending_approval` state before an agent is assigned. See [Pre-Dispatch Approval](#pre-dispatch-approval) below.

Changes here take effect on the next WO the runner picks up. No restart needed — this applies to Automation Model and Review Model too (unlike the target repo itself, `GITHUB_REPO`, which is read once at startup).

### Settings → Plan

The Plan Authoring Hub. This is where you manage the WO queue, phases, and milestones through the UI rather than the PM chat.

- **Open WOs list** — current `status=open` WOs from PLAN.json, with priority and phase, plus hold/unhold and edit buttons
- **Create WO button** — opens the WO creation form at `/settings/plan/wos/new`
- **Phases section** — collapsible list with Add/Delete controls
- **Milestones section** — collapsible list with Add/Delete controls

#### Creating a WO from the UI

The WO creation form at `/settings/plan/wos/new` includes:

- Auto-numbered WO (next available number computed from PLAN.json)
- Title, phase, priority (P0–P3), effort (XS–XL), services, depends-on, blocks-milestones
- Problem statement, what to build, acceptance criteria (dynamic list), notes

Submitting the form creates a feature branch, writes the WO markdown spec to `docs/factory/work_orders/WO-NNN-<slug>.md`, updates `PLAN.json`, and opens a PR for human review before the WO enters the dispatch queue. The submit button disables immediately on click to prevent double-submit.

Phase and milestone changes (Add/Delete) go directly to the orchestrator database and take effect immediately — no git commit, no PR needed.

### Settings → (Orchestrator)

The orchestrator is configured via environment variables in `docker-compose.status.yml`. Key variables:

| Variable | Default | Description |
|---|---|---|
| `POLL_INTERVAL` | `300` | Seconds between orchestrator loop runs |
| `DAILY_SUMMARY_HOUR` | _(unset)_ | UTC hour to post the daily GitHub issue summary |
| `SUMMARY_ISSUE_NUMBER` | _(unset)_ | GitHub issue to post daily summaries to |
| `MAX_PARALLEL_WOS` | `2` | Maximum WOs recommended in-progress simultaneously |
| `REQUIRE_APPROVAL_FOR` | `P1` | Comma-separated priorities that require pre-dispatch approval |
| `WO_PATH` | `docs/project_management/work_orders` | Path to WO spec files |

---

## Pre-Dispatch Approval

P1 WOs (and optionally P2, via `REQUIRE_APPROVAL_FOR=P1,P2`) do not dispatch immediately. Instead they enter a `pending_approval` state:

```
queue → pending_approval → claimed → in_progress → awaiting_human → complete
```

When a WO enters `pending_approval`, a Slack notification fires with a link to the approvals panel. The **Overview** tab shows the pending approval card with three actions:

- **Approve →** — the agent claims the WO on the next poll cycle
- **Skip** — returns the WO to the queue; it will not re-enter `pending_approval` for 24 hours
- **Hold** — moves the WO to held state

"View spec" expands an inline preview of the WO spec (first 40 lines) without leaving the tab.

P2 and P3 WOs bypass approval and dispatch immediately as before.

---

## Orchestrator Advisory

The orchestrator runs on a schedule (default: every 5 minutes) and writes `orchestrator.json`. The status site reads this file to populate:

- The **Dispatch Queue panel** on Overview and PM tabs — WOs ready to start, in priority order
- The **Holding Queue** — WOs whose dependencies are not yet met, with the blocking WO listed
- The **Recommendations panel** on the PM tab — human-readable advisory (e.g., "Both runners currently busy — wait before dispatching new work")

If `DAILY_SUMMARY_HOUR` and `SUMMARY_ISSUE_NUMBER` are configured, the orchestrator posts or updates a comment on that GitHub issue each day summarizing board state, ready WOs, in-progress work, blocked items, CI health, and weekly velocity.

The orchestrator is advisory only — it does not dispatch agents or write to branches. All write operations are opt-in (the daily GitHub comment requires both env vars to be set).

If the orchestrator is offline, the status site degrades gracefully: the dispatch queue and recommendations panels show "data unavailable" rather than erroring.