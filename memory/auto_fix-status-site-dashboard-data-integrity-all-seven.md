---
name: status-site-single-source-invariants
description: Dashboard "counts" (Running, WO throughput, spec ownership) must go through wo_reconcile.py's shared helpers — never re-derived per page/client
metadata:
  type: project
---

The status-site dashboard previously had the same conceptual number (e.g. "Running", "merged this month") computed 3-4 different ways across pages/JS, each individually plausible but silently disagreeing. This was fixed by centralizing all reconciliation logic in `wo_reconcile.py` (dispatch_status_counts, apply_live_status, weekly_wo_throughput, etc.), which deliberately imports nothing but `wo_parser` so it stays unit-testable without FastAPI.

Key invariants now enforced (partly by CI test `test_running_count_single_source.py`, which greps source for violations):
- "Running" means dispatch status `claimed` or `in_progress` — everywhere, including client-side JS (which must fetch `/api/factory/counts` instead of filtering dispatch itself).
- Work-order throughput/velocity must resolve via `resolve_all_wos_for_pr` and credit a WO to its **earliest** merge in-window, not latest — crediting the latest lets finished work "reappear" in later weeks as follow-up PRs keep naming it.
- Merged-PR fetching must page by actual merge time via the search API and report whether the window is *complete* — a short/failed fetch must be visually distinguishable (e.g. amber bars, "no data") from a genuin