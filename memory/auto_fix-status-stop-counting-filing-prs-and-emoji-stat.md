---
name: wo-status-logic-triplicated-across-repo
description: wo status/PR-completion classification logic is duplicated in three files and must be kept in sync via a parity test
metadata:
  type: project
---

The WO status classification (`classify_wo_status`) and merged-PR-completion logic (`wos_completed_by_merged_pr`) are copy-pasted verbatim into three separate files: `scripts/wo_resolver.py`, `services/orchestrator/wo_resolver.py`, and `services/status-site/wo_parser.py`. There is no shared import between them — each is a standalone implementation.

**Why:** These services are deployed/run independently and apparently can't share a common module easily, so the pattern chosen is "duplicate + test for parity" rather than "extract shared lib." `t