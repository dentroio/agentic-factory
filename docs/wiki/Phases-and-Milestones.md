---
title: "Phases and Milestones"
description: "Controlling WO dispatch order with phases and declaring delivery gates with milestones"
last_verified: 2026-07-11
covers_wos: []
doc_owner: factory-team
---

# Phases and Milestones

Phases and milestones are the two planning structures in the factory. They solve different problems.

**Phases** control when WOs get dispatched. A WO in the "now" phase is picked up before a WO in the "backlog" phase, even if the backlog WO has a higher position number. Phases are about sequencing.

**Milestones** are delivery gates. A milestone is "done" when all WOs that block it have completed. Milestones are about measuring progress toward a named goal.

## Phases

Phases are managed in **Settings → Plan → Phases**. The help text there says: "Controls when WOs get picked up by the orchestrator."

A phase has:
- A label (e.g., "now", "next", "backlog", "Q3")
- A target date (optional)
- A position that sets its dispatch priority relative to other phases

The orchestrator orders WOs first by phase position, then by their position within the phase. A pinned WO floats above all phase ordering.

### Creating a phase

From the Plan settings page, click **Add Phase** and fill in the label and optional target date.

From the PM chat:

> "Create a 'now' phase for current sprint work."
> "Add a Q3 phase targeting September 30."

The phase appears in the Plan tab and the WO queue immediately.

### Assigning a WO to a phase

Set the `phase` field when creating a WO, or edit it in the WO queue via the **Settings → Plan** table. Changing a WO's phase affects the next dispatch decision — the orchestrator reads phase assignments live.

### Deleting a phase

From the Plan settings page, click the delete button on the phase row.

From the PM chat:

> "Delete the backlog phase."

WOs assigned to a deleted phase are not deleted — they remain in the queue without a phase assignment and are ordered by position only.

## Milestones

Milestones are managed in **Settings → Plan → Milestones**. The help text there says: "Delivery gates — a milestone is done when all blocking WOs complete."

A milestone has:
- A label (e.g., "Beta Launch", "Q3 Release")
- A target date
- A progress count driven by WOs with `blocks_milestones` referencing that milestone's ID

### Creating a milestone

From the Plan settings page, click **Add Milestone**.

From the PM chat:

> "Add a milestone called 'Beta Launch' for August 15."
> "Create a Q3 release milestone targeting September 30, 2026."

### Connecting WOs to a milestone

In the WO spec or the queue edit form, set the `blocks_milestones` field to include the milestone's ID. The milestone progress card counts down as those WOs complete.

Multiple WOs can block the same milestone. A WO can block multiple milestones.

### Milestone completion

When all WOs blocking a milestone reach `done` status, the milestone card in the Plan tab shows 100% complete. There is no automatic action on milestone completion — it is a signal for you to ship, tag a release, or declare a phase done.

## How they relate to Programs

Programs, phases, and milestones are independent concepts that you can combine however makes sense for your project.

A **program** is a label grouping WOs into an initiative (e.g., "Launch Program"). WOs from the same program can span multiple phases and block multiple milestones.

A **phase** controls dispatch timing — work in the "now" phase runs before work in the "backlog" phase.

A **milestone** declares a gate — all WOs blocking the milestone must complete before you can declare it done.

A typical setup: one program ("Launch Program") spans two phases ("now" for immediate work, "next" for what's after), with a single milestone ("Beta Launch") that the critical WOs block.

## Practical example: setting up a beta release gate

You want to ship a beta on August 15. You have 12 WOs queued. Five of them are essential for beta. The others can wait.

1. Create a milestone: "Beta Launch" targeting August 15.
2. For each of the five essential WOs, set `blocks_milestones: ["beta-launch"]`.
3. Create a "beta-prep" phase for the five WOs and a "post-beta" phase for the rest.
4. Assign WOs to phases accordingly.

Now the Plan tab shows a Beta Launch card with 0/5 complete. As WOs merge, the counter ticks up. On August 15, if all five show done, you ship. The seven post-beta WOs stay queued and will be dispatched after the beta phase clears.

From the PM chat, you could set this up in a single conversation:

> "I want to ship a beta on August 15. WO-370 through WO-374 are the essential ones. Set up a milestone and phase for this."
