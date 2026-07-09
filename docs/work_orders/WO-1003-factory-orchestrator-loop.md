# WO-1003 — Factory Orchestrator Loop

**Status:** ✅ Complete (2026-07-01 — dentroio/agentic-factory merged)
**Priority:** P2
**Repo:** `dentroio/agentic-factory`
**Service:** `services/orchestrator/`
**Estimated effort:** 4–6 hours
**Depends on:** WO-349 (status site), WO-1001 (PR watchdog)

---

## Concept

From the article "Loop Engineering: The next evolution in AI coding isn't a better prompt, it's a system that prompts itself" (TechSpot, Jun 29, 2026):

> "You should be designing loops that prompt your agents." — Peter Steinberger, OpenAI

> "Tell Codex to maintain your repos, wake up every 5 minutes and direct work to threads." — Steinberger

> "The model that wrote the code is way too nice grading its own homework." — Addy Osmani, Google Cloud

The Clarion AI Factory already has agents that work autonomously. What it lacks is a **coordinator** — a process that continuously observes the WO board, understands what is ready to work on, respects capacity and dependencies, and either advises the human or (in a later phase) dispatches agents directly.

---

## What the orchestrator does

The orchestrator is a container that wakes on a schedule (default: every 5 minutes), reads the state of the repository, and produces a **dispatch advisory** — a structured JSON file describing which WOs are ready, which are blocked, runner capacity, and a recommended next action for each ready WO.

**Phase 1 (this WO):** Advisory only. The orchestrator writes `orchestrator.json` which the status site reads. It posts a daily GitHub issue comment summarizing the board state. No agents are dispatched automatically.

**Phase 2 (future WO):** The orchestrator can trigger Claude Code sessions via the Claude API or a webhook, implementing the full "wake → assign → parallelize" loop described in the article.

---

## Core loop

```
Every POLL_INTERVAL seconds:

1. Read WO board from GitHub (all WO spec files on main)
2. Read open branches (wo/* pattern) → which WOs are in progress
3. Read open PRs → which WOs are in review
4. Read runner state → how many runners are available
5. Read watchdog.json → which PRs are blocked / healthy
6. Evaluate each WO:
   a. Is it Open (not claimed)?
   b. Are its dependencies met (all listed WOs Done)?
   c. Is there runner capacity?
   d. Is it within this agent's scope (priority, labels)?
7. Produce dispatch_queue: ordered list of ready WOs
8. Produce blocked_wos: WOs that can't start and why
9. Write orchestrator.json
10. If DAILY_SUMMARY_HOUR and current hour matches → post GitHub issue comment
```

---

## WO dependency resolution

WO spec files may declare dependencies in their frontmatter or in a `**Depends on:**` line. The orchestrator parses this to build a dependency graph:

```
WO-351 depends on WO-349  →  WO-351 cannot be dispatched until WO-349 is Done
WO-1002 depends on WO-1001  →  WO-1002 cannot be dispatched until WO-1001 is Done
```

If a WO has no `Depends on:` field, it is treated as independent and can be dispatched any time it is Open.

Circular dependency detection: if A→B→A, flag both as `blocked:circular-dependency` and alert.

---

## `orchestrator.json` schema

```json
{
  "generated_at": "2026-06-30T18:05:00Z",
  "poll_interval_seconds": 300,
  "runner_capacity": {
    "total": 2,
    "busy": 2,
    "available": 0
  },
  "board_summary": {
    "open": 12,
    "in_progress": 2,
    "in_review": 6,
    "blocked": 1,
    "done_this_week": 3
  },
  "dispatch_queue": [
    {
      "wo": 354,
      "title": "Factory PR Watchdog Service",
      "priority": "P2",
      "dependencies_met": true,
      "recommended_action": "start",
      "reason": "Open, no dependencies, runner available",
      "estimated_effort": "3-4 hours"
    }
  ],
  "holding_queue": [
    {
      "wo": 355,
      "title": "Factory Status Dashboard v2",
      "dependencies_met": false,
      "blocked_by": [354],
      "reason": "Waiting on WO-1001 (not yet Done)"
    }
  ],
  "active_work": [
    {
      "wo": 352,
      "branch": "wo/352-frontend-eslint-10",
      "agent": "claude-code",
      "step": "implementing",
      "started_at": "2026-06-30T16:00:00Z",
      "duration_minutes": 125,
      "pr_number": null,
      "ci_state": null
    }
  ],
  "recommendations": [
    "WO-1001 is ready to start — no dependencies, P2 priority",
    "Both runners currently busy — wait before dispatching new work",
    "WO-204 (pytest-asyncio) CI has been failing 127m — needs human review"
  ]
}
```

---

## Daily summary GitHub comment

When `DAILY_SUMMARY_HOUR` is set (e.g., `9` for 9am UTC), the orchestrator posts or updates a comment on a designated GitHub issue (configured via `SUMMARY_ISSUE_NUMBER`). Format:

```
## Factory Daily Summary — Mon Jun 30, 2026

**Board:** 12 Open · 2 In Progress · 6 In Review · 1 Blocked

**Ready to start:**
- WO-1001 (P2): Factory PR Watchdog Service
- WO-1003 (P2): Factory Orchestrator Loop

**In Progress:**
- WO-352 (P2): Frontend ESLint 10 upgrade — claude-code, implementing (2h 5m)

**Blocked:**
- WO-1002 depends on WO-1001 (not yet complete)

**CI Health:** 6 PRs healthy · 1 failing (127m) · 2 runners busy

**Velocity:** 3 WOs done this week
```

The orchestrator uses `issues: write` scope to post/update this comment. It searches for an existing comment by the bot before posting to avoid duplicates.

---

## Implementation

### `services/orchestrator/requirements.txt`
```
httpx>=0.24.0
apscheduler>=3.10.0
python-dotenv>=1.0.0
```

### `services/orchestrator/Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data
COPY . .
CMD ["python", "orchestrator.py"]
```

### `services/orchestrator/.env.example`
```
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-org/your-repo
POLL_INTERVAL=300
DAILY_SUMMARY_HOUR=9        # UTC hour to post daily summary (leave unset to disable)
SUMMARY_ISSUE_NUMBER=       # GitHub issue number to post summaries to (leave unset to disable)
MAX_PARALLEL_WOS=2          # Maximum WOs to have in-progress at once (advisory)
WO_PATH=docs/project_management/work_orders
RUNS_PATH=docs/factory/runs
```

### `docker-compose.status.yml` additions
```yaml
  orchestrator:
    build:
      context: ./services/orchestrator
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - GITHUB_REPO=${GITHUB_REPO}
      - POLL_INTERVAL=${POLL_INTERVAL:-300}
      - DAILY_SUMMARY_HOUR=${DAILY_SUMMARY_HOUR:-}
      - SUMMARY_ISSUE_NUMBER=${SUMMARY_ISSUE_NUMBER:-}
      - MAX_PARALLEL_WOS=${MAX_PARALLEL_WOS:-2}
      - WO_PATH=${WO_PATH:-docs/project_management/work_orders}
      - RUNS_PATH=${RUNS_PATH:-docs/factory/runs}
    volumes:
      - watchdog-data:/data      # reads watchdog.json
      - orchestrator-data:/out   # writes orchestrator.json
    restart: unless-stopped

  factory-status:
    volumes:
      - watchdog-data:/data/watchdog:ro
      - orchestrator-data:/data/orchestrator:ro

volumes:
  watchdog-data:
  orchestrator-data:
```

---

## Status site integration (WO-1002 prerequisite)

The orchestrator's output feeds two new panels in the status site (implemented in WO-1002):

**Dispatch Queue panel** (visible on `/` and `/pm`):
- Shows `dispatch_queue` items in priority order: WO number, title, P-level, "ready" badge
- Shows `holding_queue` items with their blocking dependency

**Recommendations panel** (visible on `/pm`):
- Plain-text list from `orchestrator.json` → `recommendations`
- Marked with timestamp so PMs know when the last advisory ran

---

## Shared GitHub client

The orchestrator can share `github_client.py` from the status site service. Either import it as a shared module (Python path manipulation) or copy it into `services/orchestrator/` and keep them in sync. A future WO may extract it to a shared `lib/` package.

---

## Acceptance criteria

- [ ] `orchestrator.json` is written within `POLL_INTERVAL` seconds of startup
- [ ] Dependency resolution correctly blocks WO-1002 when WO-1001 is not Done
- [ ] `dispatch_queue` only contains WOs whose dependencies are all met
- [ ] `board_summary` counts match WO spec statuses
- [ ] Daily summary posts to configured issue number on schedule (when configured)
- [ ] Orchestrator does not post duplicate comments (updates existing comment)
- [ ] Status site renders dispatch queue and recommendations when `orchestrator.json` present
- [ ] Graceful degradation: status site works normally when orchestrator is offline
- [ ] Circular dependency detected and flagged (not infinite loop)
- [ ] `MAX_PARALLEL_WOS` respected in dispatch_queue (no more than N items recommended simultaneously)

---

## Risk

**Low–Medium.** The orchestrator is advisory only in Phase 1 — no writes to branches, no triggering of agents. The only write operation is posting a GitHub issue comment (opt-in via config). The risk is in the dependency parser: if WO spec files are inconsistently formatted, the parser may incorrectly block or unblock WOs. Validate against all existing WO specs during implementation.

**Phase 2 note:** When agent dispatch is added, risk increases to Medium-High. That phase requires careful safeguards: runner capacity enforcement, duplicate dispatch prevention, and a kill switch. Scope that as a separate WO.
