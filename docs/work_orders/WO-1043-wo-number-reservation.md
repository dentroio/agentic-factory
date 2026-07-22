# WO-1043 — WO Number Reservation API

**Created:** 2026-07-22
**Priority:** P1
**Effort:** S
**Services:** orchestrator, status-site
**Depends on:** —
**Status:** Open

---

## Background

WO number allocation is a scan: `github_writer.py:next_wo_number()` globs `docs/work_orders/WO-*.md`, takes `max + 1`, and returns it. There is no reservation step. Two concurrent callers (a human in the status-site UI and a factory agent running `make wo-start`) racing within the same second will get the same number.

Observed: WO-410 was both the user's work order and a factory-dispatched WO on July 22, 2026. The collision caused the reconciler to misidentify PRs, triggering the incident described in WO-1042.

The orchestrator tracks `next_wo_num` internally but this is a field in `DraftRequest` populated by a per-request scan — not atomic, not reserved.

Additionally, the intelligence loop creates synthetic WO IDs (`WO-CONF-{pr_num}`, `WO-CI-{pr_num}`) that are not real WO numbers. These cannot be dispatched, claimed, heartbeated, or completed through the normal flow, and they create phantom board entries that can never reach "done."

## What to Build

### 1. Reservation endpoint in orchestrator

```
POST /api/wos/reserve
Body:  { "title": "short description", "reserved_by": "claude-code" }
Response: { "wo_id": "WO-416", "number": 416, "reserved_at": "2026-07-22T..." }
```

Implementation:
- `_reserved: dict[int, dict]` — number → `{reserved_by, reserved_at, title}` — persisted to `DATA_DIR/reserved_wos.json`
- `_next_wo_number()` — `max(known_wos | set(_reserved)) + 1` where `known_wos` is scanned from the local repo mount
- Reserved numbers not claimed within 1h are released (TTL cleanup on each orchestrator poll)
- On claim (`POST /api/wos/{wo_id}/claim`): consume the reservation

```
GET /api/wos/reserved   → list of currently reserved numbers with metadata
```

### 2. Wire `make wo-start` to call the reservation API

In `scripts/wo_start.sh` (both factory and Clarion repos), if `ORCHESTRATOR_URL` is set, call `POST /api/wos/reserve` to get the number:

```bash
if [ -n "${ORCHESTRATOR_URL:-}" ] && [ -z "${NNN:-}" ]; then
    RESP=$(curl -sf -X POST "$ORCHESTRATOR_URL/api/wos/reserve" \
        -H "Content-Type: application/json" \
        -d "{\"title\": \"$SLUG\", \"reserved_by\": \"$(whoami)\"}")
    NNN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['number'])")
    echo "Reserved WO-$NNN"
fi
```

Falls back to scan-based if orchestrator is unreachable (with a warning printed).

### 3. Fix intelligence loop synthetic WO IDs

Replace `WO-CONF-{pr_num}` and `WO-CI-{pr_num}` with real reserved numbers:

```python
# In intelligence.py
async with httpx.AsyncClient() as orch:
    r = await orch.post(f"{ORCHESTRATOR_URL}/api/wos/reserve",
                        json={"title": f"conflict: pr-{pr_num}", "reserved_by": "intelligence-loop"},
                        headers=_orch_headers())
    wo_id = f"WO-{r.json()['number']}"
```

`ORCHESTRATOR_URL` is already available to the intelligence module (passed from the orchestrator).

### 4. Status-site WO creation uses reservation API

Update `main.py:api_next_wo_number()` and the WO draft/create flow to call `POST /api/wos/reserve` instead of computing a scan. The reserved number is held until the WO is committed to disk or 1h elapses.

## Acceptance Criteria

- [ ] Two simultaneous `POST /api/wos/reserve` calls return different numbers (tested with `asyncio.gather`)
- [ ] Reserved numbers persist across orchestrator restart
- [ ] Unreserved numbers expire after 1h; `GET /api/wos/reserved` shows only active reservations
- [ ] `make wo-start` without `NNN=` uses API when `ORCHESTRATOR_URL` is set
- [ ] Intelligence loop conflict and CI WOs use real WO numbers, not `WO-CONF-NNN`
- [ ] Status-site WO creation calls reserve endpoint
- [ ] Scan fallback still works when orchestrator is unreachable

## Files

- `services/orchestrator/orchestrator.py` — `POST /api/wos/reserve`, `GET /api/wos/reserved`, reservation state
- `services/orchestrator/intelligence.py` — use reserve API
- `services/status-site/main.py` — use reserve API
- `scripts/wo_start.sh` — optional auto-reserve (factory + Clarion)
- `services/orchestrator/tests/test_reservation.py` — new
