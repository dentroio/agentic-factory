# WO-1104 — Orphan closer must not close canonical implementation PRs

**Created:** 2026-09-14
**Priority:** P2
**Effort:** S
**Services:** agent-runner
**Depends on:** WO-1041
**Status:** ✅ Complete (2026-09-14)

---

## Problem

The factory orphan-closer auto-closed a real implementation PR because the
dispatch/status surface said the WO had already completed via a different
bookkeeping PR.

Observed incident:

- A planning/bookkeeping PR marked a WO complete in queue state.
- The real implementation PR was still open on a canonical `wo/NNN-...` branch.
- `services/agent-runner/reviewer.py::_cleanup_stale_prs()` saw dispatch status
  `complete` with a different `pr_url` and closed the real PR as an orphan.

This repeats the same class of status-surface drift bug fixed earlier for WO
resolution: automation state is useful, but it must not overrule a live
implementation branch without corroboration.

## What to Build

Add a small decision helper in `services/agent-runner/reviewer.py` for complete
dispatch entries:

- Continue closing non-canonical orphan PRs when the WO is complete via another
  recorded PR.
- Do not auto-close an open PR whose branch is canonical for that WO
  (`wo/NNN-...`) just because dispatch state says the WO is complete elsewhere.
- Preserve deferred-WO auto-close behavior.

Add unit coverage for:

- canonical implementation branch is not closed when dispatch says complete via
  a different PR
- non-canonical duplicate/orphan branch is still closed
- same recorded PR is not closed

## Out of scope

- Changing queue storage.
- Changing WO completion resolution.
- Changing project onboarding or `PLAN.json` behavior.
- Reopening already closed PRs automatically.

## Do NOT change

- The WO resolver parity contract.
- Deferred-WO auto-close behavior.
- Runner review/approval behavior outside stale PR cleanup.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

`reviewer.py::_cleanup_stale_prs()` is a destructive GitHub action path. It
should prefer false negatives over false positives. A stale implementation PR is
annoying; closing the real implementation because a bookkeeping/status surface
drifted is worse.

## Acceptance Criteria

- [ ] Unit tests prove a canonical `wo/NNN-...` branch is not auto-closed solely
      because dispatch state says the WO completed via another PR.
- [ ] Unit tests prove non-canonical stale duplicate PRs can still be closed.
- [ ] Existing reviewer gate tests pass.
- [ ] `make ci-local` passes or any unrelated pre-existing failure is documented.

## Files

| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/agent-runner/reviewer.py` | Harden stale PR close decision |
| Modify | `tests/unit/test_reviewer_gate.py` | Add regression tests |
| Create | `docs/work_orders/WO-1104-orphan-closer-implementation-prs.md` | Work Order spec |

## Execution

- **Branch:** `wo/1104-orphan-closer-implementation-prs`
- **Risk tier:** P2
- **Services:** agent-runner
- **PR title:** `fix(agent-runner): WO-1104 — protect canonical implementation PRs`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1041
- **User verification required:** No runtime product verification; show focused unit test output.

## Closeout

- **Verification evidence:** `pytest tests/unit/test_reviewer_gate.py tests/unit/test_wo_resolver.py tests/unit/test_wo_resolver_parity.py -q` passed (`66 passed`); `python scripts/pre_pr_check.py` passed; `make secrets` passed; `black --check services/agent-runner/reviewer.py tests/unit/test_reviewer_gate.py` passed after formatting touched files.
- **Full local gate:** `make test` ran 522 tests; 521 passed and one unrelated local subprocess timeout test failed: `tests/unit/test_subprocess_timeouts.py::test_communicate_kills_grandchild_on_timeout`.
- **Follow-ons filed:** none.
- **Residual risks:** stale duplicate implementation branches may now require human cleanup instead of automatic closure; this is intentional for destructive safety.
- **Docs/status updated:** this WO spec.
