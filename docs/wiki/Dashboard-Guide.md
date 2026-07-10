# Dashboard Guide

The factory dashboard runs at `http://localhost:8099`. It has five main tabs and a Settings section. The page auto-refreshes every 60 seconds.

## Overview

The landing page. Shows:

- **Active WO card** — the WO currently claimed by an agent, which agent backend is running it, and what step it is on. Clicking the WO number goes to the thread detail page.
- **Pending validation badge** — when an agent has requested human review and is waiting for your approval, this badge appears here. Click it to go to the WO thread.
- **Agent-runner status** — online/offline indicator. Online means the draft server on port 8101 is responding. Offline means the agent-runner process is not running on the host.
- **Quick stats** — WOs completed this week, active PRs, queue depth.
- **Recent completions** — last few WOs that reached `done`, with PR links.

If you are waiting on a notification, this tab tells you the current state at a glance without having to dig into threads.

## PM

The PM — your AI project lead — lives here. Left panel is the chat interface. Right panel shows:

- **Program roll-ups** — WOs grouped by program label, with completion percentages and velocity
- **Blocked alerts** — WOs stuck on dependencies or holds
- **Velocity bar chart** — completions per week over the last 8 weeks
- **Milestone progress** — which milestones are approaching and how many blocking WOs remain

The PM is the fastest way to do most things: create WOs, dispatch agents, merge PRs, manage phases and milestones. See [PM Chat](PM-Chat) for the full reference.

## Engineering

PR health and CI state. Shows:

- **All open PRs** for the repository — CI status (passing/failing/pending), staleness, auto-merge eligibility
- **CI run history** — recent runs with pass/fail status and links to the GitHub Actions run
- **Pass rate** — percentage of CI runs passing over the last 30 days
- **Stale PR list** — PRs that have not had activity in the configured staleness window (default: 3 days). The PR watchdog populates this.

Use this tab when you want to check the state of all in-flight PRs without clicking around GitHub. The watchdog detects merge eligibility — if a PR is green but not auto-merging, the eligibility badge tells you why (e.g., "requires human approval" for P1 WOs).

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

## WO Thread pages

There is no dedicated Threads tab. Instead, each WO has its own detail page at `/wo/NNN`, accessible via **"View thread →"** links that appear on the Overview tab and in the PM tab next to active WOs.

The WO thread page shows:

- The structured WO spec (title, problem, acceptance criteria, etc.)
- The message thread — agent status updates, system messages on lifecycle transitions, and any Q&A between the agent and the orchestrator
- Any annotated screenshots posted from connected browser tools
- The review findings from the peer review chain (after the quality gate runs)

Use these pages when you want to check what an agent is doing mid-run, or review what the AI reviewers flagged before approving a merge.

## Settings

The settings hub links to three sub-pages.

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

- **Preferred backend** — which AI backend executes WOs (Claude, Cursor, Codex, Gemini, or claude-api)
- **Agent name** — display name shown in the dashboard
- **Timeout** — seconds before a WO run is forcibly stopped (default: 7200)
- **Force cross-LLM review** toggle — when on (the default), reviewer roles are automatically assigned to different AI models from the one that wrote the code. When off, you assign reviewers manually using the per-reviewer dropdowns below.
- **Per-reviewer backend dropdowns** — only relevant when the force cross-LLM toggle is off. Set which backend runs each of the four reviewers: security, architecture, correctness, performance.

Changes here take effect on the next WO the runner picks up. No restart needed.

### Settings → Plan

The Plan Authoring Hub. This is where you manage the WO queue, phases, and milestones through the UI rather than the PM chat.

- **Open WOs list** — with hold/unhold and edit buttons
- **Create WO button** — goes to the new WO form
- **Phases section** — list of phases with Add/Delete controls
- **Milestones section** — list of milestones with Add/Delete controls

Phase and milestone changes go directly to the orchestrator database. They take effect immediately — no git commit, no PR.

The WO spec file is the exception: creating or editing a WO writes or updates a markdown file on disk. The orchestrator picks it up on the next poll.
