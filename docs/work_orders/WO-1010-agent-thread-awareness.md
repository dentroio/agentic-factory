# WO-1010 — Agent Thread Awareness: Mid-Work Conversation

**Status:** ✅ Complete
**Priority:** P1
**Effort:** M (1 day)
**Services:** agent-runner
**Depends on:** WO-1009, WO-365

---

## Problem

WO-1009 built the thread infrastructure and human-facing UI. But the agent runner didn't read the thread — it fired a prompt, worked until done, then called `/api/validate`. Human messages posted mid-task were invisible to the agent.

---

## What Was Built

### `thread_monitor.py` — new module in `services/agent-runner/`

`ThreadMonitor` class:
- `poll()` — returns new human messages since the last call (incremental via `since` ID)
- `post(content, msg_type, metadata)` — thin wrapper around `orchestrator_client.post_thread_message`
- `_is_question(content)` — heuristic: ends with `?` or starts with why/what/how/explain/...

### `runner.py` — concurrent monitoring during agent execution

Two new async tasks launched alongside the main agent subprocess:

```
main agent run
  │
  ├── _checkin_loop (90 s heartbeats)
  └── _thread_monitor_loop (polls every 15 s after 30 s startup delay)
       │
       ├── Q&A message → asyncio.create_task(_handle_qa) — non-blocking
       └── Guidance message → backend.inject(content) — queued for next invocation
```

**`_thread_monitor_loop(wo_id, monitor, backend)`**:
- Waits 30 s before first poll (gives agent time to start)
- Every 15 s: polls thread, processes new human messages
- Questions: spawns `_handle_qa` as a concurrent task (does not interrupt main work)
- Directives: calls `backend.inject(content)` and posts an acknowledgement

**`_handle_qa(wo_id, question, monitor, backend)`**:
- Calls `backend.ask(prompt)` — for Claude: spawns a separate `claude --print -p` invocation
- Posts answer to thread as `[Q: {question}]\n\n{answer}` — non-blocking, fires and forgets

**Monitoring during approval wait**:
- `_poll_approval(wo_id, monitor)` also polls the thread every 15 s
- Q&A questions answered via `_handle_qa` while waiting for the human to approve/reject
- Keeps agent responsive to human questions even after work is submitted

**Agent posts on submission**:
- "Implementation submitted for review. Monitoring thread for questions while waiting..."

### Backend injection behaviour

| Backend | `inject()` behaviour |
|---------|---------------------|
| Claude CLI | Queued in `_pending_messages`; incorporated in next re-invocation |
| Cursor CLI | Queued in `_context_messages` |
| Codex CLI | Queued in `_context_messages` |

For the current one-shot CLI backends, guidance messages are acknowledged in the thread and will be incorporated if the agent is re-run. True real-time injection would require streaming/interactive mode (future work).

---

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Human question mid-task → answered in thread within 30 s | ✅ `_handle_qa` task |
| 2 | Q&A non-blocking — main agent task continues | ✅ `create_task` |
| 3 | Guidance/directive → acknowledged in thread | ✅ `backend.inject` + ack |
| 4 | Monitoring continues during approval wait | ✅ monitor param in `_poll_approval` |
| 5 | Agent posts progress message on review submission | ✅ |

---

## Execution

- **Branch:** `wo/369-agent-thread-awareness` (agentic-factory)
- **Risk tier:** P1 — agent-runner changes only; orchestrator and status-site unchanged
- **Rebuild:** agent-runner
