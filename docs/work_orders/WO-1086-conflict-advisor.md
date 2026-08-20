# WO-1086 — Conflict advisor for dispatch order

**Created:** 2026-08-18
**Priority:** P1
**Effort:** M
**Services:** orchestrator, docs
**Depends on:** —
**Status:** 🟡 In Progress

---

## Background

Factory dispatch order is pin → phase → priority → effort. Conflict avoidance is only what the spec author wrote (`depends_on`, `files_likely_changed`) plus occupancy. The intelligence loop does not sequence WOs; it reacts after a PR is already merge-conflicted.

That left two holes:

1. Two WOs that share a service (e.g. both `frontend`) can dispatch together when `MAX_PARALLEL_WOS > 1`, against AGENT_PROCESS ("one agent per service").
2. Missing `depends_on` edges are never filled in. The factory already has an LLM in the intelligence loop and does not use it for queue hygiene.

This WO adds a **deterministic same-service skip** on `/api/next` and a **conflict-advisor pass** (same 10-minute intelligence job) that writes extra `depends_on` edges into `/data/conflict_advisor.json`. Dispatch stays rule-based. The advisor never replaces `/api/next`.

Do **not** auto-hold WOs. Do **not** rewrite spec files. Do **not** start the factory or unpause.

## What to Build

### 1. `conflict_advisor.py` (importable without apscheduler)

- Parse `**Services:**` (comma, pipe, or `and`). Ignore `none`, `docs`, `n/a`, `-`.
- For every pair of open primary-repo WOs: if services overlap or `files_likely_changed` overlap, the later WO (lower priority first, then higher WO number) gets an advisor edge `depends_on` the earlier one.
- Skip the edge if it would cycle, if it already exists (spec or advisor file), or if either WO is held.
- Optional LLM (Haiku): given at most 15 open WOs (id, title, priority, services, files, depends_on), return extra high-confidence edges only. Invalid JSON / no key → no LLM edges. Deterministic edges still apply.
- Persist `{ "WO-463": [418] }` in `/data/conflict_advisor.json`. Thread-message each new edge.

### 2. `/api/next`

- Union spec `depends_on` with advisor edges before `_dependency_satisfied`.
- Skip a candidate whose services overlap an in-flight (`claimed` / `in_progress`) WO. Docs/none do not count.

### 3. Intelligence job

After the existing pass, run the advisor. Append actions to `actions_taken` so the dashboard Intelligence panel shows them.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` `get_next` and `_intelligence_job`
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Occupancy/close-out guards on this branch stay; they are a separate hotfix in the same working tree
- Do not start the runner

## Acceptance Criteria

- [ ] Two open WOs with `**Services:** frontend` do not both dispatch while one is `in_progress`
- [ ] Advisor edge is stored in `/data/conflict_advisor.json`, not the spec file
- [ ] Cycle-creating edges are refused
- [ ] Missing Anthropic key still applies deterministic service/file edges
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/conflict_advisor.py` | Parse, propose edges, LLM |
| Modify | `services/orchestrator/orchestrator.py` | get_next + intelligence job |
| Create | `tests/unit/test_conflict_advisor.py` | Edges, cycles, services parse |
| Modify | `docs/wiki/Intelligence-Loop.md` | Document pass 5 |
| Create | `docs/work_orders/WO-1086-conflict-advisor.md` | This spec |

## Execution

- **Branch:** `wo/1086-conflict-advisor`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `feat(orchestrator): WO-1086 — conflict advisor and same-service dispatch skip`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** none
- **PM docs to update:** PROGRESS.md

### UI Verification

1. Open http://127.0.0.1:8099 — factory still paused
2. Intelligence panel still loads (last run / all clear or actions)
3. After a manual `POST /api/intelligence/run` (optional): actions may list advisor edges; `/api/next` still returns drain while paused
4. Confirm no errors in orchestrator logs for `conflict_advisor`
