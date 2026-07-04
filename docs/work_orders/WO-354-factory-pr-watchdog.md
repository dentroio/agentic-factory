# WO-354 — Factory PR Watchdog Service

**Status:** ✅ Complete (2026-07-01 — dentroio/agentic-factory merged)
**Priority:** P2
**Repo:** `dentroio/agentic-factory`
**Service:** `services/pr-watchdog/`
**Estimated effort:** 3–4 hours
**Depends on:** WO-349 (status site running — watchdog feeds alert data into it)

---

## Problem

The factory has no continuous watch on PR health. PRs can silently stall:
- CI fails and nobody notices for hours
- Auto-merge is queued but a flaky test keeps re-failing
- A branch has merge conflicts that prevent CI from even starting
- Dependabot PRs pile up waiting for a runner that's been busy too long
- A PR sits "In Review" for days with no action

Currently the only visibility is the status site's PR Queue panel, which shows a snapshot but doesn't alert, doesn't track age, and doesn't distinguish "CI just started" from "CI has been failing for 6 hours."

---

## Solution

A lightweight container service (`services/pr-watchdog/`) that runs on a configurable schedule (default: every 5 minutes), polls the GitHub API, evaluates each open PR against health rules, and writes a structured state file that the status site reads to display alerts.

The watchdog does **not** take autonomous action (no auto-close, no force-push, no commenting without explicit configuration). It is an observation and alerting service only, with optional comment posting as an opt-in feature.

---

## Architecture

```
┌─────────────────────────┐
│   pr-watchdog container  │
│                          │
│  scheduler (APScheduler) │
│    every POLL_INTERVAL   │
│         │                │
│  ┌──────▼──────┐         │
│  │ GitHub API   │         │
│  │ - open PRs   │         │
│  │ - CI checks  │         │
│  │ - branch     │         │
│  │   status     │         │
│  └──────┬──────┘         │
│         │                │
│  ┌──────▼──────┐         │
│  │  Rule engine │         │
│  │  (health     │         │
│  │   checks)    │         │
│  └──────┬──────┘         │
│         │                │
│  /data/watchdog.json ◄───┘
└─────────┬───────────────┘
          │  volume mount
┌─────────▼───────────────┐
│  status-site container   │
│  reads watchdog.json     │
│  renders alert panel     │
└─────────────────────────┘
```

The two containers communicate via a shared Docker volume (`factory-watchdog-data`). The status site reads `watchdog.json` at render time; no API call between containers.

---

## Health rules

| Rule ID | Condition | Severity | Label |
|---------|-----------|----------|-------|
| `ci-failing-long` | PR CI has been in `failure` state for > `CI_FAIL_THRESHOLD` minutes (default: 60) | `error` | CI failing too long |
| `ci-stuck` | PR CI has been `in_progress` or `queued` for > `CI_STUCK_THRESHOLD` minutes (default: 45) | `warning` | CI stuck |
| `merge-conflict` | PR has merge conflicts (mergeable_state = `dirty`) | `error` | Merge conflict |
| `auto-merge-blocked` | PR has auto-merge enabled but CI is failing | `warning` | Auto-merge blocked |
| `pr-stale` | PR has been open > `STALE_DAYS` days with no push or comment (default: 7) | `warning` | Stale |
| `pr-ancient` | PR has been open > `ANCIENT_DAYS` days (default: 14) | `error` | Needs attention |
| `ci-never-ran` | PR has 0 check runs more than 10 minutes after opening | `warning` | CI not triggered |
| `runners-all-busy` | All configured runners are reporting `busy: true` | `info` | Runners saturated |
| `queue-depth` | More than `QUEUE_WARN_DEPTH` jobs queued (default: 5) | `warning` | Queue backing up |

---

## `watchdog.json` schema

Written to `/data/watchdog.json` after each poll:

```json
{
  "generated_at": "2026-06-30T18:00:00Z",
  "poll_interval_seconds": 300,
  "summary": {
    "total_open_prs": 12,
    "healthy": 8,
    "warnings": 3,
    "errors": 1,
    "runners_online": 2,
    "runners_busy": 2,
    "queue_depth": 4
  },
  "alerts": [
    {
      "pr_number": 204,
      "pr_title": "Update pytest-asyncio requirement",
      "rule": "ci-failing-long",
      "severity": "error",
      "message": "CI has been failing for 127 minutes",
      "detail": "Unit Tests: exit code 1",
      "first_seen": "2026-06-30T15:53:00Z",
      "last_checked": "2026-06-30T18:00:00Z"
    }
  ],
  "pr_health": [
    {
      "number": 204,
      "title": "Update pytest-asyncio requirement",
      "age_hours": 48.2,
      "ci_state": "failure",
      "ci_duration_minutes": 127,
      "mergeable": true,
      "auto_merge": true,
      "rules_triggered": ["ci-failing-long", "auto-merge-blocked"]
    }
  ],
  "runner_health": {
    "runners": [
      {"name": "clarion-runner", "status": "online", "busy": true},
      {"name": "clarion-runner2", "status": "online", "busy": true}
    ],
    "queue_depth": 4
  }
}
```

---

## Implementation

### `services/pr-watchdog/requirements.txt`
```
httpx>=0.24.0
apscheduler>=3.10.0
python-dotenv>=1.0.0
```

### `services/pr-watchdog/Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data
COPY . .
CMD ["python", "watchdog.py"]
```

### `services/pr-watchdog/.env.example`
```
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-org/your-repo
POLL_INTERVAL=300
CI_FAIL_THRESHOLD=60
CI_STUCK_THRESHOLD=45
STALE_DAYS=7
ANCIENT_DAYS=14
QUEUE_WARN_DEPTH=5
# Optional: post a GitHub comment on first detection of error-severity issues
POST_COMMENTS=false
```

### `docker-compose.status.yml` additions
```yaml
services:
  pr-watchdog:
    build:
      context: ./services/pr-watchdog
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - GITHUB_REPO=${GITHUB_REPO}
      - POLL_INTERVAL=${POLL_INTERVAL:-300}
      - CI_FAIL_THRESHOLD=${CI_FAIL_THRESHOLD:-60}
      - CI_STUCK_THRESHOLD=${CI_STUCK_THRESHOLD:-45}
      - STALE_DAYS=${STALE_DAYS:-7}
      - ANCIENT_DAYS=${ANCIENT_DAYS:-14}
    volumes:
      - watchdog-data:/data
    restart: unless-stopped

  factory-status:
    # existing config...
    volumes:
      - watchdog-data:/data:ro   # read-only mount

volumes:
  watchdog-data:
```

---

## Status site integration

The status site reads `/data/watchdog.json` at render time and passes alert data to templates. If the file doesn't exist or is older than `POLL_INTERVAL * 2` seconds, it renders a "watchdog offline" notice instead of crashing.

Implementation in `main.py`:
```python
import json
from pathlib import Path

WATCHDOG_PATH = Path("/data/watchdog.json")

def _load_watchdog() -> dict | None:
    if not WATCHDOG_PATH.exists():
        return None
    try:
        data = json.loads(WATCHDOG_PATH.read_text())
        age = (datetime.now(UTC) - datetime.fromisoformat(
            data["generated_at"].replace("Z", "+00:00")
        )).total_seconds()
        if age > int(os.getenv("POLL_INTERVAL", "300")) * 2:
            return None  # stale
        return data
    except Exception:
        return None
```

---

## Optional: GitHub comment posting

When `POST_COMMENTS=true`, the watchdog posts a single comment per PR on first detection of an `error`-severity rule, and updates it (not duplicates) on subsequent polls. This requires `pull_requests: write` scope on the token. Off by default.

---

## Acceptance criteria

- [ ] `services/pr-watchdog/` container builds and starts cleanly
- [ ] `watchdog.json` is written within `POLL_INTERVAL` seconds of startup
- [ ] Alert panel appears in status site when `watchdog.json` is present
- [ ] Status site renders gracefully when watchdog is offline (no crash, "watchdog offline" notice)
- [ ] All 9 health rules fire correctly against test data
- [ ] `docker compose -f docker-compose.status.yml up` starts both `factory-status` and `pr-watchdog`
- [ ] `POST_COMMENTS=false` default confirmed — no GitHub comments created during test

---

## Risk

**Low.** Read-only GitHub API calls only (unless `POST_COMMENTS=true`). Failure modes are isolated: if the watchdog crashes, the status site degrades gracefully. No write access to repos, no triggering of CI, no branch operations.
