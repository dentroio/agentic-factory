# WO-1025 — WO Readiness Gate: Planned vs Ready

**Created:** 2026-07-18
**Priority:** P1
**Effort:** S
**Services:** orchestrator, status-site
**Depends on:** none

---

## Background

Every WO with `Status: 📋 Open` is treated as immediately dispatchable. There is no way to put work in the backlog without either leaving the spec file unwritten or manually holding the WO in the orchestrator UI.

In practice this caused the factory to spin up empty worktrees for WO-385 and WO-404 — genuinely open WOs that hadn't been scheduled or prioritized yet. The agent did nothing useful (no unique commits) but consumed a slot and cluttered the workspace.

The fix is a two-value open state: **Planned** (backlog, do not dispatch) and **Ready** (queued for dispatch). Only `Ready` WOs enter the dispatch queue.

---

## What to Build

### 1. Add `📋 Ready` as a distinct status value

Update `_is_done()` and the dispatch logic to distinguish `Planned` from `Ready`. A WO is dispatchable only when its status begins with `📋 Ready` or the equivalent text `ready`.

Spec files use one of:
- `**Status:** 📋 Planned` — written, scoped, but not yet scheduled. Factory ignores it.
- `**Status:** 📋 Ready` — approved for dispatch. Factory may pick it up.
- `**Status:** 📋 Open` — **legacy alias for Ready** (backwards compat — treat as Ready so existing specs don't break)

### 2. Update `_resolve_dependencies` to gate on readiness

```python
def _is_ready(status: str) -> bool:
    s = status.strip().lstrip("*").strip()
    sl = s.lower()
    return (
        sl.startswith(("ready", "open"))        # open = legacy alias
        or s.startswith("📋 Ready")
        or s.startswith("📋 Open")
    )

# In _resolve_dependencies loop:
for num, spec in sorted(specs.items(), ...):
    if _is_done(spec["status"]):
        continue
    if not _is_ready(spec["status"]):           # NEW — skip Planned/backlog
        holding.append({..., "reason": "Status is Planned — mark Ready to dispatch"})
        continue
    # ... existing dependency + dispatch logic
```

### 3. Update status site to show Planned distinctly

In the status site, `Planned` WOs should appear in a separate "Backlog" column or section, clearly distinct from the active/ready queue. They should not show a "dispatch" button.

### 4. Update WO spec template

The default status in the WO spec template (in `docs/AGENT_PROCESS.md` and any generator scripts) should default to `📋 Planned` for new specs and require a human to change it to `📋 Ready` before the factory will dispatch it.

---

## Acceptance Criteria

- [ ] WOs with `Status: 📋 Planned` do not appear in the dispatch queue
- [ ] WOs with `Status: 📋 Open` (legacy) continue to be dispatched (backwards compat)
- [ ] WOs with `Status: 📋 Ready` are dispatched normally
- [ ] Status site shows Planned WOs in a separate Backlog section
- [ ] New WO spec template defaults to `📋 Planned`
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] Update `docs/AGENT_PROCESS.md` — add Planned vs Ready distinction to WO lifecycle section
- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — dispatch readiness gate documented
