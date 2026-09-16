---
name: wo-completion-logic-duplicated-four-files
description: wos_completed_by_merged_pr (WO completion detection from PR title/branch) is copy-pasted across four files and must be updated in lockstep
metadata:
  type: project
---

The logic that decides whether a merged PR "completes" a WO (`wos_completed_by_merged_pr`) is independently duplicated in: `scripts/wo_resolver.py`, `services/orchestrator/wo_resolver.py`, `services/status-site/wo_parser.py`, and reimplemented (as `_wos_completed_by_merged_pr`) in `services/pr-watchdog/watchdog.py`. There is no shared module.

Also note the invariant this logic encodes: a `docs(...)`/