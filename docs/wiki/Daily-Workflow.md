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

If the agent-runner is active, the **Overview** tab shows which WO is currently claimed and what step the agent is on.

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

The fastest path is the PM tab. Describe what you want in the chat box:

> "I want to add a dark mode toggle to the settings page."

The PM drafts a structured spec — title, priority, effort, acceptance criteria — and confirms the details with you. Say "create it" and the PM writes the WO and adds it to the queue. You never write the spec yourself.

Alternatively, go to **Settings → Plan → Create WO**. Describe the feature in plain language, pick which AI generates the spec, review the generated fields, and click **Save**. The WO lands in the queue immediately.

See [Work Orders](Work-Orders.md) for everything about WO specs, priority tiers, and the queue lifecycle.

## Dispatching a WO

If the agent runner is running, it picks up the next available WO automatically after completing the current one. You do not need to do anything.

To dispatch a specific WO right now, tell the PM:

> "Start WO-375 with Cursor."

The PM sends a dispatch signal that wakes the runner immediately, bypassing the polling interval.

## Monitoring progress

Navigate to the WO detail page (`/wo/375`) — linked from the Overview tab as "View thread →". You will see:

- A live feed of what the agent is doing (streamed from the agent runner)
- System messages when the WO transitions states (claimed, validation requested, approved)
- Any Q&A exchanges between you and the agent
- Screenshots posted via the Oryntra browser extension, if used

The **Overview** tab shows the current agent step at a glance. The agent posts a checkin every time it moves to a new step.

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
