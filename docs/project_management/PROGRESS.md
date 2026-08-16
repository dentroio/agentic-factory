# Dentro AI Factory — Progress Tracker

_Last updated: 2026-08-16_

---

## How to read this doc

- ✅ Complete — merged to main, verified
- 🟡 In Progress — branch exists or agent is working
- 🔵 Open — scoped, not started
- ❌ Cancelled — descoped, reason noted

Update this file **at the time of merge**, not before.

---

## Work Orders

| WO | Title | Priority | Status | Merged |
|----|-------|----------|--------|--------|
| WO-1064 | Empty unit-test suite must fail CI | P1 | 🟡 In Progress | — |
| WO-1063 | Remaining workflow injection (AF-13) | P0 | ✅ Complete | 2026-08-16 |
| WO-1062 | CI AI review treats the PR diff as data | P1 | ✅ Complete | 2026-08-16 |
| WO-1061 | AI reviewer cannot satisfy the human validation gate | P1 | ✅ Complete | 2026-08-16 |
| WO-1060 | Persist retry attempts across dispatch delete | P1 | ✅ Complete | 2026-08-16 |
| WO-1059 | Dashboard authentication (AF-08) | P0 | ✅ Complete | 2026-08-16 |
| WO-1058 | Fine-grained GitHub PAT only | P1 | ✅ Complete | 2026-08-15 |
| WO-1057 | Scoped Vault token for the orchestrator | P1 | ✅ Complete | 2026-08-15 |
| WO-1056 | Do not write factory secrets to disk or logs | P1 | ✅ Complete | 2026-08-15 |
| WO-1055 | Treat WO markdown as untrusted prompt data | P1 | ✅ Complete | 2026-08-15 |
| WO-1054 | Factory audit closeout (no autonomous development) | P0 | ✅ Complete | 2026-08-15 |
| WO-1014 | Plan Authoring UI — Create WOs/Phases/Milestones | P2 | ✅ Complete | 2026-07-04 |
| WO-1013 | Multi-Agent Peer Review Chain | P2 | ✅ Complete | 2026-07-04 |
| WO-1012 | Quality Gate — CI + Bandit + Semgrep Enforcement | P2 | ✅ Complete | 2026-07-03 |
| WO-1011 | Oryntra Chrome Extension + Thread Image Support | P2 | ✅ Complete | 2026-07-04 |
| WO-1010 | Agent Thread Awareness — Mid-Task Q&A + Directives | P2 | ✅ Complete | 2026-07-04 |
| WO-1009 | WO Thread — Per-WO Conversation + SSE Stream | P2 | ✅ Complete | 2026-07-04 |
| WO-1008 | Codex GitHub Actions Dispatch | P2 | ✅ Complete | 2026-07-04 |
| WO-1007 | Notification Webhooks (ntfy.sh + Slack) | P2 | ✅ Complete | 2026-07-04 |
| WO-365 | Agent Runner — Multi-Backend Autonomous Execution | P2 | ✅ Complete | 2026-06-27 |
| WO-1006 | Factory Velocity + Milestone Projection | P2 | ✅ Complete | 2026-07-02 |
| WO-1005 | Factory Orchestrator Auto-Dispatch (REST API) | P2 | ✅ Complete | 2026-07-02 |
| WO-1004 | Factory Plan Store + Priority Queue | P2 | ✅ Complete | 2026-07-02 |
| WO-1004 | Multi-Repo Config UI + Settings | P2 | ✅ Complete | 2026-07-02 |
| WO-1003 | Factory Orchestrator Loop | P2 | ✅ Complete | 2026-07-01 |
| WO-1002 | Status Site v2 — PM View, CI View, enriched cards | P2 | ✅ Complete | 2026-06-30 |
| WO-1001 | PR Watchdog Service + alert panel | P2 | ✅ Complete | 2026-06-30 |

### Quality Fixes (no WO number — committed directly to main)

| Fix | Description | Date |
|-----|-------------|------|
| wo/dashboard-wo-source-of-truth | Dashboard data integrity, defects 1/2/4 (WO specs read from the GitHub default branch instead of a feature-branch mount; open PR outranks a merged PR title match; deterministic duplicate-number resolution) and defects 3/7 ("Running" defined once as dispatch `claimed`/`in_progress` and shared by all pages; new Stalled column; shared `agents_in_flight()`) and defects 5/6 (velocity counts distinct work orders instead of pull requests, 47.2/wk → 22.0/wk; merged-PR window fetched via search `merged:>=` and reports its own completeness instead of truncating silently). Total WOs 434 → 439, In Review 0 → 3, Merged This Month 195 → 90. All seven defects in [DASHBOARD_DATA_INTEGRITY_FIXES.md](DASHBOARD_DATA_INTEGRITY_FIXES.md) | 2026-08-05 |
| fix/factory-resilience | Auto-recovery on build/CI failure (`release_dispatch` → `POST /api/dispatch/{wo}/retry`); retry context injection (`format_prior_context()` injects prior rejection reason + ci_analysis into next attempt); `ValidationDecision.reject_reason` field + storage; factory status timestamps (live feed HH:MM:SS + WO card last-seen relative time); dispatch management endpoints | 2026-07-14 |
| fix/factory-quality-alignment | Semgrep ERROR-only threshold, JS/TS security scan, performance + code quality mandate in agent prompt, Codex/Cursor `ask()` rewritten to use OpenAI API (not agentic CLI) | 2026-07-04 |

---

## Milestones

| Milestone | Target | Status |
|-----------|--------|--------|
| M1: Live Dashboard | 2026-06-30 | ✅ Complete |
| M2: Orchestrator + Agent Loop | 2026-07-02 | ✅ Complete |
| M3: Multi-Repo + Projections | 2026-07-03 | ✅ Complete |
| M4: Agent Runner + Quality Gate | 2026-07-03 | ✅ Complete |
| M5: Thread + Notifications + Dispatch | 2026-07-04 | ✅ Complete |
| M6: Review Chain + Oryntra + Plan Authoring | 2026-07-04 | ✅ Complete |

---

## Blocked / Needs decision

_None currently._
