# WO-000 — {{Short Title}}

**Status:** 🔵 Open / 🟡 In Progress / ✅ Complete / ❌ Cancelled
**Priority:** P0 / P1 / P2 / P3
**Assigned:** Human / Agent
**Target:** {{YYYY-MM-DD}}
**Depends on:** WO-XXX (if any)

---

## Problem

_One paragraph: what is broken, missing, or needed? Be specific about symptoms, not solutions._

## Goal

_One or two sentences: what does "done" look like from a user/operator perspective?_

## Scope

**In scope:**
- Item 1
- Item 2

**Out of scope:**
- Item 3 (explicitly excluded — why)

## Approach

_Technical approach. Reference files, data models, and APIs by name. If multiple approaches exist, state the chosen one and why._

## Acceptance Criteria

- [ ] Criterion 1 — verifiable, not vague
- [ ] Criterion 2
- [ ] All existing tests still pass
- [ ] `make ci-local` passes

## Verification Steps

```bash
# Commands an agent or human can run to confirm the WO is complete
# e.g.:
#   make ci-local
#   curl -s http://localhost:8000/api/health | jq .
#   pytest tests/unit/test_foo.py -v
```

---

## Execution

> This section is read by agents before starting implementation.

**Branch:** `wo/000-short-description`
**Risk tier:** P0/P1/P2/P3
**PR title:** `type(scope): WO-000 — Short Title`
**Auto-merge:** yes (P2 only) / no (P0/P1 — notify human)

**PM docs to update after merge:**
- `docs/project_management/PROGRESS.md` — mark WO-000 complete
- `docs/project_management/CAPABILITY_STATUS.md` — update affected capability row (if applicable)

**Files to touch (estimated):**
- `path/to/file.py` — describe the change
- `path/to/other.ts` — describe the change

**Key constraints:**
- List any invariants the agent must not violate (db patterns, auth gates, etc.)

### UI Verification

Steps a human can follow in the browser to confirm this WO is working — write these before implementation:

1. Open `{{APP_URL}}` — log in as `{{TEST_USER}}`
2. Navigate to `{{exact menu path}}`
3. `{{Specific action: click X, fill in Y, save}}`
4. Expected: `{{exact result — label text, status badge, row in table, etc.}}`
5. Confirm no errors in browser DevTools console

> Replace this entire subsection with `No UI changes — backend / API only.` if this WO has no frontend impact.

---

## Notes / Context

_Anything that doesn't fit above: links, incident reports, design decisions, trade-offs considered._
