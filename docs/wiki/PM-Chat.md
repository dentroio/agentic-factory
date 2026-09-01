---
title: "PM Chat"
description: "Plain-language project lead: create WOs, dispatch, merge, phases — against your product"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# PM Chat

The PM tab is your AI project lead. Each turn includes live context for the **product** (`GITHUB_REPO`): queue, PRs, CI, Dependabot, phases, milestones, and session memory. You speak; it acts.

Needs a working Anthropic key (or another configured automation path) — [Troubleshooting](Troubleshooting) if chat says no backend.

## What it knows

- Open WOs (priority, effort, status) and top-of-queue order  
- Phases, milestones, blockers  
- Open PR / CI / Dependabot signals  
- Session prefs (preferred backend, recent dispatches)  

Suggestions are grounded in that brief, not invented cold.

## Create Work Orders

> I want rate limiting on the API — 100 req/min/user, 429 + Retry-After.

Review the drafted tier, effort, and criteria. Say “create it” or adjust first (“make it P2”). Specs land in the product WO folder and enter the queue.

Alternative: **Create WO** → **Settings → Plan → Create WO**. Details: [Work Orders](Work-Orders).

## Dispatch

> Start WO-375 with Cursor.  
> Dispatch WO-381 now.

Wakes the runner instead of waiting for the poll. Default backend follows Settings / session memory unless you name one.

## Merge and Dependabot

> Merge PR 308.  
> Approve and merge all passing Dependabot PRs.  
> Lodash Dependabot keeps failing — file a WO.

PM checks CI before merge and can open fix WOs for broken dependency PRs.

## Phases and milestones

> Create a Q3 phase targeting September 30.  
> Add milestone Beta Launch for August 15.

Changes hit the orchestrator immediately (no git). See [Phases and Milestones](Phases-and-Milestones).

## Images

Paste or drag screenshots/mockups into the chat input for UI bugs, designs, or error dumps.

## Action tags (automatic)

The PM emits tags the orchestrator executes. You do not type them:

| Tag | Effect |
|-----|--------|
| `[DISPATCH:WO-375:cursor]` | Claim + wake runner |
| `[PR:merge:308]` | Squash-merge PR |
| `[DEPENDABOT:approve-merge:308]` | Dependabot only |
| `[DEPENDABOT:rebase:308]` / `recreate` | Dependabot commands |
| `[CREATE_PHASE:id\|Label\|YYYY-MM-DD]` | Phase CRUD |
| `[CREATE_MILESTONE:id\|Label\|date]` | Milestone CRUD |
| `[DELETE_PHASE:…]` / `[DELETE_MILESTONE:…]` | Remove |

## Session memory

Preferred backend and notable decisions persist across orchestrator restarts within the session store. “Use Gemini from now on” sticks for later dispatches.
