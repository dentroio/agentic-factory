# WO-NNN — Title

**Created:** YYYY-MM-DD
**Priority:** P1 | P2 | P3
**Effort:** XS | S | M | L | XL
**Services:** frontend | data-service | connector-service | correlation-service | docs | none
**Depends on:** WO-NNN (or —)

---

## Background

Why this exists. What pain it solves. What went wrong without it.
Reference the specific incident, failure mode, or user need that drives this work.

## What to Build

Concrete implementation spec. Pseudo-code for key logic. Exact file names and function signatures.
No ambiguity — the agent should not need to make significant design decisions.

## Requirements

```yaml
requires:
  connectors: []       # list connector types needed; leave empty if none
                       # example: [{type: "palo_alto", min_count: 1}]
  services: []         # list Clarion services that must be healthy before starting
                       # example: ["data-service", "connector-service"]
```

## Domain Notes

Gotchas specific to the services this WO touches. Agent reads this before starting.
- Known conflict risks (conflict-magnet files)
- Recently changed dependencies
- Patterns to copy from (with file paths)
- What NOT to do (and why)

## Acceptance Criteria

- [ ] Each item is independently verifiable by the agent or CI
- [ ] At least 3 items
- [ ] No item requires a human to eyeball subjectively ("looks good")
- [ ] Each item maps to a concrete check (curl, CI step, grep, etc.)

## Files

Exhaustive list of files to create or modify. No surprises for the agent.

| Action | File | Purpose |
|--------|------|---------|
| Create | `path/to/new_file.py` | What it does |
| Modify | `path/to/existing.py` | What changes |
