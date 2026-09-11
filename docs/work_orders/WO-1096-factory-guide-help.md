# WO-1096 — In-app factory guide + inline help refresh

**Services:** status-site (factory-status)
**Priority:** P2 (docs/UX — ships with CD PR track)

## Problem

Inline `?` help was stale (missing Get Started, Deploy & Harness, History, etc.). New operators land on Overview without a clear picture of what the factory is or how a WO flows.

## What to Build

1. Dismissible visual guide at the top of Overview (`/`) — roles, lifecycle SVG, architecture SVG, “where to click” links.
2. Standalone `/guide` page + nav **Guide** + Settings hub card.
3. Refresh `HELP` map in `base.html` for all major routes and settings subpages.
4. Update wiki Dashboard Guide + CAPABILITY_STATUS + BACKLOG.

## Out of scope

- Changing agent/orchestrator behavior
- Full marketing site outside the dashboard

## Acceptance Criteria

- [x] Overview shows guide; Hide restores via chip; `/guide` returns 200
- [x] `?` help covers `/settings/deploy-harness`, `/settings/get-started`, `/history`, `/guide`
- [x] Wiki Dashboard Guide documents Guide + Deploy & Harness

## Execution

- **Branch:** `wo/1094-factory-cd` (bundled with WO-1094/1095 PR #327)
- **Risk tier:** P2 UX/docs (parent PR remains P1 for CD)
- **PR title:** (same PR) feat(cd): WO-1094/1095/1096 — engine CD, Deploy & Harness, factory guide
- **PM docs:** BACKLOG.md, CAPABILITY_STATUS.md, Dashboard-Guide.md
