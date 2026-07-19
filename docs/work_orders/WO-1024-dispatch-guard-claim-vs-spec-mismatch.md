# WO-1024 — Dispatch Guard: Claim File Wins Over Spec Status

**Created:** 2026-07-18
**Priority:** P1
**Effort:** S
**Status:** ✅ Done
**Services:** orchestrator
**Depends on:** none

---

## Background

The orchestrator's `_resolve_dependencies()` decides what to dispatch by iterating `specs` and reading `spec["status"]`. If the spec says `📋 Open`, the WO enters the dispatch queue — even if the claim file (SQLite `dispatch_state`) already has an entry with `status: complete` or `status: claimed`.

This caused WO-391 to be re-dispatched: the spec file status was still `📋 Open` (cleanup hadn't happened yet), and the claim entry from the original run was gone or stale. A fresh agent was given the WO and started working on it for hours before the human noticed.

The reconciliation loop (`merged_wo_prs`) already tries to back-fill dispatch entries for recently merged PRs, but:
1. The "recently merged" window only catches PRs from the past N days — older stale specs slip through.
2. Even when a claim entry exists with `status: complete`, `_resolve_dependencies` ignores it and re-reads `spec["status"]`.

The fix is simple: before adding a WO to the dispatch queue, check the in-memory `_dispatch_state`. If a `complete` or `claimed` entry exists, skip it regardless of what the spec says.

---

## What to Build

### 1. Make `_resolve_dependencies` respect existing dispatch entries

In `orchestrator.py`, `_resolve_dependencies(specs, done_wos)` currently receives `done_wos: set[int]` built from merged PRs. Extend it to also receive the current dispatch state and skip WOs that already have a non-open entry.

```python
def _resolve_dependencies(
    specs: dict[int, dict],
    done_wos: set[int],
    dispatch_state: dict[str, dict] | None = None,   # NEW
) -> tuple[list[dict], list[dict], list[str]]:
    claimed_wos: set[int] = set()
    if dispatch_state:
        for wo_id, entry in dispatch_state.items():
            if entry.get("status") in ("claimed", "complete", "rejected"):
                try:
                    claimed_wos.add(int(wo_id.replace("WO-", "")))
                except ValueError:
                    pass

    for num, spec in sorted(specs.items(), key=lambda x: (x[1]["priority"], x[0])):
        if _is_done(spec["status"]):
            continue
        if num in claimed_wos:          # NEW — already active or completed
            continue
        # ... rest of existing logic unchanged
```

Pass `_dispatch_state` when calling `_resolve_dependencies`:

```python
dispatch_queue, holding_queue, cycle_warnings = _resolve_dependencies(
    primary_specs, done_wos, dispatch_state=_dispatch_state   # add this
)
```

### 2. Extend the merged PR reconciliation lookback

`_fetch_recently_merged_wo_prs` currently uses a short lookback. Change it to 90 days so stale merged PRs are caught even when cleanup was deferred:

```python
since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
```

### 3. Add a guard log line

When a WO is skipped because of an existing dispatch entry, log it clearly so it's visible in orchestrator output:

```python
if num in claimed_wos:
    print(f"[dispatch] WO-{num} skipped — dispatch entry exists (status: {dispatch_state.get(f'WO-{num}', {}).get('status', '?')})")
    continue
```

---

## Acceptance Criteria

- [ ] A WO with `spec["status"] == "📋 Open"` is NOT dispatched if its dispatch entry has `status: complete`
- [ ] A WO with `spec["status"] == "📋 Open"` is NOT dispatched if its dispatch entry has `status: claimed`
- [ ] Merged PR reconciliation lookback extended to 90 days
- [ ] Skipped WOs produce a log line with their dispatch entry status
- [ ] `make smoke-test` passes after rebuild
- [ ] Existing unit tests pass; add a test for the new `claimed_wos` skip logic

## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — dispatch guard section: document claim-wins-over-spec precedence
