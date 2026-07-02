"""
plan_engine.py — Pure priority-sort function for the Factory Plan Store.

Algorithm (from WO-358 spec):
  1. Exclude status in {done, deferred, claimed, in_progress, review}
  2. Exclude any WO where any depends_on entry is not done
  3. Sort remaining by:
     a. pin == true first
     b. Phase order (index in phases list) — 'parallel' phases interleave at P1
     c. Within phase: P1 → P2 → P3
     d. Within priority: effort S → M → L
     e. Within effort: most blocks_milestones first
  4. Return first item
"""

from __future__ import annotations

_EXCLUDE_STATUSES = {"done", "deferred", "claimed", "in_progress", "review"}

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_EFFORT_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3}


def _phase_sort_key(wo: dict, phase_index: dict[str, int]) -> int:
    """
    Return the effective sort key for phase ordering.
    Phases marked parallel=true interleave with all phases at position 0
    (i.e., they are always eligible alongside the earliest non-parallel phase).
    We model this by giving parallel-phase WOs a key of 0 so they float to
    the top in phase ordering, while still being sorted within that group by
    priority/effort/milestone weights.
    """
    phase_id = wo.get("phase", "")
    return phase_index.get(phase_id, 999)


def next_wo(plan: dict, wo_statuses: dict[str, str]) -> dict | None:
    """
    Given the full PLAN.json dict and a mapping of WO id → live status string,
    return the highest-priority open, unblocked WO entry, or None if queue is empty.

    wo_statuses keys must be canonical WO IDs like 'WO-358'.
    Status values are normalised internally to lowercase for comparison.
    """
    phases: list[dict] = plan.get("phases", [])
    queue: list[dict] = plan.get("queue", [])

    # Build phase lookup: id → (sort_position, is_parallel)
    phase_meta: dict[str, tuple[int, bool]] = {}
    for i, phase in enumerate(phases):
        phase_meta[phase["id"]] = (i, phase.get("parallel", False))

    # Merge plan-level statuses with live statuses.
    # Live status (from WO files / branches / PRs) wins over plan-stored status.
    def _effective_status(wo: dict) -> str:
        wo_id = wo.get("wo", "")
        if wo_id in wo_statuses:
            return wo_statuses[wo_id].lower()
        return wo.get("status", "open").lower()

    # Build set of done WO ids for dependency checking
    done_ids: set[str] = set()
    for wo in queue:
        if _effective_status(wo) == "done":
            done_ids.add(wo["wo"])
    # Also add any done statuses from live dict that may not be in queue
    for wo_id, status in wo_statuses.items():
        if status.lower() == "done":
            done_ids.add(wo_id)

    # Step 1 + 2: Filter
    candidates: list[dict] = []
    for wo in queue:
        status = _effective_status(wo)
        if status in _EXCLUDE_STATUSES:
            continue
        deps = wo.get("depends_on", [])
        if any(dep not in done_ids for dep in deps):
            continue
        candidates.append(wo)

    if not candidates:
        return None

    # Step 3: Sort
    def _sort_key(wo: dict):
        # a. pinned first (0 = pinned, 1 = not pinned)
        pin_key = 0 if wo.get("pin") else 1

        # b. phase order — parallel phases sort to position 0 (alongside earliest phase)
        phase_id = wo.get("phase", "")
        idx, is_parallel = phase_meta.get(phase_id, (999, False))
        phase_key = 0 if is_parallel else idx

        # c. priority within phase
        prio_key = _PRIORITY_ORDER.get(wo.get("priority", "P3"), 9)

        # d. effort within priority
        effort_key = _EFFORT_ORDER.get(wo.get("effort", "M"), 1)

        # e. most blocks_milestones first (invert count)
        milestones_key = -len(wo.get("blocks_milestones", []))

        return (pin_key, phase_key, prio_key, effort_key, milestones_key)

    candidates.sort(key=_sort_key)
    return candidates[0]


def sorted_queue(plan: dict, wo_statuses: dict[str, str]) -> list[dict]:
    """
    Return the full candidate queue sorted by priority (same algorithm as next_wo,
    but returns all candidates rather than just the first).
    """
    phases: list[dict] = plan.get("phases", [])
    queue: list[dict] = plan.get("queue", [])

    phase_meta: dict[str, tuple[int, bool]] = {}
    for i, phase in enumerate(phases):
        phase_meta[phase["id"]] = (i, phase.get("parallel", False))

    def _effective_status(wo: dict) -> str:
        wo_id = wo.get("wo", "")
        if wo_id in wo_statuses:
            return wo_statuses[wo_id].lower()
        return wo.get("status", "open").lower()

    done_ids: set[str] = set()
    for wo in queue:
        if _effective_status(wo) == "done":
            done_ids.add(wo["wo"])
    for wo_id, status in wo_statuses.items():
        if status.lower() == "done":
            done_ids.add(wo_id)

    candidates: list[dict] = []
    for wo in queue:
        status = _effective_status(wo)
        if status in _EXCLUDE_STATUSES:
            continue
        deps = wo.get("depends_on", [])
        if any(dep not in done_ids for dep in deps):
            continue
        candidates.append(wo)

    def _sort_key(wo: dict):
        pin_key = 0 if wo.get("pin") else 1
        phase_id = wo.get("phase", "")
        idx, is_parallel = phase_meta.get(phase_id, (999, False))
        phase_key = 0 if is_parallel else idx
        prio_key = _PRIORITY_ORDER.get(wo.get("priority", "P3"), 9)
        effort_key = _EFFORT_ORDER.get(wo.get("effort", "M"), 1)
        milestones_key = -len(wo.get("blocks_milestones", []))
        return (pin_key, phase_key, prio_key, effort_key, milestones_key)

    candidates.sort(key=_sort_key)
    return candidates
