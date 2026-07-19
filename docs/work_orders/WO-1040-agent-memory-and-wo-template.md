# WO-1040 — Agent Memory and WO Template Completeness

**Created:** 2026-07-19
**Priority:** P2
**Effort:** L
**Services:** agent-runner, orchestrator
**Depends on:** —

---

## Background

Every agent starts cold. It has no knowledge of what previous agents learned, what gotchas exist in the codebase, what recently shipped (so it doesn't duplicate it), or what the current environment state looks like. The WO spec + CLARION_PATTERNS section in `prompt_builder.py` is static — it was written once and never updated from actual agent runs.

Two observed consequences:
1. WO-1031's spec said `CLARION_MIGRATIONS_DONE` was stored in Vault. It wasn't. The agent spent time investigating something that was wrong in the spec.
2. Agents repeatedly hit the same "conflict magnet" files (adapter.py, main.py, App.tsx) and the same merge conflict pattern — because no lesson was ever recorded and injected into the next agent's context.

This WO builds a lightweight persistent memory system for agents and a richer WO template that captures what agents actually need to know.

---

## Part 1: Agent Memory System

### Memory store

A JSON file at `services/agent-runner/memory/factory_memory.json`. Structure:

```json
{
  "lessons": [
    {
      "id": "lesson-001",
      "added_at": "2026-07-18T00:00:00Z",
      "source_wo": "WO-1031",
      "category": "gotcha",
      "applies_to": ["data-service", "migrations"],
      "content": "CLARION_MIGRATIONS_DONE is set in the Dockerfile CMD, not in Vault. Do not look for it in Vault."
    },
    {
      "id": "lesson-002",
      "added_at": "2026-07-18T00:00:00Z",
      "source_wo": "WO-408",
      "category": "conflict_magnet",
      "applies_to": ["data-service"],
      "content": "services/data-service/main.py — every WO adds a router. Use router_registry.py instead of appending to main.py directly after WO-408 merges."
    }
  ],
  "environment": {
    "last_updated": "2026-07-18T00:00:00Z",
    "connected_connectors": ["ise", "pxgrid"],
    "healthy_services": ["data-service", "connector-service", "frontend"],
    "recent_migrations": ["add_schema_meta_table", "add_ot_flow_validation_results"],
    "recent_routes": ["/api/v1/ot/validation", "/api/v1/cmdb/writeback"]
  },
  "completed_wos": [
    {"wo": "WO-407", "completed_at": "2026-07-19T...", "summary": "adapter.py now auto-discovers migrations from migrations/ directory"}
  ]
}
```

### Memory injection in prompt_builder.py

`build_prompt()` gains a `memory: dict` parameter. A new `format_memory_context(memory, wo_spec)` function:

1. Selects lessons whose `applies_to` intersects with the WO's `services` field
2. Includes environment state (recent migrations, recent routes, connected connectors)
3. Lists the last 5 completed WOs so the agent knows what was recently shipped

Injected as a `## Factory Memory` section in the prompt, between the WO spec and CLARION_PATTERNS:

```
## Factory Memory

### Lessons learned (relevant to this WO's services)
- CLARION_MIGRATIONS_DONE is set in the Dockerfile CMD, not Vault [from WO-1031]
- services/data-service/main.py is a conflict magnet — use router_registry.py [from WO-408]

### Environment state (as of 2026-07-18)
- Connected connectors: ise, pxgrid (NOT: palo_alto, cisco_sase, zscaler)
- Healthy services: data-service, connector-service, frontend
- Recently added DB tables: _schema_meta, ot_flow_validation_results
- Recently registered routes: /api/v1/ot/validation, /api/v1/cmdb/writeback

### Recently completed WOs
- WO-407: adapter.py now auto-discovers migrations — no longer need to register manually
- WO-408: router_registry.py added — register new routes there, not in main.py
```

### Memory update after WO completion

In `runner.py`, after a WO completes successfully, call `update_memory_after_completion(wo_id, wo_spec, thread_msgs)`. This function:
1. Extracts the agent's thread summary
2. Uses the `ask()` backend method to distill 1-3 lessons from the run
3. Appends them to `factory_memory.json`
4. Updates `completed_wos` list

### Memory update on rejection

After a CI failure or reviewer rejection, call `update_memory_after_failure(wo_id, failure_reason)` to add a lesson with category `failure_pattern`.

### Memory refresh for environment state

Add a `refresh_environment_state()` coroutine that runs every 30 minutes in the runner:
- Calls `GET http://localhost:8000/api/connectors` → updates `connected_connectors`
- Calls `GET http://localhost:8000/health` → updates `healthy_services`
- Reads `_migration_history` table → updates `recent_migrations`

---

## Part 2: WO Template Completeness

### Update the canonical WO template

Create `docs/work_orders/TEMPLATE.md` — the single reference for what a complete WO spec must contain:

```markdown
# WO-NNN — Title

**Created:** YYYY-MM-DD
**Priority:** P1 | P2 | P3
**Effort:** XS | S | M | L | XL
**Services:** frontend | data-service | connector-service | docs | none
**Depends on:** WO-NNN (or —)

## Background
Why this exists. What pain it solves. What went wrong without it.

## What to Build
Concrete implementation spec. Pseudo-code for key logic. File names.
No ambiguity — the agent should not have to make significant design decisions.

## Requirements
```yaml
requires:
  connectors: []        # list connector types needed (leave empty if none)
  services: []          # list services that must be healthy
```
```

## Acceptance Criteria
- [ ] Each item is independently verifiable by the agent or CI
- [ ] At least 3 items
- [ ] No item requires a human to eyeball subjectively ("looks good")

## Files
List of files to create or modify. No surprises for the agent.

## Domain Notes
Gotchas specific to the services this WO touches. Agent reads this before starting.
Known conflict risks. Recently changed dependencies. Patterns to copy from.
```

### Add Domain Notes to existing WO specs

Backfill `## Domain Notes` into the 5 most recently active WO specs (WO-407, 408, 409, 1035, 1036) with the relevant lessons from factory_memory.json.

### Update CLARION_PATTERNS to reference living docs

`prompt_builder.py`'s `CLARION_PATTERNS` constant references static patterns. After WO-407/408 merge, some of these patterns change. Replace the hardcoded constant with a file read:

```python
PATTERNS_FILE = Path(__file__).parent / "clarion_patterns.md"
CLARION_PATTERNS = PATTERNS_FILE.read_text() if PATTERNS_FILE.exists() else _FALLBACK_PATTERNS
```

Create `services/agent-runner/clarion_patterns.md` as the living document. Agents (via post-completion memory update) can propose additions, which a human reviews before merging.

---

## Acceptance Criteria

- [ ] `services/agent-runner/memory/factory_memory.json` created with initial lessons from this session
- [ ] `build_prompt()` injects memory context relevant to the WO's services
- [ ] Agent prompt includes environment state: connected connectors, healthy services, recent migrations, recent routes
- [ ] After WO completion, `factory_memory.json` is updated with distilled lessons
- [ ] After CI failure, a failure_pattern lesson is added
- [ ] `docs/work_orders/TEMPLATE.md` exists with complete required sections
- [ ] `services/agent-runner/clarion_patterns.md` replaces hardcoded CLARION_PATTERNS constant
- [ ] Initial factory memory populated with lessons from this session:
  - CLARION_MIGRATIONS_DONE location
  - Conflict magnet files and their post-407/408 replacements
  - WO-391 environment gap (no Palo Alto / SASE connectors)
  - Rebase not merge in pr_watch.sh
- [ ] `make smoke-test` passes

## Files

- `services/agent-runner/prompt_builder.py` — memory injection, file-based CLARION_PATTERNS
- `services/agent-runner/runner.py` — post-completion and post-failure memory updates, environment refresh
- `services/agent-runner/memory/factory_memory.json` — new file, initial lessons
- `services/agent-runner/clarion_patterns.md` — new file, living patterns doc
- `docs/work_orders/TEMPLATE.md` — new file, canonical WO template
