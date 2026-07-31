---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO execution instructions, and agent memory"
last_verified: 2026-07-31
covers_wos:
  - WO-1014
  - WO-1021
  - WO-1023
  - WO-1032
  - WO-1040
doc_owner: factory-team
---

# Customization

The factory ships with sensible defaults and a set of project-agnostic AI review checks. This page covers the files you edit to adapt it to your specific stack and conventions.

## scripts/review_context.txt

This file is loaded into the Claude system prompt on every PR review. Use it to add checks that only make sense in the context of your project — invariants the AI could not discover by reading the diff alone.

Format: numbered list, one check per line. Lines starting with `#` are treated as comments.

```text
1. db.commit() after every db.execute() write — this project's DB adapter does NOT auto-commit.
   Flag any INSERT/UPDATE/DELETE not followed by db.commit().

2. Every new API route must include the require_role() dependency.
   Missing auth gates are a critical security issue.

3. New migration files must be registered in src/app/storage/adapter.py — no auto-discovery.
   Flag any new migration file not added to the registry.
```

Good checks are specific and falsifiable. "Check for security issues" is not a check — "Flag any use of `eval()` or `exec()` on user-supplied input" is. The AI applies your context on top of its built-in universal checks (hardcoded secrets, swallowed exceptions, SQL injection, missing test coverage).

Delete the file entirely if your project has no specific checks. The universal rules always apply.

## scripts/observability_thresholds.json

The `observability.yml` workflow polls `METRICS_ENDPOINT` every 15 minutes and compares the response against these thresholds. If any threshold is exceeded, it creates a GitHub issue and routes it into the WO workflow via the planning agent.

```json
{
  "error_rate_pct": 1.0,
  "p99_latency_ms": 2000,
  "unhealthy_services": ["database", "cache"]
}
```

| Field | What it checks |
|-------|---------------|
| `error_rate_pct` | Percentage of requests returning 5xx. Alert if above this value. |
| `p99_latency_ms` | 99th percentile response time in milliseconds. Alert if above this value. |
| `unhealthy_services` | Service names to check in the health endpoint's `services` map. Alert if any are not `"healthy"`. |

Set `METRICS_ENDPOINT` as a GitHub Actions variable (**Settings → Secrets and variables → Actions → Variables**) pointing to your application's health or metrics endpoint. If the variable is not set, the observability workflow skips silently.

## .github/workflows/ci.yml.template

The template ships with a `ci.yml.template` rather than a live `ci.yml`. This is intentional — CI is highly project-specific and a wrong default would fail immediately.

To activate CI:

```bash
cp .github/workflows/ci.yml.template .github/workflows/ci.yml
```

Then edit `ci.yml` to add your actual build, lint, and test steps. The template includes placeholder jobs named `Lint` and `Unit Tests` — rename them to match whatever you add. The job names you choose must match the required status checks in your branch ruleset (**Settings → Rules → Rulesets**).

The `ai-review.yml`, `ci-failure-notifier.yml`, and `ci-auto-fix.yml` workflows all refer to a workflow named `CI` — keep that as the `name:` field at the top of your `ci.yml`.

## WO Execution section

Every WO spec has an **Execution** section injected at the top of every agent prompt before the WO content. It describes project-specific rules the agent must follow — service names, make targets, safety gates.

Open any WO spec file at `docs/work_orders/WO-NNN-slug.md` and look at the Execution section to see the format. When you create WOs via the PM or the UI, the PM pre-fills this section based on your project context. You can also edit it directly after the spec is drafted.

Common things to put in the Execution section:
- Which services to rebuild after editing which files
- How to run the smoke test
- The commit and PR workflow (branch naming, merge strategy)
- Mandatory review steps the agent must complete before opening a PR

## WO template

A canonical WO template lives at `docs/work_orders/TEMPLATE.md`. Every complete WO spec must contain these sections (in order):

| Section | Purpose |
|---------|---------|
| `## Background` | Why the WO exists; what pain it solves |
| `## What to Build` | Concrete implementation spec; pseudo-code; file names |
| `## Requirements` | YAML block listing required connectors and services |
| `## Acceptance Criteria` | Independently verifiable checklist items (minimum 3) |
| `## Files` | Exhaustive list of files to create or modify |
| `## Domain Notes` | Gotchas, conflict risks, recently changed dependencies |

Acceptance criteria items must be independently verifiable — no item should require a human to eyeball subjectively.

When you create WOs via the Plan Authoring UI (see below), the form produces a spec that follows this template automatically.

## Plan Authoring UI

WOs, phases, and milestones can be created and managed from the status site at `/settings/plan` — no manual file editing required.

**Creating a WO:**
1. Go to `/settings/plan` and click **New WO**.
2. Fill in the form: title, phase, priority, effort, services, dependencies, problem statement, what to build, and acceptance criteria.
3. Submit. The orchestrator opens a PR in your configured GitHub repo containing the WO spec file. The WO enters the dispatch queue once the PR merges.

The WO number is assigned automatically (one above the current maximum). The submit button disables immediately on click to prevent double-submission.

**Phases and milestones** are managed from the same `/settings/plan` hub. Adding or editing them writes directly to the factory database — no PLAN.json file editing needed.

## Queue database

The WO queue, phases, and milestones are stored in the orchestrator's SQLite database (`factory.db`), not in PLAN.json. PLAN.json remains in the repo as a read-only human reference but is no longer written by the orchestrator.

Key behaviours:
- **Auto-cleanup:** When a WO's spec file is marked `✅` complete, it is removed from the queue automatically on the next orchestrator poll cycle — the queue stays current without manual cleanup.
- **Pinning:** Set `pin: 1` on a queue entry to prevent it from being reordered or auto-removed.
- **Ordering:** Use `PUT /api/queue/{wo}/position` (or the Plan UI drag-and-drop) to reorder the queue.

The queue CRUD endpoints (`GET/POST/DELETE /api/queue`, `PUT /api/queue/{wo}`, etc.) are documented in `docs/TECHNICAL_ARCHITECTURE.md`.

## Documentation requirements enforcement

When the PM drafts a WO spec that touches documented surfaces (API endpoints, env vars, architecture diagrams), it emits a `## Documentation Required` checklist in the spec. This checklist is enforced at review time:

- The orchestrator parses the `Documentation Required` section when the WO is queued and stores it in the `docs_required` column of the `queue` table.
- The coding agent's prompt includes a **Documentation Mandate** block listing the required doc updates. The agent may not call `POST /api/validate` until all items are addressed.
- A **documentation reviewer** runs after the four standard code reviewers (security, architecture, correctness, performance) for all P0/P1/P2 WOs. It checks the diff for meaningful updates to each file listed in `docs_required` and returns a `HIGH` finding for any item not addressed. A `HIGH` finding blocks human validation.

You do not need to configure this — it activates automatically whenever a WO spec contains a `## Documentation Required` section.

## Agent memory

Each agent run starts with context injected from a persistent memory store at `services/agent-runner/memory/factory_memory.json`. This prevents agents from repeating mistakes already seen in previous runs.

### What is injected

The memory is filtered to the WO's services and injected as a `## Factory Memory` block in the agent prompt, between the WO spec and CLARION_PATTERNS. It contains:

- **Lessons learned** — gotchas, conflict-magnet files, failure patterns recorded from previous WO runs
- **Environment state** — connected connectors, healthy services, recently added DB tables and routes (refreshed every 30 minutes)
- **Recently completed WOs** — the last 5 completed WOs so the agent knows what has already shipped

### How memory is updated

- **After a successful WO:** the runner distills 1–3 lessons from the agent's thread and appends them to `factory_memory.json`.
- **After a CI failure or reviewer rejection:** a `failure_pattern` lesson is added automatically.
- **Environment state** is refreshed every 30 minutes by polling the connectors and health endpoints and reading the migration history table.

### Editing memory manually

`factory_memory.json` is a plain JSON file. You can add, edit, or delete lessons directly. The structure:

```json
{
  "lessons": [
    {
      "id": "lesson-001",
      "added_at": "2026-07-18T00:00:00Z",
      "source_wo": "WO-1031",
      "category": "gotcha",
      "applies_to": ["data-service", "migrations"],
      "content": "CLARION_MIGRATIONS_DONE is set in the Dockerfile CMD, not in Vault."
    }
  ],
  "environment": {
    "last_updated": "2026-07-18T00:00:00Z",
    "connected_connectors": ["ise", "pxgrid"],
    "healthy_services": ["data-service", "connector-service", "frontend"],
    "recent_migrations": ["add_schema_meta_table"],
    "recent_routes": ["/api/v1/ot/validation"]
  },
  "completed_wos": [
    {"wo": "WO-407", "completed_at": "...", "summary": "adapter.py now auto-discovers migrations"}
  ]
}
```

Valid `category` values: `gotcha`, `conflict_magnet`, `failure_pattern`.

`applies_to` is matched against the WO's `Services` field — a lesson is only injected when at least one value overlaps.

## CLARION_PATTERNS (living document)

The agent-runner's built-in code patterns are loaded from `services/agent-runner/clarion_patterns.md` rather than a hardcoded constant. This file is the living reference for patterns agents must follow in your codebase.

To add a pattern:
1. Edit `services/agent-runner/clarion_patterns.md` directly (or let the post-completion memory update propose one).
2. Commit and push. The runner picks up the change on