---
name: dependabot-yml-not-template
description: GitHub only reads .github/dependabot.yml (not .template files); config must list every services/*/requirements.txt directory explicitly
metadata:
  type: project
---

GitHub Dependabot only reads `.github/dependabot.yml` — a `.github/dependabot.yml.template` or similar placeholder file is invisible to GitHub and silently produces zero dependency PRs. Also, Dependabot's `pip` ecosystem does not auto-discover requirements files across a monorepo; each `services/*/requirements.txt` directory must be listed as its own explicit entry in `dependabot.yml`, alongside a `github-actions` ecosystem entry for workflow files.

**Why:** The team had a template file checked in that looked correct but was never actually active, so dependency updates silently stopped arriving for all Python services and Actions.

**How to apply:** When adding/removing a service with its own `requirements.txt`, add a matching directory entry to `.github/dependabot.yml` (not a template). Policy convention for this repo: `interval: "monthly"`, `rebase-strategy: "disabled"`, ignore `version-update:semver-major`, and restrict `update-types` to `["minor", "patch"]`. `tests/unit/test_dependabot_config.py` enforces these invariants — update it when adding new services.