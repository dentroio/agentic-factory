---
name: wo-spec-section-validation-sync
description: Work order template section headings must stay in sync across planning_agent.py, github_writer.py, and orchestrator.py's SPEC_REQUIRED_SECTION_GROUPS
metadata:
  type: project
---

The orchestrator validates work order specs by checking for required section headings (`SPEC_REQUIRED_SECTION_GROUPS` in `services/orchestrator/orchestrator.py`), matched as "one-of" synonym groups (e.g. `## Problem`/`## Background`/`## Motivation`/`## Scope`, and `## What to