# WO-368 — WO Thread: Conversational Collaboration Layer

**Status:** ✅ Complete
**Priority:** P1
**Effort:** L (2–3 days spec; 1 session actual)
**Services:** orchestrator, factory-status, agent-runner
**Depends on:** WO-365

---

## Problem

Human-agent interaction was fragmented. When an agent completed a WO or needed guidance, the human had no single place to see what happened, ask questions, or provide feedback — they had to check GitHub PR comments, the IDE, and Slack separately.

---

## What Was Built

### `services/orchestrator/thread.py` — storage module

Per-WO thread files at `/data/threads/{wo_id}.json`. Message fields:

```json
{
  "id": "01720000000000001",
  "author": "claude-runner",
  "role": "agent",
  "type": "text",
  "content": "Starting implementation...",
  "image_url": "",
  "metadata": {},
  "timestamp": "2026-07-04T02:00:00Z"
}
```

Message types: `text` | `ci_result` | `security_finding` | `review` | `image`

Roles: `agent` | `human` | `reviewer` | `system`

Helper functions: `load_thread`, `save_thread`, `append_message`, `make_message`, `system_message`, `all_thread_summaries`.

### Orchestrator — 4 new endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/thread/{wo}/messages` | Append a message (agent or human) |
| `GET /api/thread/{wo}/messages?since=...` | Fetch all or incremental messages |
| `GET /api/thread/{wo}/stream` | SSE stream — 2 s poll, keepalive ticks |
| `GET /api/threads` | Summary of all threads `{wo_id: {count, last}}` |

### Auto system messages on all state transitions

| Event | Message posted |
|-------|---------------|
| `/api/claim` | "WO-N claimed by **agent** on `host`" |
| `/api/validate` (pass) | "Awaiting human review — ✅ CI · ✅ Security" |
| `/api/validate` + thread_summary | Agent's summary posted as `agent` message |
| Approve | "✅ Approved by **human**" |
| Reject | "✗ Rejected — {guidance}" |
| Complete | "✅ WO complete — merged and closed by **agent**" |

### Status site — thread proxy + UI

**New proxy endpoints** in `main.py`:
- `GET /api/thread/{wo}/messages` → proxies to orchestrator
- `POST /api/thread/{wo}/messages` → proxies human posts to orchestrator

**`wo_detail.html` — thread panel** added below spec sections:
- Server-side rendered initial messages (Jinja2)
- Colour-coded by role: system (grey), agent (cyan), human (indigo), reviewer (amber)
- `ci_result` type: green (pass) / red (fail) with monospace output
- `security_finding` type: amber with left border
- Compose area: textarea + Send button (Ctrl+Enter shortcut)
- JavaScript polls `GET /api/thread/{wo}/messages?since=...` every 3 s
- Auto-scrolls to bottom on new messages

### Agent runner — thread messages at key points

`orchestrator_client.post_thread_message(wo_id, content, msg_type, metadata)` added.

`runner.py` posts at:
1. "Starting implementation of WO-N: {title}"
2. "Running quality gate..." (before CI+security)
3. "❌ Quality gate failed: {failures}" (with CI output snippet) on gate failure
4. "✅ Quality gate passed — requesting human review" on gate pass

---

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Thread persists across container restarts | ✅ JSON file on volume |
| 2 | System messages auto-posted on all transitions | ✅ |
| 3 | Human can post via status site compose area | ✅ |
| 4 | Agent posts progress messages during run | ✅ |
| 5 | Thread visible on WO detail page | ✅ |
| 6 | Polling delivers new messages within 3 s | ✅ 3 s JS interval |
| 7 | SSE stream endpoint available for future use | ✅ |

---

## Execution

- **Branch:** `wo/368-wo-thread` (agentic-factory)
- **Risk tier:** P1 — new endpoints + UI additions (no existing behaviour changes)
- **Rebuild:** orchestrator + factory-status + agent-runner
