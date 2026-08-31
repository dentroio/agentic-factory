---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO templates, documentation enforcement, agent process docs, and agent memory"
last_verified: 2026-08-30
covers_wos:
  - WO-1014
  - WO-1021
  - WO-1023
  - WO-1032
  - WO-1040
doc_owner: factory-team
---

# Customization

The factory **engine** ships with defaults. Adapt **your product** with files in that repo; do not edit this engine’s live workflows to match an app.

- Product process: [docs/adopters/PROCESS.md](../adopters/PROCESS.md)
- Product WO shape: [docs/adopters/WO_SPEC_FORMAT.md](../adopters/WO_SPEC_FORMAT.md)
- Paste-in Actions: [templates/github/](../../templates/github/)
- First-time split: [Adopting](Adopting)

`scripts/review_context.txt` in **this** repo is for reviews that run **here**. If AI review runs on the product, put product invariants in the product (or a copied `review_context.txt` next to that workflow).

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

If you're adding WOs to a **product** repo, start from [docs/adopters/WO_SPEC_FORMAT.md](../adopters/WO_SPEC_FORMAT.md) (or the samples in [agentic-factory-template](https://github.com/dentroio/agentic-factory-template)). `docs/work_orders/TEMPLATE.md` in **this** engine is for factory-internal WOs.

## Documentation enforcement

Documentation debt used to accumulate silently — code could merge without any corresponding doc update. The factory now enforces documentation completeness as part of the review chain:

- A WO spec can include a `## Documentation Required` checklist. When the WO is created, this checklist is parsed and stored as JSON (`docs_required`) on the queue record.
- The coding agent's prompt includes a **documentation mandate**: it is told explicitly which doc files must be updated, and is instructed not to request human validation until each item is checked off.
- A fifth reviewer role, **documentation**, runs after the security/architecture/correctness/performance reviewers on the PR diff. It checks whether each `docs_required` item is meaningfully addressed in the diff — not code quality, just completeness.
- Unfulfilled items come back as `HIGH` severity findings, which block the chain the same way other blocking findings do. If `docs_required` is empty, the documentation reviewer step is skipped entirely.

To use this, add a `## Documentation Required` section to your WO specs listing the specific files/sections that must change (e.g. README env var tables, architecture diagrams, in-app help copy).

## Agent process docs

**Product repos:** copy [docs/adopters/PROCESS.md](../adopters/PROCESS.md) to `AGENT_PROCESS.md`. Keep front doors (`CLAUDE.md`, `AGENTS.md`, Cursor rules) pointing at that file. Do not copy this engine’s Docker rebuild table or service names into a product.

**This engine:** agents are told to read root `AGENT_PROCESS.md` before implementing factory WOs. That file is split so agents pay tokens only for what they need:

- **`AGENT_PROCESS.md`** — the "what to do" cheatsheet for **this engine**. Short, imperative. Must-not-forget: claim file first, never `git add -A`, human checkpoint on P0–P2, `make ci-local` before a PR. Also: risk tiers, numbered branch/PR steps, how to rebuild **factory** Docker services, danger zones for compose recreate.
- **`AGENT_PROCESS_DETAIL.md`** — the "why" file, if present. Product repos should use [docs/adopters/PROCESS.md](../adopters/PROCESS.md) instead of copying engine make targets.

`CLAUDE.md` in this engine tells agents to read `AGENT_PROCESS.md` before factory implementation work. Product front doors should point at that product’s `PROCESS.md`.

## Agent memory

Agents used to start every task cold, with no knowledge of what previous agents learned, what "conflict magnet" files exist in the codebase, or what the current environment actually looks like. The factory now maintains a lightweight persistent memory store that's injected into every agent's prompt.

### Memory store

A JSON file at `services/agent-runner/memory/factory_memory.json` holds three things:

- **`lessons`** — an array of `{id, added_at, source_wo, category, applies_to, content}` records. `category` is typically `gotcha`, `conflict_magnet`, or `failure_pattern`. `applies_to` lists the services a lesson is relevant to.
- **`environment`** — current environment state: `connected_connectors`, `healthy_services`, `recent_migrations`, `recent_routes`, and when it was last updated.
- **`completed_wos`** — a short history of recently completed WOs with a one-line summary of what they changed.

### How it's used

`build_prompt()` accepts a `memory` dict and injects a `## Factory Memory` section between the WO spec and the code-pattern reference, containing:

- Lessons whose `applies_to` intersects with the current WO's `services` field (so agents only see what's relevant)
- Current environment state (connected connectors, healthy services, recent migrations, recent routes) — so agents don't waste time investigating things that were true in the past but aren't now
- The last 5 completed WOs, so the agent doesn't duplicate work that already shipped

### How it stays current

- After a WO completes successfully, the runner distills 1–3 lessons from the agent's thread and appends them to `factory_memory.json`, along with an entry in `completed_wos`.
- After a CI failure or reviewer rejection, a `failure_pattern` lesson is recorded the same way.
- A background refresh runs periodically to update `connected_connectors`, `healthy_services`, and `recent_migrations` from the live environment, so the memory doesn't drift from reality.

This means WO specs and prompts don't need to be manually kept in sync with every environment change — the memory store closes that gap automatically as WOs complete.