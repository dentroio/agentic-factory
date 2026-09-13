# WO-1098 — Fix Orchestrator Multi-Repo Polling Loop Crash

**Created:** 2026-09-12
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Depends on:** WO-1089
**Status:** 🟡 In Progress

---

## Problem

A critical regression from WO-1089 causes the factory orchestrator to crash on every polling interval (every 60 seconds):

```python
Job "poll (trigger: interval[0:01:00], next run at: ...)" raised an exception
Traceback (most recent call last):
  File ".../apscheduler/executors/base.py", line 181, in run_coroutine_job
    retval = await job.func(*job.args, **job.kwargs)
  File "/app/orchestrator.py", line 4314, in poll
    for idx, p in enumerate(configured_projects):
                            ^^^^^^^^^^^^^^^^^^^
NameError: name 'configured_projects' is not defined
```

### Root Cause
1. In `services/orchestrator/orchestrator.py`, line 4314 iterates over `configured_projects`, using `specs_results[idx]`, `branch_results[idx]`, and `pr_results[idx]`.
2. However, at the top of `poll()` (lines 4055–4085), the code was only gathering `primary_specs_task`, `active_branches_task`, `pr_wos_task`, and `secondary_tasks`, leaving `configured_projects`, `specs_results`, `branch_results`, and `pr_results` completely undefined in the function scope.
3. Because `poll()` crashes midway through every cycle, `/data/orchestrator.json` is never written, `/api/plan` returns empty queues (`"queue": []`, `"all_wos": []`), and autonomous dispatch across all repos is completely blocked.
4. Additionally, `_fetch_active_branches` checked `if LOCAL_REPO_MOUNT:` without verifying `repo == GITHUB_REPO`, which would mistakenly read primary repo local git branches when querying secondary repositories.

## What to Build

1. In `poll()`:
   - Load `configured_projects = _get_configured_repos()`.
   - Concurrently fetch `specs`, `active_branches`, `open_prs`, and merged PRs for all configured repositories.
   - Populate `specs_results`, `branch_results`, `pr_results`, `merged_this_week`, and `merged_wo_prs`.
   - Update global `_open_pr_wos` to the combined `pr_wos` set.
2. In `_fetch_active_branches`:
   - Scope local git ref query to `if LOCAL_REPO_MOUNT and repo == GITHUB_REPO:`, querying the GitHub API for any secondary repositories.
3. Unit tests:
   - Add unit test verifying `poll()` executes cleanly without `NameError` and correctly combines specs, branches, and PRs across multiple configured projects.
   - Test `_fetch_active_branches` respects `repo == GITHUB_REPO` for local mount vs API fallback.

## Out of scope

- Changing the priority sorting algorithm or conflict advisor rules.
- Oryntra deep integration (being worked by another agent).

## Acceptance Criteria

- [ ] `poll()` runs without `NameError` when one or more projects are configured.
- [ ] Multi-repo specs, active branches, and open PRs are fetched in parallel and aggregated.
- [ ] `_fetch_active_branches` only queries `LOCAL_REPO_MOUNT` when `repo == GITHUB_REPO`.
- [ ] Unit tests verify multi-project polling aggregation and lack of undefined variable errors.
- [ ] Orchestrator Docker container runs cleanly without polling exceptions in logs.
- [ ] `make ci-local` passes.

## Execution

- **Branch:** `wo/1098-orchestrator-multi-repo-poll-fix`
- **Risk tier:** P2 — auto-merge after CI + human verification
- **PR title:** `fix(orchestrator): WO-1098 — multi-repo polling loop crash fix`
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
