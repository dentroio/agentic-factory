# Dentro AI Factory — Capability Status

_Last updated: 2026-07-03_

A living registry of what the system can do, at what fidelity, and what's still open.

---

## How to read this doc

| Symbol | Meaning |
|--------|---------|
| ✅ | Production-ready — tested, deployed, verified |
| 🟡 | Partial — works but has known gaps listed |
| 🔵 | Planned — scoped, not yet built |
| ❌ | Removed / descoped |

---

## Dimension 1: Live Dashboard (factory-status, port 8099)

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| Overview tab — branch/PR/WO cards | ✅ | Dark glassmorphism design | WO-355 |
| PM View — velocity bar chart, active agents, program roll-up | ✅ | 8-week velocity history | WO-355 |
| Engineering tab — CI health, run history, pass rate | ✅ | | WO-355 |
| Plan tab — milestone cards, phase progress, priority queue | ✅ | Phase-filterable queue | WO-358 |
| WO detail page (`/wo/<n>`) | ✅ | Structured spec view | WO-355 |
| Velocity projection + milestone on-track/at-risk badges | ✅ | Avg of last 4 weeks | WO-360 |
| Dark / light mode toggle | ✅ | Persisted in localStorage | WO-355 |
| Auto-refresh (configurable interval) | ✅ | Default 60 s | WO-355 |
| Settings UI — multi-repo project management | ✅ | Named Docker volume backed | WO-357 |

## Dimension 2: PR Watchdog (pr-watchdog)

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| Stale PR detection (configurable age threshold) | ✅ | Default 7 days warn / 14 ancient | WO-354 |
| CI failure / stuck run alerts | ✅ | Threshold-based | WO-354 |
| Review-requested stale detection | ✅ | | WO-354 |
| Queue depth warning | ✅ | Configurable threshold | WO-354 |
| Blocked items panel in PM View | ✅ | Links to GitHub PRs | WO-354 |
| Auto-comment on blocked PRs | 🟡 | Disabled by default (`POST_COMMENTS=false`) | WO-354 |

## Dimension 3: Orchestrator + Agent Dispatch (orchestrator, port 8100)

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| PLAN.json ingestion + priority queue computation | ✅ | Reads from GitHub repo | WO-358 |
| Phase / milestone stats (`milestone_stats`, `phase_stats`) | ✅ | | WO-358 |
| Next WO selection (respects pins, status, dependencies) | ✅ | | WO-358 |
| REST API — `/api/next`, `/api/claim`, `/api/checkin`, `/api/validate` | ✅ | FastAPI + APScheduler | WO-359 |
| Agent claim / check-in / release lifecycle | ✅ | JSON state on `/data` volume | WO-359 |
| Human validation queue (`/api/validate`) | ✅ | | WO-359 |
| Daily summary posting to GitHub issue | 🟡 | Optional; needs `SUMMARY_ISSUE_NUMBER` env var | WO-356 |
| Multi-repo orchestration | 🔵 | Currently single-repo per instance | — |

## Dimension 4: CI/CD + Agent Infrastructure

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| GitHub Actions CI pipeline (lint, test, static check) | ✅ | Blocks merge on failure | — |
| AI code review (Claude) | ✅ | Advisory — never blocks merge | — |
| Secret detection (gitleaks) | ✅ | Blocks on detected secrets | — |
| Merge advisor (synthesized recommendation) | ✅ | ✅/⚠️/❌ in PR comments | — |
| Self-healing CI (auto-update behind-main branches) | ✅ | | — |
| `.agents/` entry point for Google Antigravity / Gemini | ✅ | Skills + workflows subdirs | — |
| Docker Compose single-command deploy | ✅ | `docker compose -f docker-compose.status.yml up -d` | — |

---

## Open Gaps

1. Multi-repo orchestration — single orchestrator instance can only track one `GITHUB_REPO`; the settings UI adds read-only dashboards but dispatch is still single-repo. Impact: medium.
2. Agent authentication — `/api/claim` is unauthenticated; any caller can claim a WO. Suitable for closed networks only. Impact: low for current use, high for SaaS.
3. Persistent agent history — orchestrator state resets on container restart; no durable audit log of completed WOs. Impact: medium.

---

## Recently Completed

| Date | Capability | WO |
|------|------------|----|
| 2026-07-02 | Velocity projection + milestone on-track badges | WO-360 |
| 2026-07-02 | Orchestrator REST API (claim/checkin/validate) | WO-359 |
| 2026-07-02 | PLAN.json plan store + priority queue | WO-358 |
| 2026-07-01 | Orchestrator polling loop + daily summary | WO-356 |
| 2026-06-30 | Status site v2 — dark design system, all views | WO-355 |
| 2026-06-30 | PR Watchdog service | WO-354 |
