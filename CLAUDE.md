# Claude Code — {{PROJECT_NAME}}

## First time here?

Run the factory status check:
```bash
python3 scripts/factory_status.py
```

If anything is missing, say: **"Read ENGINEER.md and help me finish setting up the factory."**
That activates the Project Engineer — an agent persona that walks you through CI, CD, branch protection, AI review, and the full agent loop.

---

**Read `AGENT_PROCESS.md` before starting any implementation task.** It is the single source of truth for how agents work on this repository: risk tiers, branch/PR workflow, merge authority, and critical code patterns.

## Development environment

**Read `## §3 Development Environment` in `AGENT_PROCESS.md`** before making code changes — it tells you whether to rebuild Docker containers, push to staging, or use a cloud dev URL to verify your work.

## Quick reference

| Priority | Action |
|----------|--------|
| P0/P1 | sync → branch → implement → **deploy → ask user to verify** → ci-local → PR → notify human |
| P2 | sync → branch → implement → **deploy → ask user to verify** → ci-local → PR → auto-merge |
| P3 (docs/PM only) | Commit directly to `main` — no deploy, no user checkpoint |

## ⛔ Ask the user to verify before committing

After deploying code changes, **do not commit** until the user confirms the running system looks correct. See `AGENT_PROCESS.md §2b` for the exact wording and the re-verify loop for PR fixes.

## Critical patterns

> Replace with project-specific invariants. Examples:
> - Always call `db.commit()` after writes
> - Register every new migration in the migration runner
> - Every new API route needs an auth dependency

## One-time setup

```bash
make install          # install dependencies
pre-commit install    # install git hooks
```

## Local gate before every PR

```bash
make ci-local
```
