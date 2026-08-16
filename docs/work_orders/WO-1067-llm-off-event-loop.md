# WO-1067 — LLM calls must not block the orchestrator event loop (AF-23)

**Created:** 2026-08-16
**Priority:** P1
**Effort:** S
**Services:** orchestrator, docs
**Depends on:** WO-1066
**Status:** 🟡 In Progress

---

## Background

AF-23: PM chat, plan draft, and intelligence use the **synchronous** Anthropic SDK on the orchestrator's asyncio loop. A long completion blocks heartbeat processing and feeds false stale reaps. `CLAIM_TIMEOUT_SECONDS` was widened to paper over this.

Do **not** start the factory or unpause.

## What to Build

1. `llm_client.messages_create` — `await asyncio.to_thread(client.messages.create, ...)`.
2. Replace the five inline `messages.create` calls in `orchestrator.py` and `intelligence.py`.
3. Unit tests. Runner `review_chain.py` is out of scope (AF-24).

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Conflict-magnet: `orchestrator.py` — only the two Anthropic call sites
- Rebuild orchestrator with `--no-deps` so Vault is not recreated
- Do not start the runner

## Acceptance Criteria

- [ ] Orchestrator and intelligence do not call `messages.create` on the event loop
- [ ] Factory stays paused after deploy
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/orchestrator/llm_client.py` | `to_thread` wrapper |
| Modify | `services/orchestrator/orchestrator.py` | Plan draft + PM chat |
| Modify | `services/orchestrator/intelligence.py` | CI/conflict LLM |
| Create | `tests/unit/test_llm_off_event_loop.py` | Guards |
| Modify | `docs/project_management/PROGRESS.md` | 1066 complete, 1067 in progress |

## Execution

- **Branch:** `wo/1067-llm-off-event-loop`
- **Risk tier:** P1 — human must approve and merge
- **PR title:** `fix(orchestrator): WO-1067 — run Anthropic SDK calls off the event loop`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1066
- **PM docs to update:** PROGRESS.md

### UI Verification

No UI. After deploy, confirm pause is still on and `/api/next` still drains.
