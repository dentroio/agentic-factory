# Work Order spec format (generic)

A well-formed WO passes the **cold start test**: an agent with zero chat history can implement it without asking clarifying questions.

Copy this into the target repo (default path `docs/project_management/work_orders/`).

## Template

```markdown
# WO-NNN — Short descriptive title

**Status:** Open
**Priority:** P0 | P1 | P2 | P3
**Effort:** S | M | L | XL

## Problem
WHY. The symptom. File paths, routes, error messages. Not the fix.

## What to Build / What to Fix
Files, signatures, API contracts. Enough to implement.

## Out of scope
Tempting extras you are deliberately not doing.

## Acceptance Criteria
1. A command, URL, or visible UI result
2. Local CI gate passes

## Execution
- **Branch:** `wo/NNN-short-name`
- **Risk tier:** P0 | P1 | P2 | P3
- **PR title:** `type(scope): WO-NNN — description`
- **Pre-PR gate:** `make ci-local` (or your equivalent)
- **Depends on:** none | WO-NNN
- **User verification required:** Yes — [exact steps] / No
```

**First commit on the branch:** [claim file](CLAIM_SCHEMA.md).

## Risk tiers

| Tier | Examples | Human verify running product | Auto-merge |
|------|----------|------------------------------|------------|
| P0 | Auth, secrets | Always | No |
| P1 | Schema, API contracts | Always | No |
| P2 | Features, UI, most fixes | Yes, then CI | Yes after CI + review |
| P3 | Markdown only | No | Yes via PR |

## Synthetic examples (not from a private product)

### P2 — UI bug

**Problem:** Clicking a row in `src/ui/List.tsx` does not open the detail panel. The click handler fires (console) but state does not update. Likely an overlay with pointer-events.

**What to Fix:** Identify the absorbing element; click should call `setSelected(id)` and open the panel. Drag on empty canvas still pans.

**Out of scope:** Redesigning the list layout.

**Acceptance:** Click opens panel; drag still pans; tests pass.

### P1 — API shape

**Problem:** `GET /items` returns a bare array. Clients cannot page.

**What to Build:** Return `{ "data": [...], "meta": { "total": N } }`. Update tests.

**Acceptance:** Curl shows the new shape; existing empty list is `data: []`.

### P3 — Docs

**Problem:** README does not mention the local verify command.

**What to Build:** Add a “Verify” section with the exact command.

**Acceptance:** README includes the command; no application code changed.

## Anti-patterns

| Anti-pattern | Fix |
|--------------|-----|
| “The map is broken” | Symptom + path + likely cause |
| Solution in Problem | Problem = symptom; Build = chosen fix |
| “Works correctly” | A command or a URL |
| Missing Execution | Branch, PR title, risk tier |
