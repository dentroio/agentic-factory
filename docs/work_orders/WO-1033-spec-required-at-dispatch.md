# WO-1033 — Spec Required at Dispatch: Validate WO Has Spec Before Agent Starts

**Created:** 2026-07-18
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1025

---

## Background

The factory currently dispatches WOs based on spec files in `docs/project_management/work_orders/`. A WO is dispatchable as soon as its spec file exists and its status is `Open`/`Ready`. The spec file IS the WO definition — it contains the what, why, and acceptance criteria.

However, two problems were observed:
1. **Empty worktrees**: WO-385 and WO-404 were dispatched and created worktrees with 0 unique commits. The agents started, found nothing actionable, and produced no output. This wasted dispatches and cluttered the workspace.
2. **Incomplete specs**: Some spec files are stubs (title + status only, no background or acceptance criteria). Agents dispatched to these can't make meaningful progress and waste time trying to infer what to do.

A dispatch gate that validates spec completeness before dispatching would catch both cases.

---

## What to Build

### 1. Define a minimum viable spec

A spec is dispatchable only if it contains all of the following sections:

```python
REQUIRED_SPEC_SECTIONS = [
    "## Background",         # or "## Problem"
    "## What to Build",      # or "## Solution" or "## Approach"
    "## Acceptance Criteria", # must have at least 3 items
]

MINIMUM_BODY_LENGTH = 300  # characters — catches empty or stub specs
```

### 2. Add spec validation to `_resolve_dependencies`

Before dispatching a WO, validate its spec:

```python
def _validate_spec(wo_num: int, spec: dict) -> list[str]:
    """Returns a list of validation error strings. Empty = valid."""
    errors = []
    raw = spec.get("_raw_body", "")  # full spec text loaded when parsing

    if len(raw) < MINIMUM_BODY_LENGTH:
        errors.append(f"Spec is too short ({len(raw)} chars) — likely a stub")

    for section in REQUIRED_SPEC_SECTIONS:
        if section.lower() not in raw.lower():
            errors.append(f"Missing section: {section}")

    # Acceptance criteria count
    ac_lines = [l for l in raw.splitlines() if l.strip().startswith("- [ ]")]
    if len(ac_lines) < 3:
        errors.append(f"Acceptance criteria has only {len(ac_lines)} items — need at least 3")

    return errors

# In _resolve_dependencies:
errors = _validate_spec(num, spec)
if errors:
    holding.append({
        "wo": num,
        "reason": "Spec incomplete: " + "; ".join(errors),
        "action": "complete the spec before dispatching"
    })
    continue
```

### 3. Show incomplete specs on status site

Status site should show a "Spec incomplete" badge on WOs that fail validation, with the error list displayed on hover/expand. This makes it easy for humans to see what needs to be filled in before a WO can run.

### 4. Add a spec lint command

```
make spec-lint WO=NNN
```

This command reads the spec file and runs the same validation checks, printing any errors. Useful for humans writing specs who want to verify before pushing.

---

## Acceptance Criteria

- [ ] WOs with stub specs (< 300 chars or missing required sections) are held with a clear message
- [ ] WOs with < 3 acceptance criteria items are held
- [ ] Status site shows "Spec incomplete" badge with error detail
- [ ] `make spec-lint WO=NNN` runs validation and prints results
- [ ] Existing complete specs pass validation without false positives (test against WO-1024 through WO-1032 as baseline)
- [ ] `make smoke-test` passes

## Documentation Required

- [ ] `docs/AGENT_PROCESS.md` — add spec completeness requirements to WO authoring section
- [ ] `docs/TECHNICAL_ARCHITECTURE.md` — document dispatch validation gate
