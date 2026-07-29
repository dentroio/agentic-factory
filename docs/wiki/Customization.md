---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO execution instructions, and agent memory"
last_verified: 2026-07-29
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

The canonical WO spec template lives at `docs/work_orders/TEMPLATE.md`. Every complete WO spec must contain the following sections:

| Section | Purpose |
|---------|---------|
| `## Background` | Why this WO exists and what pain it solves |
| `## What to Build` | Concrete implementation spec with file names and pseudo-code; no ambiguity |
| `## Requirements` | YAML block listing required connectors and services |
| `## Acceptance Criteria` | Independently verifiable checklist items (minimum 3; no subjective items) |
| `## Files` | List of files to create or modify |
| `## Domain Notes` | Gotchas, conflict risks, recently changed dependencies for the services this WO touches |

When creating WOs via the Plan Authoring UI or the PM, the template is used automatically. For manually authored WOs, copy `TEMPLATE.md` as your starting point.

## WO queue

The WO queue is stored in the orchestrator's SQLite database (`factory.db`), not in `PLAN.json`. The `queue`, `phases`, and `milestones` tables are the source of truth for backlog ordering and milestone tracking. `PLAN.json` remains in the repository as a read-only reference snapshot but is no longer written by the orchestrator.

Key queue behaviours:
- When a WO spec file is marked ✅ Done, the orchestrator removes it from the `queue` table automatically on the next poll cycle.
- Queue order, priority, phase assignment, and pinning are all editable via the Plan Authoring UI or the queue CRUD endpoints.

See [TECHNICAL_ARCHITECTURE.md](../TECHNICAL_ARCHITECTURE.md) for the full DB schema and orchestrator endpoint reference.

## Plan Authoring UI

WOs, phases, and milestones can be created directly from the status site without editing files manually.

- Navigate to **Settings → Plan Authoring** (`/settings/plan`) to see the current open WO backlog, phases, and milestones.
- Click **New WO** to open the WO creation form. The form auto-numbers the WO, lets you assign a phase, priority, effort, services, dependencies, and acceptance criteria, and opens a PR for human review before the WO enters the dispatch queue.
- Phases and milestones can be added inline from the Plan Authoring hub.

WO specs are written to `docs/factory/work_orders/WO-NNN-<slug>.md` via the GitHub Contents API — no local git clone is required inside the container.

## Agent memory

Agents start with context about your project's current state injected into every prompt. This context is stored in `services/agent-runner/memory/factory_memory.json` and includes:

- **Lessons learned** — gotchas, failure patterns, and conflict warnings distilled from previous WO runs, tagged by service
- **Environment state** — connected connectors, healthy services, recently added DB tables, recently registered routes (refreshed every 30 minutes)
- **Recently completed WOs** — the last 5 completed WOs so agents know what was recently shipped and don't duplicate it

Only lessons whose `applies_to` services intersect with the current WO's services are injected, keeping the context focused.

**Memory is updated automatically:**
- After a WO completes successfully, the runner distills 1–3 lessons from the agent thread and appends them to `factory_memory.json`.
- After a CI failure or reviewer rejection, a `failure_pattern` lesson is added.

To add a lesson manually, edit `factory_memory.json` directly and follow the existing entry structure:

```json
{
  "id": "lesson-003",
  "added_at": "2026-07-29T00:00:00Z",
  "source_wo": "WO-1041",
  "category": "gotcha",
  "applies_to": ["data-service"],
  "content": "Describe the gotcha here."
}
```

Valid `category` values: `gotcha`, `conflict_magnet`, `failure_pattern`.

## CLARION_PATTERNS / agent patterns doc

The agent pattern rules (formerly a hardcoded constant in `prompt_builder.py`) are now loaded from `services/agent-runner/clarion_patterns.md` at runtime. This file is the living document for project-specific coding patterns injected into every agent prompt.

To update a pattern, edit `clarion_patterns.md` directly and commit. The change takes effect on the next agent dispatch — no rebuild required.

If `clarion_patterns.md` is missing, `prompt_builder.py` falls back to its built-in default patterns.

## Documentation enforcement

For P0/P1/P2 WOs, a documentation reviewer runs automatically as part of the review chain after the four standard reviewers (security, architecture, correctness, performance). It checks whether the diff includes updates to every file listed in the WO spec's `## Documentation Required` section.

- A missing documentation update produces a `HIGH` severity finding that blocks the chain — the coding agent must address it before human validation is requested.
- The documentation reviewer is skipped when a WO has no `Documentation Required` items.

The coding agent is also given a **Documentation Mandate** in its prompt listing the required doc files, so it knows to update them before calling `POST /api/validate`.

To ensure your WO specs trigger this enforcement, include a `## Documentation Required` section with specific file-level checklist items:

```markdown
## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — add new endpoint to the API table
- [ ] Update `docs/wiki/Configuration.md` — document the new environment variable
```

## Agent process documentation

Agent operating rules are split across two files in the project repository:

| File | Purpose |
|------|---------|
| `AGENT_PROCESS.md` | **What to do** — risk tiers, branch/PR workflow (numbered steps), container rebuild table, critical patterns, container danger zones. Agents read this before every task. Under 200 lines. |
| `AGENT_PROCESS_DETAIL.md` | **Why** — detailed explanations of each rule: worktree system, `db.commit()` rationale, `--no-deps` requirement, migration registration, role guard rationale. Optional reading. |

`CLAUDE.md` instructs agents: *"Read `AGENT_PROCESS.md` before starting any implementation task. If you need the reasoning behind a rule, see `AGENT_PROCESS_DETAIL.md`."*

If you add a new project-wide invariant that every agent must know, add it to `AGENT_PROCESS.md` in the `## ⚠️ You must know these` section near the top of the file.

## Agent backend selection

The default backend is set during `make agent-setup`. To change it after setup:

```bash
# Edit the prefs file directly
echo "PREFERRED_AGENT=cursor" >> ~/.config/factory-agent/prefs
```

Or run `make agent-setup` again and pick a different backend when prompted.

To dispatch a specific WO with a different backend than the default, tell the PM:

> "Start WO-123 with Gemini."

The PM sends a dispatch signal that overrides the default for that one WO.

See [Agent Backends](Agent-Backends) for a comparison of when to use each backend.

## Environment variables

Non-secret configuration is stored in `~/.config/factory-agent/prefs`. Secrets (GitHub token, API keys, ntfy topic, Slack webhook) are stored in the macOS Keychain under the service name `dentroio-factory` and read at runtime by `scripts/factory-env.sh`.

To add a new secret after initial setup:

```bash
security add-generic-password -s "dentroio-factory" -a "MY_NEW_KEY" -w "the-value"
```

To read a stored secret:

```bash
security find-generic-password -s "dentroio-factory" -a "MY_NEW_KEY" -w
```

Docker Compose reads secrets via the `factory-env.sh` script, which exports them as environment variables before `docker compose up`. You do not need a `.env` file.