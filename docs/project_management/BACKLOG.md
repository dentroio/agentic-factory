# Factory Program Backlog — Operator & Engineering Todos

_Last updated: 2026-09-07_

Single checklist for closing the “UI-complete factory” loop. Check items off when
merged or verified. Detailed specs live in `docs/work_orders/`.

---

## Now (in flight)

### WO-1094 — Engine CD workflow (PR #327)
- [x] `deploy.yml` for `docker-compose.status.yml` (gated by `FACTORY_CD_ENABLED`)
- [x] `make smoke` / `scripts/factory_smoke.py`
- [ ] Human merge of PR #327 (P1)
- [ ] Self-hosted runner registered with label `factory-deploy` (operator — GitHub UI)

### WO-1095 — Settings → Deploy & Harness (UI, no file edits)
- [x] Settings card + `/settings/deploy-harness` page
- [x] Toggle `FACTORY_CD_ENABLED` on **engine** GitHub repo via API
- [x] Show self-hosted runners / `factory-deploy` label status
- [x] Edit harness prefs in UI → `~/.config/factory-agent/prefs` (tool policy, budget)
- [x] Prefs flow into runner via existing `factory-env.sh` (restart agent to apply)
- [x] Unit tests + `make ci-local`
- [x] Docs: Getting-Started, LLM-Harness, CAPABILITY_STATUS, this BACKLOG

### WO-1096 — In-app factory guide + inline help refresh (same PR track)
- [x] Visual guide on Overview (`/`) — lifecycle + architecture diagrams, dismissible
- [x] Standalone `/guide` + Settings hub card + nav **Guide**
- [x] Refresh `?` help for Overview, Factory, PM, Engineering, Plan, History, Usage, Settings + subpages (Get Started, Deploy & Harness, Agents, …)

---

## Next (after 1094+1095)

| # | Item | Owner | Notes |
|---|------|-------|-------|
| 1 | Enable CD in UI once runner is online | Operator | Settings → Deploy & Harness → toggle |
| 2 | Optional weekly spend budget | Operator | Same page → `USAGE_BUDGET_USD_WEEK` |
| 3 | Set `METRICS_ENDPOINT` | Operator | Still GitHub Actions variable (follow-up UI if needed) |
| 4 | Oryntra deep integration | Eng | WO-1048 / WO-1049 |
| 5 | Exact LLM billing (not estimates) | Eng | Needs CLI/API usage hooks |

---

## Done recently

| WO | Title | Merged |
|----|-------|--------|
| WO-1093 | LLM harness hardening | 2026-09-07 |
| WO-1092 | Draft ports + remount | 2026-09-06 |
| WO-1091 | Adoption DX | 2026-09-04 |
| WO-1090 | Runner auth / zero-trust | 2026-08-31 |

---

## How to use this list

1. Engineers: pick the top unchecked WO in **Now**, follow its `## Execution` section.
2. Operators: after merge, work the **Next** table top-down in the dashboard UI.
3. Update this file **at merge time** (same rule as PROGRESS.md).
