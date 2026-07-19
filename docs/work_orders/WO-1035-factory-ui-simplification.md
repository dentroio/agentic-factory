# WO-1035 — Factory UI Simplification

**Created:** 2026-07-19
**Priority:** P2
**Effort:** S
**Services:** status-site
**Depends on:** —

---

## Background

The Factory tab currently has four agent backend cards (Claude / Cursor / Codex / Gemini) that read from dispatch state. That state goes stale immediately when an agent dies, so the cards confidently show "Claude: working · WO-375" when Claude has been dead for an hour. The live feed filter buttons connect to these cards — clicking "Cursor" reconnects the SSE stream filtered to that agent, but if the agent isn't logging, the feed says "Connected — waiting for activity" and looks broken with no explanation.

The result: the factory tab is confusing rather than informative. Users can't tell if work is actually happening.

## What to Build

### Remove the agent backend cards

Delete the entire `{# Backend Stations #}` section (lines 17–82 of `factory.html`). Replace with a single status bar:

```
● Runner online  |  3 active  |  Cursor  |  ⏸ pause
```

One line. Shows: runner health dot, active WO count, which backend is configured (`PREFERRED_AGENT`), and the pause button. No per-backend cards. No stale working/ready states.

### Simplify the left column

Remove the standalone "Dispatch", "Claude API", and "Runner Online" glass-panels below the active jobs list (lines 141–158). Fold runner status and pause into the single status bar above.

### Fix the Live Feed

Remove the per-agent filter buttons (All / Claude / Cursor / Codex / Gemini) from the feed header. Replace with a single WO filter: a `<select>` dropdown populated from the active WO list. Selecting a WO filters the SSE stream to `?wo=WO-NNN` instead of `?agent=cursor`. This is more useful — you want to see what WO-407 is doing, not what "Cursor" is doing in the abstract.

The SSE endpoint `/api/runner/log/stream` already accepts `?agent=` — add `?wo=` filtering to it in `main.py` so the frontend can use it.

### Keep

- Active Jobs list (left 1/3) — unchanged
- Live Feed (right 2/3) — keep layout, fix filter
- Dependabot PR panel — unchanged
- API usage banner — unchanged

## Acceptance Criteria

- [ ] No agent backend cards on the Factory tab
- [ ] Single status bar shows runner health, active count, current backend, pause button
- [ ] Live feed filter is a WO dropdown, not per-agent buttons
- [ ] `/api/runner/log/stream?wo=WO-NNN` filters log lines to that WO
- [ ] Stale dispatch state no longer causes misleading "Claude: working" displays
- [ ] `make smoke-test` passes after rebuild

## Files

- `services/status-site/templates/factory.html` — remove agent cards, simplify left column, replace feed filters
- `services/status-site/main.py` — add `?wo=` filter to SSE stream endpoint
