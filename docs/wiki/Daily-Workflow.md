---
title: "Daily Workflow"
description: "Day-to-day loop for starting the factory, dispatching work orders, and reviewing results"
last_verified: 2026-07-30
covers_wos:
  - WO-1002
  - WO-1003
  - WO-1008
  - WO-1036
  - WO-1038
doc_owner: factory-team
---

# Daily Workflow

This is the loop you run every day. The factory is stateful — it remembers what's in the queue, which WOs are in progress, and what the PR watchdog has seen. You do not need to reset or re-initialize anything between sessions.

## Starting the factory

```bash
make up
open http://localhost:8099
```

That is usually all you need. The orchestrator polls GitHub every 5 minutes. The PR watchdog tracks every open PR in the background. The dashboard auto-refreshes every 60 seconds by default.

First time on a new machine:

```bash
make agent-setup    # stores GitHub token, Anthropic key, ntfy topic in macOS Keychain
make up
```

Then open **Settings → Authentication** and verify the credential badges are green.

## Checking queue health

Open the **Plan** tab. You will see:

- The priority queue, sorted by position (pinned WOs float to the top)
- Phase assignments — which WOs are in "now" vs. "backlog"
- Milestone cards showing how many blocking WOs remain
- Hold status — a ⏸ badge means the orchestrator is skipping that WO

If the agent-runner is active, the **Overview** tab shows which WO is currently claimed and what step the agent is on. Jobs with no checkin for more than 10 minutes show an amber **stale Nm** badge — the orchestrator will automatically release and re-queue them after `CLAIM_TIMEOUT_SECONDS` (default: 600).

## Starting the agent runner

The agent runner is a host process, not a Docker container. It needs access to your AI CLI (Claude, Cursor, Codex, or Gemini). Start it in a separate terminal:

```bash
make agent-run
```

Or to claim and complete exactly one WO then stop:

```bash
make agent-once
```

The runner polls the orchestrator for the next available WO, claims it, and starts working. It streams progress to the WO's thread, visible on the WO detail page (`/wo/NNN`).

## Creating a new work order

The fastest path is to open the PM tab and describe what you want:

> "I want to add a dark mode toggle to the settings page."

The PM drafts a structured spec — title, priority, effort, acceptance criteria — and confirms the details with you. Say "create it" and the PM writes the WO and adds it to the queue. You never write the spec yourself.

Alternatively, go to **Settings → Plan → Create WO**. Describe the feature in plain language, pick which AI generates the spec, review the generated fields, and click **Save**. The WO lands in the queue immediately.

See [Work Orders](Work-Orders.md) for everything about WO specs, priority tiers, and the queue lifecycle.

## Dispatching a WO

If the agent runner is running, it picks up the next available WO automatically after completing the current one. You do not need to do anything — unless the WO requires pre-dispatch approval (see below).

To dispatch a specific WO right now, tell the PM:

> "Start WO-375 with Cursor."

The PM sends a dispatch signal that wakes the runner immediately, bypassing the polling interval.

### Cloud dispatch via Codex (GitHub Actions)

For P3 or docs-only WOs with `services: none`, the orchestrator can dispatch work through GitHub Actions instead of a local agent runner. No Docker worktree or developer machine is required.

```bash
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-362","slug":"sync-in-app-help"}'
```

The orchestrator pre-claims the WO as `codex-gh-actions`, triggers the `codex-dispatch.yml` workflow in the target repo, and then detects the resulting branch and PR automatically through its normal poll loop. No callback is needed. Requires `OPENAI_API_KEY` set as a secret in the target repo.

### Pre-dispatch approval (P1 WOs)

P1 WOs do not dispatch immediately. Instead they enter a **pending approval** state. You will receive a push notification and the **Factory** tab will show an Approvals panel above the Active Jobs list:

```
┌─ PENDING APPROVAL ──────────────────────────────────────────── 1 ─┐
│  WO-1036  P1  Pre-Dispatch WO Approval                             │
│  services: orchestrator, status-site  |  effort: M                 │
│  [View spec]  [Approve →]  [Skip]  [Hold]                          │
└────────────────────────────────────────────────────────────────────┘
```

- **Approve** — the agent claims the WO on the next poll cycle.
- **Skip** — the WO returns to the queue and will not re-enter pending approval for 24 hours.
- **Hold** — the WO moves to the held state.

"View spec" expands an inline markdown preview of the WO spec without navigating away. P2 and P3 WOs bypass approval and dispatch as normal. The set of priorities that require approval is configurable via `REQUIRE_APPROVAL_FOR` (default: `P1`).

## Monitoring progress

Navigate to the WO detail page (`/wo/375`) — linked from the Overview tab as "View thread →". You will see:

- A live feed of what the agent is doing (streamed from the agent runner)
- System messages when the WO transitions states (claimed, validation requested, approved)
- Any Q&A exchanges between you and the agent
- Screenshots posted via the Oryntra browser extension, if used

The **Overview** tab shows the current agent step at a glance. The agent posts a checkin every time it moves to a new step.

### Dashboard views

The status site offers three audience-specific views, all accessible from the navigation tabs:

| Route | Audience | What you see |
|-------|----------|-------------|
| `/` | Everyone | Health banner, alert panel, enriched WO board, active work, PR queue |
| `/pm` | Project managers | WOs by program, velocity chart, blocked items, active agents |
| `/ci` | CI/CD engineers | Runner utilization, queue depth, per-PR CI breakdown, flaky detection |

The health banner at the top of `/` shows system state at a glance (● HEALTHY / ⚠ DEGRADED / ✖ CRITICAL). An alert panel appears below it when the PR watchdog has flagged issues — it disappears automatically when there are no active alerts.

WO cards on the board show age badges (color-ramped green → amber → red past 7 days), the assigned agent name, current step, and a direct PR link when one exists. Jobs in the Active Work panel display how long the agent has been working and the time since the last git push.

### Stale agent detection

The orchestrator sweeps for stale claims on every poll. If a WO has been in `in_progress` or `claimed` state with no checkin for longer than `CLAIM_TIMEOUT_SECONDS` (default: 600 seconds), it is automatically moved to `stale`, a message is posted to the WO thread, and a notification fires. Stale WOs are immediately available for re-claim by the next available agent. The dashboard shows an amber **stale Nm** badge on any job whose last checkin is older than 10 minutes.

## The human checkpoint

Every WO — regardless of priority tier — requires your sign-off before the agent commits and opens a PR. When the agent finishes implementing and the quality gate passes, it posts a message to the WO thread asking you to verify. You get a push notification (if ntfy is configured) at high priority.

Verify what the agent built: run the app, hit the endpoint, check the UI. If it looks right, reply in the thread or click the approve button on the WO detail page.

If something is wrong, describe the issue in the thread. The agent reads thread messages and will iterate.

## After approval

Once you approve, the agent:
1. Commits the work
2. Opens a PR
3. Sets `--auto-merge` if the WO is P2

GitHub CI runs. The AI code review runs. The merge advisor synthesizes everything and posts a recommendation comment.

- **P2**: merges automatically once all checks pass. The watchdog monitors CI and flags anything stale.
- **P1/P0**: you review the PR and merge manually when you're satisfied.

After merge, the verifier checks the acceptance criteria against the diff. If criteria aren't met, it opens a follow-up issue. The memory agent extracts lessons and opens a memory PR.

## End of day

There is nothing to shut down if you want the watchdog to keep running overnight. The Docker services are lightweight and idle when there is no active work.

If you want to stop everything:

```bash
make down
```

The queue, hold list, and all thread history persist in the Docker volume (`/data/`). Nothing is lost on restart.