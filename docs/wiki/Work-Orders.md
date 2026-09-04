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
| **Title / Priority / Effort / Services** | Identity, merge policy, and what to rebuild or verify |
| **Problem** | Why this exists: visible symptom, route, file, error, or operator pain |
| **What to Build** | Concrete implementation — agents should not invent architecture |
| **Out of scope / Do NOT change** | Adjacent work and hard invariants the agent must preserve |
| **Acceptance Criteria** | Verifiable checklist (agent exit + post-merge verifier) |
| **Documentation Required** | Optional doc files that must change |
| **Execution** | Branch name, risk tier, services, PR title, pre-PR gate, dependencies, user verification, PM updates — follow exactly |
| **Notes** | Context that helps but does not gate done |

Drafts may use narrative headings such as `Motivation`, `Background`, `Scope`, or `Approach`. Before dispatch, normalize the spec so agents and automation can find `Priority`, `Effort`, `Services`, dependencies, acceptance criteria, and `Execution`.

## Priority tiers

| Tier | Use for | After the PR opens |
|------|---------|-------------------|
| **P0** | Auth, security, data-loss risk | Human merges |
| **P1** | Core features, schema, API contracts | Human merges |
| **P1** pre-dispatch | Same | Often needs Approve on Overview first |
| **P2** | Additive features, UI, tests, refactors | Human verifies running product before commit; agent may `--auto` after CI + review |
| **P3** | Docs / PM only | Agent may `--auto` after CI; no product checkpoint |

Prefer P1 when you need to read the diff before merge; P2 when the running product checkpoint plus green CI and review are enough. One line of application code makes a WO at least P2; P3 is only for docs and PM markdown.

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
