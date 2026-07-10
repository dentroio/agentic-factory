# Work Orders

A work order (WO) is the unit of work the factory dispatches to an agent. Every WO has a structured spec file that describes the problem, what to build, and how to verify it was done correctly. Agents read the spec before starting and follow its acceptance criteria as the exit condition.

## What a WO spec contains

WO specs are markdown files stored at `docs/project_management/work_orders/WO-NNN-slug.md`. The key sections:

| Field | Purpose |
|-------|---------|
| **Title** | Short description of what's being built |
| **Priority** | P0–P3 — controls merge workflow (see below) |
| **Effort** | XS / S / M / L / XL — size estimate |
| **Problem** | What's broken or missing, and why it matters |
| **What to Build** | Concrete description of the implementation |
| **Acceptance Criteria** | Verifiable checklist — the agent uses this as the exit condition, and the post-merge verifier checks it against the diff |
| **Documentation Required** | Files that must be updated as part of this WO (optional) |
| **Execution** | Agent instructions injected at the start of every prompt — project-specific rules, service names, make targets |
| **Notes** | Context that helps but does not gate completion |

## Priority tiers

Priority determines what the agent does after opening a PR.

| Tier | Use for | After PR is opened |
|------|---------|-------------------|
| **P0** | Auth changes, security fixes, data loss risk | Human reviews and approves manually |
| **P1** | Core features, schema changes, API contracts | Human reviews and approves manually |
| **P2** | Additive features, tests, refactors, docs | Agent sets `--auto-merge`; merges when CI passes |
| **P3** | Docs and PM files only, no code | Agent commits directly to `main` — no PR |

When in doubt, use P1 for anything you would want to read before it lands in main. Use P2 for anything where CI passing is sufficient validation.

## Effort sizes

Effort is an estimate, not a budget. It is used for velocity tracking and for the PM assistant's planning context.

| Size | Rough scope |
|------|------------|
| XS | A few lines — config change, copy fix |
| S | A single focused function or endpoint |
| M | A feature with tests, typically 1–3 hours of agent work |
| L | Multiple services or files, likely requires iteration |
| XL | Multi-session, large scope — consider splitting |

## Creating a WO

**From the UI (recommended):** Go to **Settings → Plan → Create WO**. Write a plain-language description of what you want to build. Choose which AI backend generates the structured spec. The AI produces a draft with all fields pre-filled based on your description and the current queue context. Review and edit the fields, then click **Save**. The WO is written to disk and registered in the queue immediately.

**From the PM chat:** Describe what you want. The PM drafts the spec inline and creates the WO when you confirm. See [PM Chat](PM-Chat.md).

**From a GitHub issue:** Label any issue `new-wo`. The `planning-agent.yml` workflow picks it up, calls the planning agent, and opens a PR with a structured spec. Merge the PR to add the WO to the queue. See [GitHub Integrations](GitHub-Integrations.md).

## Editing a WO

Each WO row in **Settings → Plan** has an ✎ button. Clicking it opens the raw markdown spec in an editor. Saving writes the updated file to disk. The agent picks up the updated spec on its next poll cycle — no restart needed.

Changes to a WO that is already in progress (status `in_progress`) take effect if the agent has not yet reached the step they affect. For in-flight changes, post a message in the WO thread to let the agent know what changed.

## Holding and resuming a WO

**⏸ Hold** prevents the orchestrator from claiming a WO. Use it when:
- A dependency is not merged yet
- You want to defer work without removing it from the queue
- You need to block dispatch until external conditions are met

**▶ Resume** re-enables a held WO. The hold state persists across factory restarts.

Hold and resume buttons appear on each WO row in **Settings → Plan**.

## How a WO moves through the queue

```
open → claimed → in_progress → review → done
```

| Status | Meaning |
|--------|---------|
| `open` | In the queue, waiting to be claimed |
| `claimed` | Agent has created the claim file and started the branch |
| `in_progress` | Agent is actively implementing; sending heartbeats |
| `review` | Quality gate passed; waiting for your approval |
| `done` | PR merged; verifier ran |

The orchestrator auto-removes WOs from the queue when their spec file shows a done status (✅ Complete, ⏸ Deferred). No manual cleanup needed.

If a WO is stuck at `claimed` but the agent is not sending heartbeats (visible in the Overview tab), the runner may have crashed. Restart it with `make agent-run`. The WO will be re-claimed.

## The `blocks_milestones` field

A WO can declare that it must complete before certain milestones are considered done:

```
blocks_milestones: ["beta-launch", "q3-release"]
```

The milestone progress card in the Plan tab counts down WOs with `blocks_milestones` referencing that milestone. When all blocking WOs are done, the milestone is complete.

Set this field in the WO edit form or when creating via the PM chat ("this should block the Beta Launch milestone").

## The `depends_on` field

A WO can declare prerequisites:

```
depends_on: ["WO-370", "WO-371"]
```

The orchestrator skips a WO when any of its dependencies have not yet reached `done`. Once all dependencies complete, the WO becomes eligible and will be picked up in normal queue order.

The PM assistant reads `depends_on` from the queue and includes this context in planning conversations.

## Programs

Programs are a free-text label on WOs that group related work into an initiative. Examples: `"Launch Program"`, `"Identity-to-Policy"`, `"Q3 Hardening"`.

Set the program label in the WO spec's metadata. The PM tab groups WOs by program label and shows velocity and progress per program. There is no programs management screen — the label is all you need.

Programs do not affect dispatch order or merge behavior. They are purely organizational.
