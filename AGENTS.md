# Agents — Dentro AI Factory (engine)

This checkout is the **factory engine**. Product specs live in `GITHUB_REPO`. Adopters: [docs/wiki/Adopting.md](docs/wiki/Adopting.md). Product process: [docs/adopters/PROCESS.md](docs/adopters/PROCESS.md).

This file is the entry point for OpenAI Codex and other agents that read `AGENTS.md`.

## Setting up this engine for the first time?

Read `ENGINEER.md` and act as the Project Engineer. Run `python3 scripts/factory_status.py` first to see what needs to be configured.

---

**Read `AGENT_PROCESS.md` before starting any implementation task.**

## What you need to know

- All work is organized into Work Orders (WOs) in `docs/project_management/work_orders/`
- Dispatch-ready WOs use the canonical shape: `Problem`, `What to Build`, `Out of scope` / `Do NOT change`, `Acceptance Criteria`, and `Execution`
- Every WO has `**Services:**` metadata and a `## Execution` section — together they tell you what to rebuild or verify, the branch name, risk tier, PR title, and human checkpoint
- Run `make ci-local` before opening any PR — it mirrors the GitHub Actions gate exactly
- Risk tier determines merge authority: P0/P1 = human merge, P2 = human verifies the running product before commit, then auto-merge after CI + review, P3 = docs-only PR with no product checkpoint

## Quick start

```bash
# 1. Read the WO spec
cat docs/project_management/work_orders/WO-NNN-slug.md

# 2. Branch
git checkout -b wo/NNN-slug

# 3. Implement

# 4. Verify running behavior and stop for human checkpoint on P0-P2

# 5. Gate
make ci-local

# 6. PR
gh pr create --title "feat(scope): WO-NNN — Title" --body "..."

# 7. Merge (P2 only, after CI + review)
gh pr merge --auto --squash
```

See `AGENT_PROCESS.md` for the full rule set.
