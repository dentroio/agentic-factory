# WO-379 — PM Session Memory Across Conversations

**Status:** ✅ Done
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-376

---

## Problem

The PM has no memory of previous sessions. Every new Slack conversation or
browser chat starts cold — the PM doesn't know what WOs were recently started,
what decisions were made, or what the user prefers (e.g. "always use Cursor").
This makes every conversation feel like starting over.

---

## What to Build

### Persistent PM memory store

A structured JSON file at `/data/pm_memory.json` that accumulates across
sessions:

```json
{
  "preferences": {
    "preferred_backend": "cursor",
    "last_updated": "2026-07-07"
  },
  "recent_decisions": [
    {"date": "2026-07-07", "decision": "Run WO-185 before WO-186 — sequential dependency"},
    {"date": "2026-07-07", "decision": "Dependabot PRs: recreate when rebase_blocked"}
  ],
  "dispatched": [
    {"wo": "WO-185", "backend": "cursor", "date": "2026-07-07", "outcome": "merged"}
  ]
}
```

### Injection into PM system prompt

Load `pm_memory.json` at startup and inject a compact summary into every
PM chat context block:

```
PM memory:
- Preferred backend: cursor
- Recent: WO-185 dispatched 2026-07-07 (merged), WO-186 queued after
- Decisions: run syslog WOs sequentially; recreate blocked Dependabot PRs
```

### Memory update endpoint

`POST /api/pm/memory` — orchestrator writes a key/value to `pm_memory.json`.
PM chat calls this after a dispatch or significant decision (e.g. user confirms
a preference).

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | PM remembers preferred backend across sessions |
| 2 | PM recalls recently dispatched WOs and their outcomes |
| 3 | PM recalls recent decisions / recommendations it made |
| 4 | Memory injected into every PM chat context (≤10 lines) |
| 5 | Memory survives container restart (written to `/data` volume) |
| 6 | `POST /api/pm/memory` endpoint accepts `{key, value}` writes |
