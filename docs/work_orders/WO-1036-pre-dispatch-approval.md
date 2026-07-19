# WO-1036 — Pre-Dispatch WO Approval

**Created:** 2026-07-19
**Priority:** P1
**Effort:** M
**Services:** orchestrator, status-site
**Depends on:** —

---

## Background

The factory dispatches WOs immediately when an agent is ready. There is no human checkpoint between "WO selected from queue" and "agent starts working." This caused WO-391 (Palo Alto + SASE adapters) to run for 23 hours on a Claude backend — the WO required connectors that don't exist in the environment, so the agent could never pass its own acceptance criteria. No alarm fired.

Pre-dispatch approval adds a mandatory review step for P1 WOs (and optionally P2). The human sees the WO spec, confirms the environment can support it, and then the agent starts. This is one screen interaction, not a blocker — approvals can queue and be processed in batch.

## What to Build

### Orchestrator changes

Add a `pending_approval` state to the dispatch lifecycle, between queue selection and agent claim:

```
queue → [pending_approval] → claimed → in_progress → awaiting_human → complete
```

New env var `REQUIRE_APPROVAL_FOR` (default: `P1`) — comma-separated priorities that require pre-dispatch approval. P2 and P3 dispatch immediately as today.

New endpoints:
- `GET /api/approvals` — list WOs pending approval (wo, title, priority, spec_summary)
- `POST /api/approvals/{wo_id}/approve` — move to claimed, dispatch to next available agent
- `POST /api/approvals/{wo_id}/skip` — move back to queue at lower priority (try again later)
- `POST /api/approvals/{wo_id}/hold` — move to held (same as existing hold)

The orchestrator's dispatch loop: when selecting the next WO, if `priority in REQUIRE_APPROVAL_FOR`, move to `pending_approval` and post a notification instead of dispatching. The agent runner's claim call gets a 423 (Locked) response for WOs in `pending_approval` state.

### Status site — Approvals panel

Add an "Approvals" section to the Factory tab (above Active Jobs) that appears only when there are pending approvals:

```
┌─ PENDING APPROVAL ──────────────────────────────────────────── 1 ─┐
│  WO-1036  P1  Pre-Dispatch WO Approval                             │
│  services: orchestrator, status-site  |  effort: M                 │
│  [View spec]  [Approve →]  [Skip]  [Hold]                          │
└────────────────────────────────────────────────────────────────────┘
```

"View spec" expands an inline markdown preview of the WO spec (first 40 lines). No navigation away from the factory tab.

### Notification

When a WO enters `pending_approval`, post to the existing Slack/notification channel:
```
⏳ WO-NNN needs approval before dispatch
   Title: ...
   Priority: P1 | Effort: M
   Approve: https://factory.url/factory#approvals
```

## Acceptance Criteria

- [ ] P1 WOs enter `pending_approval` state instead of being dispatched immediately
- [ ] `GET /api/approvals` returns pending WOs with spec summary
- [ ] Approve → agent claims the WO within the next poll cycle
- [ ] Skip → WO returns to queue, does not re-enter pending_approval for 24h
- [ ] Hold → WO moves to held state (existing behavior)
- [ ] Factory tab shows the approvals panel when approvals are pending; hidden otherwise
- [ ] Slack notification fires when WO enters pending_approval
- [ ] P2 and P3 WOs bypass approval and dispatch as today
- [ ] `REQUIRE_APPROVAL_FOR=P1,P2` env var correctly gates both priorities
- [ ] `make smoke-test` passes after rebuild

## Files

- `services/orchestrator/orchestrator.py` — add pending_approval state, new endpoints, REQUIRE_APPROVAL_FOR gate
- `services/status-site/templates/factory.html` — approvals panel
- `services/status-site/main.py` — approvals API proxy endpoints
