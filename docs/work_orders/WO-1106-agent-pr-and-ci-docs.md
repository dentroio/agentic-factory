# WO-1106 — Apply `agent-pr` on runner PRs and correct engine CI docs

**Status:** ✅ Complete (2026-09-21)
**Priority:** P2
**Effort:** S
**Services:** agent-runner | docs
**Depends on:** none

## Problem

CI auto-fix and the AI review applier only run on PRs labeled `agent-pr` (or
authored by a short bot allow-list). The runner's `gh pr create` never applies
that label, so self-healing stays dormant on real factory/Clarion agent PRs.

Separately, engine docs still describe Clarion's five-job CI (`Lint`,
`Frontend`, `Migration Safety`, `PR Gate`) as if it were this repo's gate.
`factory_status.py` / `setup_factory.py` only check `new-wo`, so a missing
`agent-pr` never shows up as a setup gap.

## What to Build / What to Fix

1. Agent-runner `gh pr create` applies `--label agent-pr`, ensuring the label
   exists first. Missing-label must not block opening the PR.
2. Prompt process step tells coding agents to pass `--label agent-pr`.
3. `factory_status.py` and `setup_factory.py` require `new-wo`, `agent-pr`, and
   `pm-sync`. Setup ruleset list matches the live engine checks.
4. Correct `AGENT_PROCESS.md` §9, `docs/GITHUB_ACTIONS_GUIDE.md`, wiki
   GitHub-Integrations, ENGINEER.md, and CAPABILITY_STATUS so they describe
   this engine's actual jobs (not Clarion's).

## Out of scope

- Adding lint / frontend / migration jobs to this engine's `ci.yml`
- Setting `METRICS_ENDPOINT` (operator URL; already on BACKLOG)
- Changing Clarion's CI or ruleset

## Do NOT change

- Engine required status check names (`Unit Tests`, `Secret Detection (Gitleaks)`,
  `Claude Code Review`, `Risk Tier Approval Gate`)
- Product paste-ins in `templates/github/` except comments that would lie about
  the engine

## Acceptance Criteria

- [ ] Runner PR create argv includes `--label agent-pr`
- [ ] Label create / add failure does not prevent returning a PR URL
- [ ] `factory_status.py` treats `agent-pr` and `pm-sync` as required engine labels
- [ ] Engine CI docs list the four live required checks, not Clarion's PR Gate set
- [ ] Unit tests cover the argv helper and the status-script label list
- [ ] `make ci-local` passes

## Execution

- **Branch:** `wo/1106-agent-pr-and-ci-docs`
- **Risk tier:** P2 — human verifies running product, then auto-merge after CI + review
- **Services:** agent-runner | docs
- **PR title:** `fix(agent-runner): WO-1106 — label agent PRs and correct engine CI docs`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** none
- **User verification required:** Yes — restart agent-runner; confirm next runner PR has `agent-pr`
- **PM docs to update:** PROGRESS.md row, CAPABILITY_STATUS.md section

### UI Verification

No UI changes — backend / docs only.

1. `make agent-stop && make agent-start`
2. `make agent-status` shows the daemon loaded
3. Next WO PR opened by the runner has the `agent-pr` label on GitHub
