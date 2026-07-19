# WO-1039 — Pre-Flight Environment Validation Before Dispatch

**Created:** 2026-07-19
**Priority:** P2
**Effort:** M
**Services:** orchestrator
**Depends on:** WO-1036

---

## Background

WO-391 required Palo Alto NGFW and Cisco Secure Access connectors to validate its acceptance criteria. Neither connector was configured. The agent ran for 23 hours and could never pass. The spec had no way to declare this requirement, and the orchestrator had no way to detect it.

Pre-flight validation checks that the WO's declared environment requirements are satisfied before dispatch. If they're not, the WO is held with a clear reason rather than dispatched to an agent that cannot succeed.

## What to Build

### WO spec: `requires` field

Add an optional `requires` block to the WO spec frontmatter or a dedicated section:

```markdown
## Requirements

```yaml
requires:
  connectors:
    - type: palo_alto
      min_count: 1
    - type: cisco_sase
      min_count: 1
  services:
    - data-service
    - connector-service
  clarion_version: ">=2.0"
```
```

The orchestrator reads this block from the WO markdown (parse the YAML inside the `## Requirements` fenced block).

### Orchestrator: pre-flight check before dispatch

Before moving a WO to `pending_approval` or dispatching it, run `preflight_check(wo_spec)`:

```python
async def preflight_check(wo_spec: dict) -> list[str]:
    """Returns list of unmet requirements. Empty list = OK to dispatch."""
    failures = []
    requires = wo_spec.get("requires", {})

    # Check connectors
    for req in requires.get("connectors", []):
        ctype = req["connector_type"]
        min_count = req.get("min_count", 1)
        count = await query_clarion_api(f"/api/connectors?type={ctype}&status=connected")
        if count < min_count:
            failures.append(f"connector '{ctype}': need {min_count}, have {count} connected")

    # Check services (docker compose ps)
    for svc in requires.get("services", []):
        healthy = await check_service_health(svc)
        if not healthy:
            failures.append(f"service '{svc}' is not healthy")

    return failures
```

If `preflight_check` returns failures: move WO to `held`, set `hold_reason` to the failure list, post thread message and notification explaining why. The WO stays held until requirements are met.

### Auto-retry on requirement change

Add a `preflight_retry` sweep to the poll loop: for WOs held due to failed preflight, re-run `preflight_check` every 30 minutes. If requirements are now met, move back to queue automatically and post a notification.

### Clarion API proxy in orchestrator

The orchestrator needs to query Clarion to check connector status. Add a `CLARION_API_URL` env var (default: `http://localhost:8000`) and a lightweight `query_clarion_api(path)` helper that returns JSON. Used only for preflight checks — read-only, no writes.

## Acceptance Criteria

- [ ] WO with `requires.connectors: [{type: palo_alto, min_count: 1}]` is held if no Palo Alto connector is connected
- [ ] Hold reason is visible on the WO thread and in the held-WOs list
- [ ] Pre-flight re-check runs every 30 minutes for held-preflight WOs
- [ ] WO automatically re-queues when requirements are met
- [ ] Slack notification fires when WO is held for failed preflight
- [ ] Slack notification fires when held WO is re-queued after requirements met
- [ ] WOs with no `## Requirements` section bypass preflight and dispatch normally
- [ ] `CLARION_API_URL` env var configures the Clarion endpoint
- [ ] `make smoke-test` passes

## Files

- `services/orchestrator/orchestrator.py` — preflight_check(), auto-retry sweep, CLARION_API_URL
- `docs/work_orders/WO-NNN-*.md` (template) — document `## Requirements` section format
