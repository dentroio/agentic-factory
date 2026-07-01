# Factory Status Site

A live dashboard for any project using the Agentic Engineering Factory pattern. Reads your GitHub repository via API and displays:

- **WO Board** — Kanban (Open / In Progress / In Review / Blocked / Done), with status overridden live from branch and PR state
- **Active Work** — Open `wo/*` branches, last push time, and agent name + step when a WO claim file is present
- **PR Queue** — All open PRs with CI pass/fail state, age, and WO number
- **CI Health** — Last 20 workflow runs, pass/fail trend, rolling pass rate

Auto-refreshes every 60 seconds via HTML meta tag. No JavaScript required.

## Quick start

```bash
# From the agentic-factory root
GITHUB_TOKEN=ghp_your_token GITHUB_REPO=your-org/your-repo \
  docker compose -f docker-compose.status.yml up --build

# Open http://localhost:8099
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes | — | PAT with `contents: read` and `pull_requests: read` |
| `GITHUB_REPO` | Yes | — | `owner/repo` e.g. `dentroio/clarion` |
| `SITE_TITLE` | No | `AI Factory Status` | Page title |
| `REFRESH_SECONDS` | No | `60` | Auto-refresh interval |
| `WO_PATH` | No | `docs/project_management/work_orders` | Path to WO spec files in the repo |
| `RUNS_PATH` | No | `docs/factory/runs` | Path to WO claim JSON files in the repo |

## WO claim files

For the Active Work panel to show agent name and current step, agents must write a claim file at the start of each WO branch:

**File:** `docs/factory/runs/WO-NNN.json` (configurable via `RUNS_PATH`)

```json
{
  "wo": 349,
  "title": "WO title",
  "agent": "claude-code",
  "agent_platform": "claude-code-cli",
  "status": "in_progress",
  "step": "implementing-backend",
  "started_at": "2026-06-30T14:22:00Z",
  "last_updated": "2026-06-30T14:35:00Z",
  "branch": "wo/349-short-name",
  "notes": ""
}
```

The dashboard degrades gracefully when claim files are absent — it shows branch metadata (last push time) instead.

## WO board status inference

The board overrides the static status in WO spec files with live GitHub state:

| Condition | Board column |
|-----------|-------------|
| No `wo/NNN-*` branch exists | As written in WO spec file |
| Branch exists, no PR open | 🔄 In Progress |
| PR open + CI pending | 👀 In Review (CI running) |
| PR open + CI passing | 👀 In Review (ready) |
| PR open + CI failing | 🔴 Blocked |
| PR merged | ✅ Done |
