# WO-1002 — Factory Status Dashboard v2 (Audience-Aware, Enriched)

**Status:** ✅ Complete (2026-07-01 — dentroio/agentic-factory merged)
**Priority:** P2
**Repo:** `dentroio/agentic-factory`
**Service:** `services/status-site/` (enhancement to WO-349)
**Estimated effort:** 5–7 hours
**Depends on:** WO-349 (base status site), WO-1001 (PR watchdog — alert panel)

---

## Problem

The current status site (WO-349) is functional but sparse. It shows four panels of raw data with minimal structure. It doesn't distinguish between what a project manager needs (WO progress, velocity, blockers) and what a CI/CD engineer needs (runner state, queue depth, CI timing, flaky tests). Alerts from the PR watchdog (WO-1001) need a home. And the WO board kanban is text-only with no visual weight to indicate urgency, age, or ownership.

---

## Goals

1. **Everyone can read it at a glance** — a health score, an alert banner, and color coding communicate system state in seconds without reading anything
2. **Project managers get a PM view** — WOs by program, velocity, what's blocked and why
3. **CI/CD engineers get a CI view** — runner utilization, queue depth, per-check CI breakdown, flaky detection
4. **The base dashboard is enriched** — age badges, agent names, block reasons, auto-merge indicators all visible without clicking through

---

## New URL structure

| Route | Audience | Description |
|-------|----------|-------------|
| `/` | Everyone | Enhanced overview (health score, alerts, enriched 4 panels) |
| `/pm` | Project managers | WOs by program, velocity, blocked summary, completion forecast |
| `/ci` | CI/CD engineers | Runner state, queue, per-PR CI breakdown, flaky test log |
| `/wo/{number}` | Developers | Existing WO detail view (unchanged) |
| `/health` | Ops/monitoring | Existing JSON health endpoint (unchanged) |

Navigation tabs across all pages link to each view.

---

## Overview page (`/`) — enhancements

### Health score banner (top of page)
A single-line status bar with an overall health indicator:

```
● HEALTHY   2 agents active   14 PRs in flight   3 WOs completed this week   Runners: 1/2 busy
```
```
⚠ DEGRADED  CI failing on 3 PRs   1 runner offline   Queue depth: 7
```
```
✖ CRITICAL  Both runners offline   5 PRs blocked on CI failures
```

Color: green / amber / red. Derived from watchdog data + runner state.

### Alert panel (below header, only when alerts exist)
Rendered from `watchdog.json`. Each alert is one line with severity color, PR number link, rule label, and duration:

```
[ERROR]  #204 pytest-asyncio — CI failing for 127m         auto-merge blocked
[WARN]   #216 plotly.js — CI stuck (queued) for 52m
[WARN]   #228 WO-349 specs — PR open 3 days, no activity
```

Collapsible if > 5 alerts. Disappears entirely when no alerts.

### WO Board — enriched kanban

Each WO card gains:
- **Age badge** — `2d`, `5d`, `14d` with color ramp (green → amber → red past 7d)
- **Agent badge** — agent name from claim file, or `unassigned`
- **Step** — current step from claim file (e.g., `implementing-backend`)
- **Block reason** — if `Blocked`, show the reason from watchdog or claim file
- **PR link** — if there's an open PR, link directly to it

### Active Work — enriched branch panel

Add:
- **Duration** — how long the agent has been working (`started 2h 14m ago`)
- **Step progress** — current step label
- **Last push** — time since last git push to the branch
- **CI indicator** — inline pass/fail badge if a PR exists

### PR Queue — enriched PR table

Current columns: title, CI state, age, WO number.

Add:
- **CI breakdown** — one icon per check (✅ ❌ ⏳) instead of a single state label
- **Auto-merge** — indicator showing whether auto-merge is queued
- **Merge conflict** — warning badge if `mergeable_state = dirty`
- **Age color** — amber > 24h, red > 72h
- **Watchdog flags** — inline alert icons from watchdog rules

### CI Health — enriched panel

Add:
- **Runner utilization bar** — `[██████░░░░] 2/2 busy` with runner names
- **Queue depth** — `4 jobs queued`
- **Average CI time** — computed from last 20 runs
- **Pass rate trend** — 7-day rolling (not just current window)

---

## PM view (`/pm`)

Designed for a project manager who wants to understand progress across programs and identify what's blocking delivery.

### Program roll-up table

| Program | WOs Total | Done | In Progress | Blocked | Open | % Complete |
|---------|-----------|------|-------------|---------|------|------------|
| Launch Program (WO-286–298) | 13 | 8 | 2 | 1 | 2 | 62% |
| DIEP (WO-201–209) | 9 | 9 | 0 | 0 | 0 | 100% |
| ...

Derived by parsing WO spec `## Program` or `**Program:**` field. WOs without a program field are grouped under "Standalone."

### Blocked items table

| WO | Title | Blocked by | Duration |
|----|-------|-----------|----------|
| #204 | pytest-asyncio upgrade | CI failing 127m | 2h 7m |
| #228 | WO-349 specs | Waiting on CI | 14m |

### Velocity panel

```
WOs completed per week (last 8 weeks):
Week of Jun 16  ████████  8
Week of Jun 23  █████     5
Week of Jun 30  ██        2  ← in progress
```

ASCII bar chart. Computed from merged PR timestamps.

### Active agents

| Agent | WO | Step | Started | Duration |
|-------|-----|------|---------|----------|
| claude-code | WO-349 | done | 2h ago | 35m |
| claude-code | WO-1001 | planning | 8m ago | 8m |

---

## CI view (`/ci`)

Designed for a CI/CD engineer or DevOps person who needs to diagnose pipeline issues.

### Runner panel

```
clarion-runner   ● online   ● BUSY   currently: CI run #1017 (wo/352-...) — 4m 12s
clarion-runner2  ● online   ● BUSY   currently: CI run #1016 (wo/346-...) — 11m 3s
```

Live runner names, current job, duration. Refreshes with the page auto-refresh.

### Queue panel

```
Jobs waiting for a runner: 4

#1018  CI           wo/352-353-frontend-dep-upgrade-specs  queued 3m ago
#1019  AI Review    wo/352-353-frontend-dep-upgrade-specs  queued 3m ago
#1020  Merge Advisor  main                                  queued 2m ago
#1021  AI Applier     main                                  queued 1m ago
```

### PR CI breakdown table

Full table of all open PRs with one row per check:

| PR | Check | State | Duration | Attempts |
|----|-------|-------|----------|----------|
| #228 | Unit Tests | ✅ pass | 1m 36s | 1 |
| #228 | Frontend Build | ✅ pass | 42s | 1 |
| #228 | Lint | ✅ pass | 12s | 1 |
| #204 | Unit Tests | ❌ fail | 2m 1s | 3 |
| #204 | Frontend Build | ✅ pass | 38s | 1 |

**Flaky detection:** if a check has `attempts > 1` and eventually passed, flag it as `⚠ flaky`. Flaky checks are summarized at the top of the CI view.

### CI timing panel

```
Average CI time (last 20 runs): 3m 42s
Fastest: 1m 18s   Slowest: 8m 14s

By check:
  Unit Tests      ████████████  avg 1m 51s
  Frontend Build  ██████        avg 48s
  Lint            ███           avg 14s
  Migration Check ████          avg 22s
```

---

## Implementation approach

All enhancements live in `services/status-site/` in `dentroio/agentic-factory`:

- **`main.py`** — add `/pm` and `/ci` routes; extend `_load_*` functions with new fields; add `_load_watchdog()` for alert data; add `_load_runner_health()` from GitHub Actions API
- **`github_client.py`** — add `list_queued_runs()`, `get_runner_list()`, `get_pr_check_detail()` (per-check breakdown with attempt count)
- **`templates/dashboard.html`** — enrich all four panels; add health banner and alert panel
- **`templates/pm.html`** — new; program table, blocked table, velocity chart, agent list
- **`templates/ci.html`** — new; runner panel, queue, PR CI breakdown, timing panel
- **`templates/base.html`** — update nav to include PM and CI tab links

No new dependencies required beyond what WO-349 already installs (FastAPI, Jinja2, httpx).

---

## Design principles

- **No JavaScript required** — all rendering server-side, Tailwind CSS for styling, auto-refresh via `<meta http-equiv="refresh">`
- **Graceful degradation** — if watchdog data is missing, the alert panel hides; if GitHub API call fails, the panel shows "data unavailable" not a 500
- **Mobile readable** — single-column layout on narrow screens; tables collapse to card lists
- **Role nav is persistent** — PM / CI / Overview tabs visible on every page so users can bookmark their view

---

## Acceptance criteria

- [ ] `/` health banner correctly shows HEALTHY / DEGRADED / CRITICAL
- [ ] Alert panel renders watchdog alerts when `watchdog.json` present; hidden when not
- [ ] WO cards show age badge, agent name, step
- [ ] PR table shows per-check CI icons, auto-merge indicator, conflict badge
- [ ] `/pm` program table correctly groups WOs; velocity panel shows last 8 weeks
- [ ] `/pm` blocked table shows PRs flagged by watchdog
- [ ] `/ci` runner panel shows both runners with current job
- [ ] `/ci` queue panel shows queued CI jobs
- [ ] `/ci` flaky detection flags PRs with multi-attempt passes
- [ ] All pages auto-refresh at configured interval
- [ ] Pages render without JS enabled
- [ ] `make smoke-test` passes (no Clarion code changed)
