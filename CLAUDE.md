# Claude Code — {{PROJECT_NAME}}

**Read `AGENT_PROCESS.md` before starting any implementation task.** It is the single source of truth for how agents work on this repository: risk tiers, branch/PR workflow, merge authority, and critical code patterns.

## Quick reference

| Priority | Action |
|----------|--------|
| P0/P1 | Branch → implement → `make ci-local` → PR → notify human |
| P2 | Branch → implement → `make ci-local` → PR → `gh pr merge --auto --squash` |
| P3 (docs/PM only) | Commit directly to `main` |

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
