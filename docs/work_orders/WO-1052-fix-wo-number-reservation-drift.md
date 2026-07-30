# WO-1052 — Fix WO Number Reservation Counter Drift

**Created:** 2026-07-23
**Priority:** P2
**Effort:** S → M (see below)
**Services:** orchestrator, status-site
**Repos:** `dentroio/agentic-factory`
**Depends on:** —
**Status:** ✅ Done

---

## Background

Observed 2026-07-23 while scoping the Oryntra program: `GET /api/plan/next-wo-number`
returned `{"next": 1035, "wo_id": "WO-1035", "reserved": true}` while spec files in
`docs/work_orders/` already reach WO-1046.

## Actual root cause (differs from the original diagnosis above)

This was never a stale persisted counter — investigation on 2026-07-29 found the
reservation endpoint has no notion of "which repo" at all. `GITHUB_REPO` and `WO_PATH`
are hardcoded in `.env` to `dentroio/clarion` / `docs/project_management/work_orders`.
`/api/wos/reserve` always numbered against Clarion's WO space, permanently — it just
happened to answer correctly when Clarion's own WO-1035 already existed there. There
was no "flooring the counter" that would have fixed this: the scan target itself was
wrong for any caller asking about agentic-factory's own WOs.

Two independent WO-number sequences — Clarion's and agentic-factory's own
`docs/work_orders/` — use overlapping numeric ranges (both in the low-1000s), which is
exactly what made this collision-prone rather than merely inconvenient.

`POST /api/factory/wos` was and remains unaffected — it numbers from spec files
directly via `gw.next_wo_number()`, which already takes `repo`/`wo_path` params.

## What was built

In `services/orchestrator`:

- `_reserved` restructured from `dict[int, meta]` to `dict[repo, dict[int, meta]]`,
  with migration of the old flat-format `reserved_wos.json` on load.
- `ReserveRequest` gained optional `repo` / `wo_path` fields (default to
  `GITHUB_REPO`/`WO_PATH` — existing callers unaffected).
- New `_next_wo_number_for(client, repo, wo_path)`: for the default repo, delegates to
  the existing local-mount scan; for any other repo, does a single GitHub directory-
  listing call to collect WO numbers from filenames. Deliberately does **not** reuse
  `_fetch_wo_specs` (which fetches and parses full file content for every WO — 50+
  API calls for agentic-factory's own directory, which blew past status-site's 5s
  timeout on the first live test).
- `/api/wos/reserved` takes an optional `repo` query param.
- Claim-consume and the intelligence loop's internal reservations stay pinned to
  `GITHUB_REPO` explicitly — both are Clarion-only flows.

In `services/status-site`:

- `/api/plan/next-wo-number` takes optional `repo`/`wo_path` query params, forwarded
  to the orchestrator reservation call and to the GitHub-API fallback path.

No startup-reconciliation warning was added — with the redesign there's no separate
persisted "counter" to drift from the files; each reservation is computed live against
current known numbers (reserved + on-disk/API scan), so there's nothing to reconcile
at startup.

## Domain Notes

- Reserved-but-unwritten numbers are legitimate (an agent reserves, then opens a PR).
- Verified live 2026-07-29 against running containers: Clarion reservation → 1036
  (correct next after the real WO-1035), agentic-factory reservation → 1053 (correct
  next after real spec files through WO-1052) — previously both would have returned
  the same (wrong, for one of the two) number.

## Acceptance Criteria

- [x] Reserving against `dentroio/agentic-factory` (`docs/work_orders`) returns a
      number past its own real spec-file max, not Clarion's
- [x] Reserving against the default repo is unaffected (still returns Clarion's next
      number)
- [x] Two consecutive reservations in the same repo return strictly increasing numbers
- [x] A reservation in one repo does not consume or block a number in the other, even
      when their ranges overlap
- [x] Unit tests cover: independent numbering per repo, non-interference across repos,
      and flat→nested `reserved_wos.json` migration (11 tests, all passing)
- [x] Live-verified against running orchestrator + status-site containers, including
      the timeout regression found and fixed during that verification

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/orchestrator/orchestrator.py` | Per-repo `_reserved`, `_next_wo_number_for`, reserve/list endpoints take `repo`/`wo_path` |
| Modify | `services/status-site/main.py` | `/api/plan/next-wo-number` forwards `repo`/`wo_path` |
| Modify | `tests/unit/test_reservation.py` | Per-repo independence + migration tests |
