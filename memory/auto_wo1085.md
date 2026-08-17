---
name: required-status-checks-list-drift
description: When adding a new required CI check, update both the branch protection ruleset AND scripts/factory_status.py + ENGINEER.md's hardcoded list
metadata:
  type: project
---

Required status checks are enforced via GitHub branch protection ruleset, but the list is also duplicated as a hardcoded array in `scripts/factory_status.py::check_ruleset()` and documented in ENGINEER.md. These do not sync automatically.

**Why:** WO-1072 added a Gitleaks CI job and configured it as a required check in the ruleset, but factory_status.py and ENGINEER.md still had the old list — meaning a new factory setup could pass validation while silently missing the Gitleaks requirement.

**How to apply:** Whenever a new required CI check/job is added (or renamed), grep for the existing required-checks array in `scripts/factory_status.py` (`check_ruleset`) and update it plus ENGINEER.md in the same PR. Don't assume the ruleset config is the single source of truth.