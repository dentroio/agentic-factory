# WO-1030 — Claim File as Single Source of Truth for WO Status

**Created:** 2026-07-18
**Priority:** P1
**Effort:** M
**Services:** orchestrator
**Depends on:** WO-1024, WO-1026
**Status:** ✅ Done

---

## Background

Today the orchestrator checks WO status from two different places:

1. **Spec file** — `docs/project_management/work_orders/WO-NNN-slug.md`, field `**Status:** ...`
2. **Claim file** — `docs/factory/runs/WO-NNN.json`, field `"status": "..."`
3. **`_dispatch_state`** — in-memory/SQLite dict tracking which WOs were dispatched this session

These three can disagree. The orchestrator's `_resolve_dependencies()` reads the spec file status. `_is_done()` also reads the spec file. The claim file is written when an agent starts but the orchestrator doesn't read it when deciding to dispatch — only when checking if the WO was already started in-process.

This multi-source pattern created several bugs this week:
- 14 WOs had `status: in_progress` claim files but spec files still said `📋 Open` → orchestrator re-dispatched them
- Batch docs PR was needed to update 12+ spec files manually just to stop re-dispatch
- The claim file's `status` field was essentially decorative — nothing read it

The fix is to make the claim file the **single authoritative record** for dispatch status, with the spec file being human-readable documentation only (not parsed for status by the orchestrator).

---

## What to Build

### 1. Orchestrator reads claim file status, not spec file, for dispatch decisions

Change `_resolve_dependencies()` to check claim file status as the primary gate:

```python
def _load_claim(wo_num: int) -> dict | None:
    """Load the claim file for a WO, returning None if it doesn't exist."""
    claim_path = _target_repo_path / "docs" / "factory" / "runs" / f"WO-{wo_num}.json"
    if not claim_path.exists():
        return None
    try:
        return json.loads(claim_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

def _is_done_from_claim(wo_num: int) -> bool:
    claim = _load_claim(wo_num)
    if claim is None:
        return False  # no claim = not started = not done
    return claim.get("status") in ("done", "complete", "completed")

def _is_in_progress_from_claim(wo_num: int) -> bool:
    claim = _load_claim(wo_num)
    if claim is None:
        return False
    return claim.get("status") in ("in_progress", "claimed")
```

In `_resolve_dependencies()`, replace the spec-file-based `_is_done()` check with `_is_done_from_claim()` + fallback:

```python
# Check claim file first; fall back to spec file status for backwards compat
if _is_done_from_claim(num) or _is_done(spec.get("status", "")):
    done.append(num)
    continue
if _is_in_progress_from_claim(num):
    # Already claimed by an agent — skip unless stuck
    holding.append({..., "reason": "Active claim file exists"})
    continue
```

### 2. Validate claim file consistency at startup

At orchestrator startup, log any WOs where claim and spec disagree:

```python
def _audit_claim_spec_consistency():
    for wo_num, spec in _all_specs().items():
        claim = _load_claim(wo_num)
        spec_status = spec.get("status", "")
        if claim is None:
            continue
        claim_status = claim.get("status", "")
        spec_done = _is_done(spec_status)
        claim_done = claim_status in ("done", "complete", "completed")
        if spec_done != claim_done:
            print(f"[orchestrator] ⚠️ Claim/spec mismatch WO-{wo_num}: "
                  f"claim={claim_status!r} spec={spec_status!r}")
```

### 3. Add a reconcile endpoint for humans

```
POST /api/admin/reconcile-claims
```

This endpoint scans all claim files against specs and returns a list of mismatches. It also accepts a `?fix=true` query parameter that updates claim files to match spec status (claim wins when `done`, spec wins when `in_progress` but spec says `Done`).

### 4. Write claim file as first step of dispatch

When the orchestrator dispatches a WO to an agent, write the claim file immediately (before the agent starts), not after the agent claims it. This prevents the window where the agent starts before the claim file exists.

```python
async def _dispatch_wo(wo_num: int, spec: dict) -> None:
    # Write claim file immediately
    claim_path = _target_repo_path / "docs" / "factory" / "runs" / f"WO-{wo_num}.json"
    claim_data = {
        "wo": wo_num,
        "title": spec.get("title", ""),
        "agent": _agent_id(),
        "status": "claimed",
        "claimed_at": _utcnow(),
        "branch": f"wo/{wo_num}-{spec.get('slug', 'unknown')}",
    }
    claim_path.write_text(json.dumps(claim_data, indent=2))
    subprocess.run(["git", "add", str(claim_path)], cwd=_target_repo_path)
    subprocess.run(["git", "commit", "-m", f"factory: claim WO-{wo_num}"], cwd=_target_repo_path)
    subprocess.run(["git", "push", "origin", "main"], cwd=_target_repo_path)
    # Then dispatch to agent...
```

---

## Acceptance Criteria

- [ ] Orchestrator's dispatch gate reads claim file status as primary signal
- [ ] WOs with `status: in_progress` or `status: claimed` in claim file are not re-dispatched
- [ ] WOs with `status: done` in claim file are not re-dispatched, even if spec says `Open`
- [ ] Claim file is written by orchestrator before dispatching (not after agent claims)
- [ ] Startup audit logs any claim/spec mismatches
- [ ] `/api/admin/reconcile-claims` endpoint exists and returns mismatch list
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] `docs/TECHNICAL_ARCHITECTURE.md` — add claim file authority section; document the spec file as human-readable only
- [ ] `docs/AGENT_PROCESS.md` — note that claim file is authoritative; spec status is for humans
