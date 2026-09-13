# Factory Program Backlog — Operator & Engineering Todos

_Last updated: 2026-09-12_

Single checklist for closing the “UI-complete factory” loop. Check items off when
merged or verified. Detailed specs live in `docs/work_orders/`.

---

## Now (in flight)

- [ ] WO-1099 — Settings UI: METRICS_ENDPOINT (`wo/1099-metrics-endpoint-settings`)

---

## Next (after 1094–1099)

| # | Item | Owner | Notes |
|---|------|-------|-------|
| 1 | Enable CD in UI once runner is online | Operator | Settings → Deploy & Harness → toggle (needs `factory-deploy` runner) |
| 2 | Optional weekly spend budget | Operator | Same page → `USAGE_BUDGET_USD_WEEK` |
| 3 | Set `METRICS_ENDPOINT` | Operator | ✅ UI in WO-1099 — save URL under Deploy & Harness → Observability |
| 4 | Clarion DOC_MAP `new_ui_page` → wiki/docs + inAppHelpMap | Product | ✅ Merged in dentroio/clarion#842 |
| 5 | Oryntra deep integration | Eng | WO-1048 / WO-1049 — other agent |
| 6 | Exact LLM billing (not estimates) | Eng | Needs CLI/API usage hooks |

---

## Done recently

| WO | Title | Merged |
|----|-------|--------|
| WO-1098 | Multi-repo polling loop crash fix | 2026-09-12 (#336) |
| WO-1097 | Docs enforcement hardening | 2026-09-12 (#333) |
| WO-1094/1095/1096 | Engine CD + Deploy & Harness + factory guide | 2026-09-11 (#327) |
| WO-1093 | LLM harness hardening | 2026-09-07 |
| WO-1092 | Draft ports + remount | 2026-09-06 |
| WO-1091 | Adoption DX | 2026-09-04 |
| WO-1090 | Runner auth / zero-trust | 2026-08-31 |

---

## How to use this list

1. Engineers: pick the top unchecked WO in **Now**, follow its `## Execution` section.
2. Operators: after merge, work the **Next** table top-down in the dashboard UI.
3. Update this file **at merge time** (same rule as PROGRESS.md).
