---
name: wo-resolver-docs-scope-title-not-completion
description: docs(...)/chore(...)-scoped PR titles never complete a WO by title mention alone in wo_resolver.py's completion logic
metadata:
  type: project
---

The `wos_completed_by_merged_pr` function (in `scripts/wo_resolver.py`, `services/orchestrator/wo_resolver.py`, and `services/status-site/wo_parser.py` — three parity copies kept in sync via `test_wo_resolver_parity.py`) previously treated any merged PR title matching `WO-NNN:` or `WO-NNN —` as completing that WO. This caused the orphan-closer (`reviewer.py::_cleanup_stale_prs`) to auto-close a real implementation PR because a merged spec PR titled `docs(pm): WO-547 — ... spec` matched the loose scan and falsely marked WO-547 done.

**Why:** A `docs(...)`/`chore(...)` conventional-commit prefix means the PR documents/tracks the WOs it names, not implements them. This is a project-specific convention, not a generic Python/regex fact — the resolver must distinguish "names a WO" from "implements a WO."

**How to apply:** When touching WO-completion detection logic, remember: a WO is only credited via (1) a `wo/NNN-` branch, (2) an explicit "mark(ed) ... complete/done" title, or (3) a `Status: ✅` spec-file reconcile (orchestrator.py backstop