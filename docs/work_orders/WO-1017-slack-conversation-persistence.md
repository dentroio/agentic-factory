# WO-1017 — Slack Conversation Persistence

**Status:** ✅ Done
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1015

---

## Problem

The Slack bot's conversation history (`_history`) and active thread registry
(`_active_threads`) are held in memory. Every container rebuild or restart
wipes them. Users lose context mid-conversation and the bot stops responding
to existing threads after a deploy.

---

## What to Build

### Persist `_history` and `_active_threads` to disk

On every write to `_history` or `_active_threads`, flush to a JSON file on
the `/data` volume (already mounted in the orchestrator container):

```
/data/slack_state.json
{
  "history": {"C1234567": [{"role": "user", "content": "..."}]},
  "active_threads": ["1234567890.123456", "1234567890.234567"]
}
```

Load on startup in `start_slack_bot()`.

### Implementation in `slack_bot.py`

- `_save_state()`: writes `_history` + `_active_threads` to `/data/slack_state.json`
  — called after every history update and every `_active_threads.add()`
- `_load_state()`: reads the file on startup, populates both globals
- Cap the file at 100 threads and 50 turns per thread to bound disk usage

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | Conversation history survives orchestrator container restart |
| 2 | Active threads survive restart — bot responds to existing threads |
| 3 | State file written to `/data/slack_state.json` |
| 4 | File capped at 100 threads / 50 turns per thread |
| 5 | Graceful on missing/corrupt file (start fresh, log warning) |
