# Factory Program Backlog — Operator & Engineering Todos

_Last updated: 2026-09-14_

Single checklist for closing the “UI-complete factory” loop. Check items off when
merged or verified. Detailed specs live in `docs/work_orders/`.

---

## Now (in flight)

_None — queue clear except CD planning (deferred)._

---

## Next (operator / deferred eng)

| # | Item | Owner | Notes |
|---|------|-------|-------|
| 1 | Enable CD in UI once runner is online | Operator | **Deferred — planning separately.** Needs `factory-deploy` runner + Settings → Deploy & Harness toggle |
| 2 | Optional weekly spend budget | Operator | Settings → Deploy & Harness → `USAGE_BUDGET_USD_WEEK` |
| 3 | Set `METRICS_ENDPOINT` | Operator | Public JSON health URL (not localhost) via Deploy & Harness → Observability |
| 4 | Clarion DOC_MAP `new_ui_page` → wiki/docs + inAppHelpMap | Product | ✅ Merged in dentroio/clarion#842 |
| 5 | Oryntra dogfood | Eng | ✅ Merged [dentroio/Oryntra#3](https://github.com/dentroio/Oryntra/pull/3) 2026-09-14 |
| 6 | Exact LLM billing (not estimates) | Eng | WO-1105 (`wo/1105-js-scan-and-api-usage`) — API usage hooks; subscription CLIs stay estimates |

---

## Done recently

| WO | Title | Merged |
|----|-------|--------|
| WO-1104 | Orphan closer must not close canonical implementation PRs | 2026-09-14 (#346) |
| WO-1103 | Refuse non-product WOs on the Clarion factory queue | 2026-09-13 (#342) |
| WO-1099 | Settings UI: METRICS_ENDPOINT (observability) | 2026-09-13 (#340) |
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
