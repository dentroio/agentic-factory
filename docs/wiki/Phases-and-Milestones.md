---
title: "Phases and Milestones"
description: "Dispatch order (phases) vs delivery gates (milestones) for product Work Orders"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Phases and Milestones

Two planning tools on the **product** queue the engine drives.

| Tool | Job |
|------|-----|
| **Phases** | **When** a WO may dispatch (sequencing) |
| **Milestones** | **Whether** a named goal is done (gates) |

Manage in **Settings → Plan** or via [PM Chat](PM-Chat). Changes apply immediately in the orchestrator (no git).

## Phases

A phase has a label (`now`, `backlog`, `Q3`, …), optional target date, and a position. Dispatch order: phase position, then WO position within the phase. Pinned WOs float above phase order.

**Create:** Plan → Add Phase, or *“Create a now phase for current sprint work.”*  
**Assign:** set `phase` on the WO (create form or Plan table).  
**Delete:** removes the phase only — WOs stay in the queue unscoped.

## Milestones

A milestone has a label, target date, and progress from WOs that list its id in `blocks_milestones`.

**Create:** Plan → Add Milestone, or *“Add milestone Beta Launch for August 15.”*  
**Connect:** in the WO spec / form:

```text
blocks_milestones: ["beta-launch"]
```

Many WOs can block one milestone; one WO can block many. At 100% complete there is **no** auto-ship — you decide to tag/release.

## Programs vs phases vs milestones

| Concept | Effect |
|---------|--------|
| **Program** | Free-text initiative label; PM grouping only |
| **Phase** | Dispatch timing |
| **Milestone** | Delivery gate count |

Combine freely (e.g. one Launch program, phases `now`/`next`, milestone `beta-launch`).

## Example: beta gate

1. Milestone `Beta Launch` → Aug 15.  
2. Essential WOs: `blocks_milestones: ["beta-launch"]`.  
3. Phase `beta-prep` for those; `post-beta` for the rest.  
4. Watch the Plan card tick 0/N → N/N, then ship.

Or one PM turn: *“Ship beta Aug 15; WO-370–374 are essential — set milestone and phases.”*

Also see [Work Orders](Work-Orders) for `depends_on`.
