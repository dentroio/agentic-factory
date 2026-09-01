---
title: "Work Orders"
description: "Spec shape, risk tiers, effort, and queue lifecycle in the product repo"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Work Orders

A Work Order (WO) is one unit of agent work. Specs live in the **product** (`GITHUB_REPO`), default path:

`docs/project_management/work_orders/WO-NNN-slug.md`

Override with `WO_SPECS_DIR` if needed. Format and examples: [WO_SPEC_FORMAT.md](../adopters/WO_SPEC_FORMAT.md). Claims: [CLAIM_SCHEMA.md](../adopters/CLAIM_SCHEMA.md). Process: [PROCESS.md](../adopters/PROCESS.md). Verify command: product [`factory.yaml`](Product-Profile).

## Spec sections

| Section | Purpose |
|---------|---------|
| **Title / Priority / Effort** | Identity and merge policy |
| **Problem** | Why this exists |
| **What to Build** | Concrete implementation — agents should not invent architecture |
| **Acceptance Criteria** | Verifiable checklist (agent exit + post-merge verifier) |
| **Documentation Required** | Optional doc files that must change |
| **Execution** | Branch name, risk tier, PR title, PM updates — follow exactly |
| **Notes** | Context that helps but does not gate done |

## Priority tiers

| Tier | Use for | After the PR opens |
|------|---------|-------------------|
| **P0** | Auth, security, data-loss risk | Human merges |
| **P1** | Core features, schema, API contracts | Human merges |
| **P1** pre-dispatch | Same | Often needs Approve on Overview first |
| **P2** | Additive features, tests, refactors | Agent may `--auto` after CI |
| **P3** | Docs / PM only | Agent `--auto` after CI |

Prefer P1 when you want to read the diff before merge; P2 when green CI is enough.

## Effort

XS → XL estimates for velocity and PM planning — not hard budgets. Split XL work.

## Create

| Path | How |
|------|-----|
| UI | **Settings → Plan → Create WO** — plain language → AI draft → Save |
| PM | Describe → confirm → create ([PM Chat](PM-Chat)) |
| GitHub | Product issue labeled `new-wo` + pasted `planning-agent.yml` |

## Edit / hold

**Settings → Plan:** ✎ edit markdown; ⏸ hold (no claim); ▶ resume. Holds survive restarts. For an in-flight WO, also post in the thread so the agent sees the change.

## Lifecycle

```text
open → claimed → in_progress → review → done
```

| Status | Meaning |
|--------|---------|
| `open` | Eligible when deps and phase allow |
| `claimed` | Claim file on the WO branch; agent started |
| `in_progress` | Heartbeats / checkins |
| `review` | Quality gate passed; waiting on you |
| `done` | Merged; verifier may run |

Stuck `claimed` with no heartbeats → restart runner (`make agent-install` / `make agent-run`). See [Troubleshooting](Troubleshooting).

## `depends_on` and `blocks_milestones`

```text
depends_on: ["WO-370", "WO-371"]
blocks_milestones: ["beta-launch"]
```

Orchestrator skips WOs with unfinished dependencies. Milestone cards count blocking WOs — [Phases and Milestones](Phases-and-Milestones).

## Programs

Free-text initiative labels (e.g. `Launch`). Organizational only — PM tab groups by program; no effect on merge rules.
