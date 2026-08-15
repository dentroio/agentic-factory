---
name: wo-status-merged-pr-title-mention-guard
description: apply_live_status() must not let a merged PR that merely mentions a WO number in its title flip that WO's status if the spec is already Deferred (or similar deliberate terminal states)
metadata:
  type: project
---

`apply_live_status()` in `services/status-site/wo_reconcile.py` treats any merged PR whose title mentions a WO number as "this WO is Done" — but that heuristic is title-matching, not a check that the PR actually implemented the WO. A pure docs/backfill commit (e.g. "docs(wo): backfill work-order specs ... file WO-484") that merely name-drops a WO number in passing can silently flip a deliberately Deferred WO to Done, corrupting dashboard counts.

**Why:** Deferred is a human decision (e.g. superseded by another approach); a title mention in an unrelated merged PR is not evidence of completion and must never override it.

**How to apply:** When touching the merged-PR override logic in `apply_live_status`, preserve the `spec_column != "deferred"` guard (or extend it to other deliberate terminal states) before flipping status to Done. When adding new status-inference heuristics based on PR titles/text, always check whether the current spec status represents a human decision that a fuzzy match shouldn't override.