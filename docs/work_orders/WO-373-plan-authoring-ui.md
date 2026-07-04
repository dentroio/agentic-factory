# WO-373 — Plan Authoring UI: Create WOs, Phases, and Milestones from the Status Site

**Status:** ✅ Done
**Priority:** P2
**Effort:** M
**Services:** status-site, orchestrator
**Depends on:** WO-358 (plan store), WO-359 (orchestrator REST API)

---

## Problem

The PLAN.json that drives the WO queue and milestone tracking can only be updated by editing files in the clarion repository directly. There is no UI for creating new WOs, adding phases, or setting milestones. This forces every WO creation through a manual git workflow, slowing down backlog grooming and making it impossible for non-engineers to contribute new work orders.

---

## What to Build

### Status site routes (`services/status-site/main.py`)

- `GET /settings/plan` → `settings_plan.html` — Plan Authoring Hub
- `GET /settings/plan/wos/new` → `settings_plan_new_wo.html` — WO creation form
- `POST /api/plan/wos` (proxied to orchestrator) → calls `github_writer.py`

### `settings_plan.html`

- Two panels: **Open WOs** (list of current `status=open` WOs from PLAN.json, with priority and phase) and **Phases** (collapsible list with an "Add Phase" form) and **Milestones** (collapsible list with an "Add Milestone" form)
- Link from Settings landing page (active card replacing the "Milestones coming soon" placeholder)
- Emerald colour scheme to distinguish from other settings sections

### `settings_plan_new_wo.html`

Full WO creation form with:
- Auto-numbered WO (next available number computed from PLAN.json)
- Title
- Phase dropdown (populated from existing phases in PLAN.json)
- Priority select (P0/P1/P2/P3)
- Effort select (XS/S/M/L/XL)
- Services (comma-delimited text input)
- Depends on (comma-delimited WO numbers)
- Blocks milestones (multi-select)
- Problem statement (textarea)
- What to build (textarea)
- Acceptance criteria (dynamic list — JS `addCriterion()` / `removeCriterion()`)
- Notes (textarea)
- Submit button disables on click with "Opening PR…" text to prevent double-submit

### `services/orchestrator/github_writer.py`

Receives a POST body with the form data and:
1. Authenticates to GitHub via `GITHUB_TOKEN`
2. Creates a feature branch on the `GITHUB_REPO` configured for the orchestrator
3. Writes the WO markdown spec to `docs/factory/work_orders/WO-NNN-<slug>.md`
4. Updates `docs/factory/PLAN.json` to add the new WO entry with `status=open`
5. Opens a PR so the WO gets human review before entering the dispatch queue
6. Returns the PR URL in the response

### `settings.html` update

Replace the "Milestones coming soon" card with an active Plan Authoring card linking to `/settings/plan`.

---

## Acceptance Criteria

- [ ] `/settings/plan` renders without error and shows open WOs, phases, and milestones
- [ ] Clicking "New WO" opens `/settings/plan/wos/new`
- [ ] Submitting the form creates a PR in the configured GitHub repo containing the WO spec file and updated PLAN.json
- [ ] Auto-numbered WO is one higher than the current maximum in PLAN.json
- [ ] Submit button disables immediately on click (no double-submit)
- [ ] Settings page links to Plan Authoring (emerald card, not "coming soon")

---

## Shipped

Merged 2026-07-04. PRs: status-site #18, orchestrator changes inline.

`github_writer.py` uses the GitHub Contents API (not git CLI) — no local git clone required inside the container.
