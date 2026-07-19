# WO-1029 — Agent Stuck Detection and Timeout Alerting

**Created:** 2026-07-18
**Priority:** P2
**Effort:** M
**Services:** orchestrator, status-site
**Depends on:** WO-1024
**Status:** ✅ Done

---

## Background

When a factory agent gets stuck — network error, infinite loop, context exhaustion, or simply an impossible WO — it holds the WO in `status: claimed` indefinitely. The orchestrator has no timeout. The status site shows the WO as "In Progress" forever.

This happened with WO-391 (re-dispatched) — the second agent was running for hours before the human noticed. There was no alert, no timeout, no badge indicating the WO had been in claimed state unusually long.

Other cases where this matters:
- An agent opens a PR but then exits before calling `pr-watch` — the WO sits in `claimed` state after the PR is open
- A cursor agent crashes mid-implementation — the branch exists, the claim entry is stale, and nothing progresses
- A P1 WO waiting for human review has been waiting for days — no escalation

---

## What to Build

### 1. Add `last_seen` to dispatch entries

Every time an agent makes any API call to the orchestrator (validate, step update, heartbeat), update `last_seen` on the dispatch entry:

```python
# In any /api/wos/{wo_id}/* handler that indicates agent activity:
if wo_id in _dispatch_state:
    _dispatch_state[wo_id]["last_seen"] = _utcnow()
    _save_dispatch()
```

Also add a dedicated heartbeat endpoint that agents can call periodically (every 5 minutes) to signal they are still active:

```
POST /api/wos/{wo_id}/heartbeat
```

### 2. Add timeout thresholds per priority

```python
STUCK_THRESHOLDS = {
    "P0": timedelta(hours=4),    # P0 must move fast
    "P1": timedelta(hours=12),
    "P2": timedelta(hours=24),
    "P3": timedelta(hours=48),
}

REVIEW_WAIT_THRESHOLDS = {
    "P0": timedelta(hours=8),    # P0 waiting for human review
    "P1": timedelta(hours=48),
    "P2": timedelta(hours=72),
}
```

### 3. Detect stuck WOs in the poll loop

In the main orchestrator poll loop, after computing dispatch state:

```python
now = datetime.now(UTC)
for wo_id, entry in _dispatch_state.items():
    if entry.get("status") != "claimed":
        continue
    wo_num = int(wo_id.replace("WO-", ""))
    spec = primary_specs.get(wo_num, {})
    priority = spec.get("priority", "P2")
    last_seen = entry.get("last_seen") or entry.get("claimed_at")
    if not last_seen:
        continue
    last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    threshold = STUCK_THRESHOLDS.get(priority, timedelta(hours=24))
    if now - last_seen_dt > threshold:
        entry["stuck"] = True
        entry["stuck_since"] = last_seen
        _dispatch_state[wo_id] = entry
        print(f"[orchestrator] ⚠️ WO-{wo_num} STUCK — no activity for {now - last_seen_dt}")
        # Post Slack alert (if configured)
        await _post_stuck_alert(wo_id, priority, now - last_seen_dt)
```

### 4. Auto-hold after stuck threshold × 2

If a WO has been stuck for twice the threshold with no activity, auto-hold it (add to `_held_wos`) so no new agents pick it up, and alert for human review:

```python
if now - last_seen_dt > threshold * 2:
    _held_wos.add(wo_id)
    await _post_slack(f"⛔ WO-{wo_num} auto-held after {now - last_seen_dt} with no activity. Human must review and un-hold.")
```

### 5. Show stuck indicator on status site

Add a `⚠️ Stuck` badge on status site cards where `entry["stuck"] == True`. Include time since last activity. Show a distinct color (amber) vs the normal in-progress color (blue).

### 6. Add P1 review-wait escalation

For P1 WOs where `step == "PR merged — awaiting human review"` and the wait exceeds `REVIEW_WAIT_THRESHOLDS["P1"]`, post a Slack escalation message tagging the reviewer.

---

## Acceptance Criteria

- [ ] `last_seen` is updated on every agent API call and heartbeat
- [ ] `POST /api/wos/{wo_id}/heartbeat` endpoint exists and updates `last_seen`
- [ ] Stuck WOs are detected in the poll loop based on `last_seen` age vs priority thresholds
- [ ] Stuck WOs produce a log line and (if Slack configured) a Slack alert
- [ ] WOs stuck for 2× threshold are auto-held and alerted
- [ ] Status site shows `⚠️ Stuck` badge with time-since-activity on affected WOs
- [ ] P1 WOs waiting for review beyond threshold trigger escalation alert
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] `docs/TECHNICAL_ARCHITECTURE.md` — add stuck detection section; document timeout thresholds table; heartbeat endpoint
