# Paste-in GitHub workflows (for **your** product repo)

These are **copies** of factory workflow ideas. Paste them into a **consumer** repository’s `.github/workflows/`.

Do **not** replace or edit the live workflows in this engine repo (`.github/workflows/` at the root). Changing those would affect the factory’s own CI.

| File | Purpose |
|------|---------|
| `planning-agent.yml` | Issue labeled `new-wo` → draft WO spec PR |
| `dependabot-wo-bridge.yml` | Failed Dependabot PR → `new-wo` issue |
| `ai-review.yml` | Advisory review comment on PRs |
| `ai-review-applier.yml` | Apply “Needs attention” suggestions on agent PRs |
| `ci-auto-fix.yml` | Patch red CI on agent PRs (limited attempts) |
| `merge-advisor.yml` | Synthesize merge recommendation |
| `automation-watchdog.yml` | Alert if unattended workflows fail repeatedly |
| `auto-update-prs.yml` | Merge `main` into open `wo/*` branches |
| `ci.yml.template` | Starting point for **your** language CI (rename to `ci.yml` and edit) |

Scripts some of these call (`scripts/planning_agent.py`, `scripts/ai_review.py`, …) live in **this** engine repo. Either:

- Keep using the factory against a target repo that does not run those Actions, or
- Copy the matching `scripts/*.py` into the consumer repo if you enable the workflow there.

The [template repo](https://github.com/dentroio/agentic-factory-template) already wires a minimal demo CI. Paste extra workflows from this folder if you want planning-agent, AI review, etc.
