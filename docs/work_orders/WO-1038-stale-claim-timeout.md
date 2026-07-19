# WO-1038 — Stale Claim Timeout and Dead Agent Detection

**Created:** 2026-07-19
**Priority:** P1
**Effort:** S
**Services:** orchestrator
**Depends on:** —
**Status:** ✅ Done

---

## Background

When an agent process dies mid-WO, the orchestrator keeps the WO in `in_progress` state indefinitely. The heartbeat (checkin) interval is 2 minutes, but there is no server-side timeout that expires stale claims. The result: WOs show as "in progress" on the dashboard for hours after the agent died. The next agent cannot claim them. The factory appears to be working when it is not.

Observed: three WOs (WO-375, WO-407, WO-408) showed as active with checkins 49–57 minutes old. No agent was running. Had to manually call `/api/wos/{wo_id}/hold` three times to release them.

## What to Build

### Stale claim expiry in the orchestrator poll loop

Add `CLAIM_TIMEOUT_SECONDS` env var (default: `600` — 10 minutes). In the orchestrator's existing poll loop, add a stale-claim sweep:

```python
for wo_id, entry in list(dispatch_state.items()):
    if entry.get("status") not in ("in_progress", "claimed"):
        continue
    last_seen = entry.get("last_seen")
    if not last_seen:
        continue
    age = (datetime.utcnow() - datetime.fromisoformat(last_seen)).total_seconds()
    if age > CLAIM_TIMEOUT_SECONDS:
        logger.warning(f"[orchestrator] {wo_id} stale claim ({age:.0f}s) — releasing")
        dispatch_state[wo_id]["status"] = "stale"
        dispatch_state[wo_id]["stale_at"] = datetime.utcnow().isoformat()
        # Post thread message so the failure is visible
        await post_thread_message(wo_id, f"⚠️ Claim expired after {age/60:.0f} minutes — agent appears dead. Re-queueing.")
```

WOs in `stale` status are treated the same as `planned` by the dispatch loop — available for re-claim.

### Stale badge in the UI

The Active Jobs list already shows checkin age (`tsRel`). Add a visual indicator when age > 10 minutes:

```
WO-407  in progress  ⚠ stale 57m
```

Replace the indigo dot with an amber dot, add "stale Nm" label. No other changes needed — `tsRel` already calculates the age.

### Notification on expiry

When a claim expires, post to the Slack/notification channel:
```
⚠️ WO-NNN claim expired (57 min since last checkin) — agent appears dead. Re-queued.
```

## Acceptance Criteria

- [ ] WO in `in_progress` with no checkin for >10 minutes automatically moves to `stale`
- [ ] Stale WOs are re-claimable by the next available agent
- [ ] Dashboard shows amber "stale Nm" badge on jobs with old checkins
- [ ] Thread message posted when claim expires
- [ ] Slack notification fires on expiry
- [ ] `CLAIM_TIMEOUT_SECONDS=300` env var reduces timeout to 5 minutes (configurable)
- [ ] `make smoke-test` passes

## Files

- `services/orchestrator/orchestrator.py` — stale sweep in poll loop, CLAIM_TIMEOUT_SECONDS
- `services/status-site/templates/factory.html` — stale badge in active jobs JS
