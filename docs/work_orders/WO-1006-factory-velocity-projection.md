# WO-1006 — Factory Velocity + Milestone Projection

**Status:** ✅ Complete
**Priority:** P2
**Repo:** `dentroio/agentic-factory`
**Estimated effort:** M (4–6 hours)
**Depends on:** WO-1004 (PLAN.json + velocity.json), WO-1005 (dispatch — provides cycle time data)

---

## Background

The factory knows what to work on (WO-1004) and how to start it (WO-1005). WO-1006 answers "are we on track?" — computing rolling velocity, calibrating effort estimates, and projecting milestone dates.

## What Needs to Happen

### velocity.py
```python
def compute_velocity(runs_dir: Path, weeks: int = 4) -> float:
    """WOs completed per week over the last `weeks` weeks."""
    ...

def detect_bottlenecks(queue: list[dict], velocity: float) -> list[str]:
    """Return list of bottleneck descriptions (e.g. all P1 items are L effort)."""
    ...
```

### projection.py
```python
def project_milestones(plan: dict, velocity: float) -> dict[str, dict]:
    """
    For each milestone, count remaining blocker WOs and divide by velocity.
    Returns {milestone_id: {projected_date, status: on_track|at_risk|blocked}}.
    on_track  = projected_date <= target
    at_risk   = projected_date <= target + 2 weeks
    blocked   = projected_date > target + 2 weeks
    """
    ...
```

### Orchestrator integration
Call `compute_velocity()` and `project_milestones()` on each poll cycle. Write results into `orchestrator.json` under `velocity` and `milestones`. Update `docs/factory/velocity.json` with latest completed WO data.

### Plan tab — Velocity section
Below the phase progress bars, add a Velocity card:
- WOs/week (rolling 4-week)
- Effort P50/P90 cycle time (S/M/L)
- Milestone projection: target date | projected date | status chip (On Track / At Risk / Behind)

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `compute_velocity()` reads claim file timestamps from `docs/factory/runs/` and git log |
| 2 | `project_milestones()` returns on_track/at_risk/blocked for each milestone in PLAN.json |
| 3 | Orchestrator writes `velocity` and milestone projections to orchestrator.json on each poll |
| 4 | Plan tab shows velocity card with milestone projections |
| 5 | `velocity.json` is updated with each newly completed WO |

## Key Files to Create/Modify

| File | Change |
|------|--------|
| `services/orchestrator/velocity.py` | New — compute_velocity(), detect_bottlenecks() |
| `services/orchestrator/projection.py` | New — project_milestones() |
| `services/orchestrator/orchestrator.py` | Call velocity + projection on each poll |
| `services/status-site/templates/plan.html` | Add velocity + projection card |
| `docs/factory/velocity.json` (clarion) | Updated by orchestrator after each WO completion |
