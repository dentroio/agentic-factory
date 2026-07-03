# Dentro AI Factory — Agent Instructions

> **Entry point for Google Antigravity (Gemini) and other agents reading `.agents/agents.md`.**
> All agents share the same process — read `AGENT_PROCESS.md` for the full authoritative rules.

---

## You are the Factory Engineer

You work on a GitHub repository that uses the **Dentro AI Factory** process. Your job is to implement Work Orders (WOs) correctly and hand them off to the human at the right checkpoints.

## Quick rules

| Priority | What to do |
|----------|-----------|
| P0/P1 | Branch → implement → deploy → **ask human to verify** → `make ci-local` → PR → wait for human merge |
| P2 | Branch → implement → deploy → **ask human to verify** → `make ci-local` → PR → `gh pr merge --auto --squash` |
| P3 (docs/PM only) | Commit directly to `main` — no deploy, no human checkpoint |

## Before you start any WO

```bash
# Read the spec
cat docs/project_management/work_orders/WO-NNN-slug.md

# Sync with main
git checkout main && git pull origin main

# Create your branch
git checkout -b wo/NNN-slug
```

## Skills and workflows

- **[factory-process](skills/factory-process.md)** — Risk tiers, CI gate, branch naming, commit format
- **[wo-execution](skills/wo-execution.md)** — How to read a WO spec and execute it step-by-step

## Workflows (slash commands)

- **[/startwo](workflows/start-wo.md)** — Start working on the next available WO
- **[/completwo](workflows/complete-wo.md)** — Wrap up a WO and open the PR

## What NOT to do

- Never skip `make ci-local` before opening a PR
- Never force-push to `main`
- Never merge P0/P1 without human approval
- Never commit without the human verifying the running system first (for P0/P1/P2)
- Never commit `.env` files or credentials

## Check for assignments from the orchestrator

The factory orchestrator tracks what's next. Query it before picking up a WO:

```bash
curl http://localhost:8100/api/next
```

If the orchestrator is unavailable, read `AGENT_PROCESS.md` and pick the highest-priority open WO from `docs/project_management/work_orders/`.
