# WO-1052 — Fix WO Number Reservation Counter Drift

**Created:** 2026-07-23
**Priority:** P2
**Effort:** S
**Services:** orchestrator
**Repos:** `dentroio/agentic-factory`
**Depends on:** —
**Status:** Open

---

## Background

Observed 2026-07-23 while scoping the Oryntra program: `GET /api/plan/next-wo-number`
returned `{"next": 1035, "wo_id": "WO-1035", "reserved": true}` while spec files in
`docs/work_orders/` already reach WO-1046. WO-1035 has existed since the
factory-UI-simplification work. Any caller trusting this endpoint (WO-1043 built it
for agents drafting specs) would collide with an existing WO — and the endpoint
*reserves* the number as a side effect, so each probe advances a counter that is
already wrong.

`POST /api/factory/wos` is unaffected — it numbers from the spec files in the repo
via `gw.next_wo_number()`, which is why it remains the authoritative creation path.

## What to Build

In `services/orchestrator`:

1. **Floor the counter on the spec files** — on every reservation request, compute
   `max(existing spec file numbers, PLAN entries, DB queue entries)` and return
   `max(counter, computed) + 1`, persisting the corrected counter. The counter may
   only ever move forward.
2. **Startup reconciliation** — on orchestrator start, run the same computation and
   log at WARN if the stored counter was behind the spec files (include both values).
3. **Test** — unit test: counter behind files → reservation returns file-max + 1 and
   the counter is persisted forward; counter ahead of files (numbers reserved but
   specs not yet written) → counter is respected.

## Domain Notes

- Reserved-but-unwritten numbers are legitimate (an agent reserves, then opens a PR)
  — that is why the fix is `max(counter, files) + 1`, not "always files + 1".
- Check where the counter is stored (SQLite vs JSON state file) before writing; the
  reservation logic landed in WO-1043 (PR #34).

## Acceptance Criteria

- [ ] With spec files up to WO-1046 and a stale counter, `GET /api/plan/next-wo-number`
      returns ≥ 1047
- [ ] Two consecutive reservations return strictly increasing numbers
- [ ] Startup log warns when the stored counter is behind the spec-file max
- [ ] Unit tests cover both drift directions (counter behind / counter ahead)

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/orchestrator.py` (or module owning reservation) | Floor counter on spec-file max |
| Create/Modify | orchestrator tests | Drift regression tests |
