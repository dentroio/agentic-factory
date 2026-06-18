# Agents — {{PROJECT_NAME}}

This file is the entry point for OpenAI Codex and other agents that read `AGENTS.md`.

## Setting up this factory for the first time?

Read `ENGINEER.md` and act as the Project Engineer. Run `python3 scripts/factory_status.py` first to see what needs to be configured.

---

**Read `AGENT_PROCESS.md` before starting any implementation task.**

## What you need to know

- All work is organized into Work Orders (WOs) in `docs/project_management/work_orders/`
- Every WO has a `## Execution` section — that tells you the branch name, risk tier, PR title, and what PM docs to update
- Run `make ci-local` before opening any PR — it mirrors the GitHub Actions gate exactly
- Risk tier determines merge authority: P0/P1 = human merge, P2 = auto-merge after CI, P3 = direct to main

## Quick start

```bash
# 1. Read the WO spec
cat docs/project_management/work_orders/WO-NNN-slug.md

# 2. Branch
git checkout -b wo/NNN-slug

# 3. Implement

# 4. Gate
make ci-local

# 5. PR
gh pr create --title "feat(scope): WO-NNN — Title" --body "..."

# 6. Merge (P2 only)
gh pr merge --auto --squash
```

See `AGENT_PROCESS.md` for the full rule set.
