# WO-1022 — PM Situational Awareness: Inject Context When Drafting WO Specs

**Created:** 2026-07-09
**Priority:** P2
**Effort:** S
**Status:** ✅ Complete
**Services:** orchestrator
**Depends on:** WO-1021 (SQLite queue — provides clean DB query for open WOs)
**Blocks:** WO-1023

---

## Background

When the PM agent drafts a WO spec today, it writes blind. The system prompt (`_DRAFT_SYSTEM` in `orchestrator.py`) gives it only the WO number and the user's plain-English description. It has no awareness of:

- What WOs are currently open and their priority/effort
- What's already in the queue and in what order
- What was recently shipped (to avoid duplicating work)
- Current phases and milestone target dates
- Deferred WOs that might be related

This means the PM agent cannot reason about sequencing, dependencies, or redundancy. A spec drafted for "add IPSK endpoint labeling" might produce P2/M with no `depends_on` — even though WO-199 (pxGrid cert auth, also P2/M) is open and should go first. The PM agent has to guess at priority and effort with no frame of reference.

The same gap exists in the PM chat (`/api/pm/chat`): the chat context includes the board state, but the draft endpoint (`/api/plan/draft`) does not.

---

## What to Build

### 1. Build a situational brief function

In `orchestrator.py`, add `_pm_situational_brief() -> str`:

```python
def _pm_situational_brief() -> str:
    """Return a brief of current factory state for injection into PM prompts."""
    lines = []

    # Open WOs (from spec files — the authoritative source)
    open_wos = [
        (num, spec) for num, spec in sorted(_spec_cache.items())
        if not _is_done(spec.get("status", "")) and not _is_blocked(spec.get("status", ""))
    ]
    if open_wos:
        lines.append("CURRENTLY OPEN WORK ORDERS (not yet started or in progress):")
        for num, spec in open_wos[:15]:  # cap at 15 to control prompt size
            pri = spec.get("priority", "?")
            effort = spec.get("effort", "?")
            title = spec.get("title", f"WO-{num}")
            st = spec.get("status", "")[:40]
            lines.append(f"  WO-{num} [{pri}/{effort}]: {title} — {st}")
    else:
        lines.append("CURRENTLY OPEN WORK ORDERS: none")

    # Queue order (from DB after WO-1021; fall back to PLAN.json overlay)
    lines.append("")
    lines.append("PRIORITY QUEUE ORDER (top 10):")
    queue = _get_queue_from_db()  # new helper after WO-1021
    for i, entry in enumerate(queue[:10], 1):
        lines.append(f"  {i}. {entry['wo']}: {entry['title']} [{entry['priority']}/{entry['effort']}]")

    # Active phases and milestones
    lines.append("")
    lines.append("PHASES AND MILESTONES:")
    for phase in _get_phases_from_db():
        ms = f" → {phase['milestone_id']}" if phase.get("milestone_id") else ""
        lines.append(f"  Phase {phase['id']}: {phase['label']} (target {phase['target_date']}){ms}")
    for ms in _get_milestones_from_db():
        lines.append(f"  Milestone {ms['id']}: {ms['label']} — {ms['target_date']}")

    # Recently shipped (last 5 — from spec files with ✅ status and recent merged_at)
    lines.append("")
    lines.append("RECENTLY SHIPPED (last 5):")
    recent = _get_recent_completions(limit=5)
    for wo_id, title in recent:
        lines.append(f"  {wo_id}: {title}")

    return "\n".join(lines)
```

### 2. Inject the brief into `_DRAFT_SYSTEM`

The system prompt is currently a module-level constant. Convert it to a function `_build_draft_system(brief: str) -> str` that appends the situational brief:

```python
def _build_draft_system(brief: str) -> str:
    return _DRAFT_SYSTEM_BASE + f"\n\n=== CURRENT FACTORY STATE ===\n{brief}\n\nUse this context to:\n- Set priority relative to existing open WOs (don't create a P1 if there are already 3 open P1s)\n- Set effort relative to similar WOs already in the queue\n- Identify depends_on based on related open WOs listed above\n- Avoid duplicating work already in progress or recently shipped\n- Suggest an appropriate phase based on active phases above\n"
```

### 3. Inject into the PM chat system prompt

The PM chat at `POST /api/pm/chat` already includes board context via `_wo_status_summary()`. Augment it to also include the queue order and milestone state from the brief. The PM chat is conversational so the brief should be shorter — just open WOs and queue order (skip the recently shipped section).

### 4. Inject into the DOC_MAP

When building the draft system prompt, also read `docs/factory/DOC_MAP.json` from the local repo mount (if available) and append a condensed version:

```
=== DOCUMENTATION REQUIREMENTS ===
When the WO involves [trigger], the spec must include a "Documentation Required" section listing updates to [files].
Always check AGENT_PROCESS.md if the WO changes any pattern agents must follow.
```

This ensures every PM-generated spec includes documentation obligations from the start.

---

## Acceptance Criteria

- [ ] `POST /api/plan/draft` includes the situational brief in the system prompt
- [ ] The brief lists all currently open WOs with priority and effort
- [ ] The brief includes the current queue order (top 10)
- [ ] The brief includes active phases and milestone target dates
- [ ] PM chat (`/api/pm/chat`) includes queue order and milestone context
- [ ] Draft output sets `depends_on` appropriately when related open WOs are mentioned in the brief
- [ ] Brief is capped so total system prompt stays under 6,000 tokens (to leave room for the WO description and response)
- [ ] DOC_MAP.json triggers appear in the draft system prompt when the file exists
- [ ] All existing `/api/plan/draft` tests pass

## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — update the "Draft routing" section to describe the situational brief injection and DOC_MAP reading
