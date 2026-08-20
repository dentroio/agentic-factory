---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO execution instructions, agent process docs, and agent memory"
last_verified: 2026-08-20
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

## AGENT_PROCESS.md and AGENT_PROCESS_DETAIL.md

`AGENT_PROCESS.md` is the single source of truth agents read before starting any implementation task — it is referenced directly from `CLAUDE.md`. It is deliberately split into two files so agents only pay the cost of reading what they need every time:

- **`AGENT_PROCESS.md`** — the "what to do" cheatsheet. Kept short (under 200 lines) and written entirely as imperative commands and tables, not prose: risk tiers, the numbered branch/PR workflow (Step 1 through Step 8), a container rebuild table (service → make target → verify command), critical code patterns, the "stop and ask user" rule, and emergency ops references. The five must-not-forget patterns (e.g. `db.commit()` after every write, migration registration, `require_role()`, double-rebuild for shared modules, claim-file-first-commit) live under a `## ⚠️ You must know these` header within the first 30 lines.
- **`AGENT_PROCESS_DETAIL.md`** — the "why" reference, read only when an agent needs the reasoning behind a rule (worktree mechanics, why certain modules live in two containers, why `--no-deps` is required on force-recreate, migration registration rationale, role guard rationale).

A **container danger zones** table in `AGENT_PROCESS.md` explicitly lists dangerous commands, their safe replacements, and what goes wrong if you don't use the replacement (e.g. `docker compose up -d --force-recreate <svc>` can wipe the migrations-done flag by recreating dependency containers; use `make build-svc-wt SVC=<svc>` from a worktree instead of the non-worktree-aware `make build-svc`).

When customizing the factory for your project, edit `AGENT_PROCESS.md` to reflect your own risk tiers, rebuild targets, and danger zones — keep it short and imperative. Move any lengthy justification into `AGENT_PROCESS_DETAIL.md` instead of letting it accumulate in the cheatsheet.

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
- **Ordering:** Use `PUT /api/queue/{wo}/position` (or the Plan UI drag-and-dr