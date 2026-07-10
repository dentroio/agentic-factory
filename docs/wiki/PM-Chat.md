# PM Chat

The PM tab hosts an AI assistant that has live context about everything in the factory: the WO queue, open PRs, CI state, Dependabot activity, phases, milestones, and your agent memory. You talk to it in plain language. It takes action directly — no confirmation step, no separate UI.

## What the PM knows

Every PM chat turn begins with a situational brief injected into the system prompt:

- Open WOs with their priority, effort, and status
- The top 10 queue entries in dispatch order
- Active phases and their target dates
- Milestone target dates and which WOs are blocking them
- Current PM session memory (preferred backend, recent decisions, dispatched WOs)

This means the PM's suggestions about priority and effort are grounded in what's actually in flight, not drafted blind.

The PM also has access to PR state (open PRs, CI health) and Dependabot PR status.

## Creating work orders

Tell the PM what you want to build:

> "I want to add rate limiting to the API — 100 requests per minute per user, with a 429 response and a Retry-After header."

The PM will propose a structured WO spec: title, priority tier, effort estimate, acceptance criteria. Review it. If it looks right, say "create it" or "looks good." The PM creates the WO and adds it to the queue. No separate form needed.

If you want to adjust anything before creating:

> "Make it P2 instead of P1, and drop the Retry-After header from the criteria."

The PM updates the draft and creates the revised spec.

The **Create WO** button in the PM tab is an alternative: it opens the form at **Settings → Plan → Create WO** with the AI draft workflow.

## Dispatching work orders

Once a WO is in the queue, tell the PM to start it:

> "Start WO-375 with Cursor."
> "Dispatch WO-381 now."

The PM sends a dispatch signal to the orchestrator, which wakes the agent runner immediately. The WO is claimed within seconds instead of waiting for the next poll cycle.

The PM chooses a sensible default backend based on what's available and what you've used recently. Override it explicitly if you want a specific model.

## Merging PRs

> "Merge PR 308."
> "Approve and merge the dark mode PR."

The PM uses the GitHub API to approve and merge the PR. It checks CI status first and will warn you if checks are still running or failing.

## Managing Dependabot PRs

Dependabot PRs with CI failures, merge conflicts, or outdated branches can be handled through the PM:

> "Rebase the Dependabot PRs that have conflicts."
> "Approve and merge all passing Dependabot PRs."
> "The lodash Dependabot PR keeps failing — create a WO to fix it."

For the last case, the PM creates a WO that describes the dependency issue and queues it for an agent to investigate.

## Creating phases and milestones

> "Create a Q3 phase targeting September 30."
> "Add a milestone called 'Beta Launch' for August 15."
> "Delete the 'backlog' phase."

The PM calls the orchestrator API directly. Phases and milestones appear in the Plan tab immediately — no PR, no git operation.

See [Phases and Milestones](Phases-and-Milestones.md) for how phases control dispatch order and milestones declare delivery gates.

## Image support

Paste or drag a screenshot or mockup directly into the PM chat input. The PM can see it and reason about it. Use this to:

- Show a UI bug: "Here's what I'm seeing — the button is misaligned on mobile"
- Describe a feature from a mockup: "Build this — here's the design"
- Share an error screenshot: "Why is this happening?"

## Action tags

The PM emits structured action tags that the orchestrator processes automatically. You never type these yourself — they appear in the PM's response when it is taking an action.

| Tag | What it does |
|-----|-------------|
| `[DISPATCH:WO-375:cursor]` | Claims WO-375 and wakes the agent runner with the Cursor backend |
| `[PR:merge:308]` | Merges GitHub PR #308 |
| `[PR:approve:308]` | Approves GitHub PR #308 |
| `[CREATE_PHASE:Q3:2026-09-30]` | Creates a phase named Q3 with target date Sep 30 |
| `[DELETE_PHASE:backlog]` | Deletes the phase with that ID |
| `[CREATE_MILESTONE:Beta Launch:2026-08-15]` | Creates a milestone with that name and date |

These tags are parsed and executed server-side as soon as the PM's response completes. The action confirmation appears in the PM's next message.

## Session memory

The PM remembers your preferred backend, notable decisions, and which WOs have been dispatched this session. This persists across container restarts. If you change your preferred backend mid-session ("use Gemini from now on"), the PM stores that preference and applies it to future dispatches.
