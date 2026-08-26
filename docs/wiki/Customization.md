---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO templates, documentation enforcement, agent process docs, and agent memory"
last_verified: 2026-08-26
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
| `p99_latency_ms` | 99th percentile latency in milliseconds. Alert if above this value. |
| `unhealthy_services` | List of service names that must report healthy. Alert if any listed service reports unhealthy. |

## docs/work_orders/TEMPLATE.md — the WO spec template

`docs/work_orders/TEMPLATE.md` is the canonical reference for what a complete Work Order spec must contain. New WOs (written by a human or by the planning agent) should follow it so agents have everything they need without guessing:

- **Header** — `Created`, `Priority`, `Effort`, `Services`, `Depends on`, `Status`
- **Background** — why this exists, what pain it solves
- **What to Build** — a concrete implementation spec with no ambiguity; the agent should not have to make significant design decisions
- **Requirements** — a `requires:` YAML block listing needed connectors/services
- **Acceptance Criteria** — at least 3 items, each independently verifiable by the agent or CI (no "looks good" items)
- **Files** — every file to be created or modified, so there are no surprises for the agent
- **Domain Notes** — gotchas specific to the services touched, known conflict risks, recently changed dependencies, patterns to copy from

If you're adapting the factory to a new codebase, start new WOs from this template rather than from a blank page.

## Documentation enforcement

Documentation debt used to accumulate silently — code could merge without any corresponding doc update. The factory now enforces documentation completeness as part of the review chain:

- A WO spec can include a `## Documentation Required` checklist. When the WO is created, this checklist is parsed and stored as JSON (`docs_required`) on the queue record.
- The coding agent's prompt includes a **documentation mandate**: it is told explicitly which doc files must be updated, and is instructed not to request human validation until each item is checked off.
- A fifth reviewer role, **documentation**, runs after the security/architecture/correctness/performance reviewers on the PR diff. It checks whether each `docs_required` item is meaningfully addressed in the diff — not code quality, just completeness.
- Unfulfilled items come back as `HIGH` severity findings, which block the chain the same way other blocking findings do. If `docs_required` is empty, the documentation reviewer step is skipped entirely.

To use this, add a `## Documentation Required` section to your WO specs listing the specific files/sections that must change (e.g. README env var tables, architecture diagrams, in-app help copy).

## Agent process docs

Agents are told to read a process doc before starting any implementation task. That doc is split into two files so agents pay the token cost only for what they need:

- **`AGENT_PROCESS.md`** — the "what to do" cheatsheet. Short, imperative, no prose. Contains the ris