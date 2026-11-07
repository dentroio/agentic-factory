# WO-1107 — Product Work Order Protocol Support (non-numeric WO IDs, protocol states, second instance)

**Status:** 🔵 Open (Draft — needs owner readiness review)
**Priority:** P1
**Assigned:** Agent
**Target:** 2026-10-23
**Depends on:** none

---

## Problem

The engine assumes every product numbers its work orders `WO-<integer>` and keeps one engine instance per
machine. The AegisFlux product (`dentroio/aegisflux`) uses the **Work Order Protocol** (level 2): IDs like
`WO-UX-032` and `WO-OPS-020`, states Draft / Ready / In Progress / Review / Complete / Blocked / Deferred, a draft
PR as the claim (no `docs/factory/runs/WO-NNN.json`), and specs under
`docs/project_management/work_orders/<program>/WO-AREA-NNN_TITLE.md`. Numeric-only parsing is hard-coded in at least:

- `services/orchestrator/wo_resolver.py` (`_WO_NUM_RE = \bWO-(\d+)\b`, `_BRANCH_RE = wo/(\d+)-`), `thread.py` (`^WO-\d+$`)
- `services/status-site/wo_parser.py`, `wo_reconcile.py`, `github_writer.py` (`WO-(\d+)`, `wo/(\d+)-`, `depends_on` as ints)
- `services/agent-runner/reviewer.py`, `runner.py` (worktree names `wo-{num}-...`)

So the engine cannot list, claim, review or reconcile AegisFlux work orders. The engine also reads a single
`~/.config/factory-agent/prefs` and fixed launchd labels (`com.dentroio.factory-agent*`) and ports 8099/8100, so a
second product cannot run beside Clarion.

## Goal

Point a second engine instance at `dentroio/aegisflux` and have the dashboard, orchestrator, PR watchdog and agent
runner treat its work orders correctly, without changing behavior for numeric-ID products (Clarion).

## Scope

**In scope:**
- **WO key type:** a single `parse_wo_ref()` returning a string key (`"1106"` or `"UX-032"`) from filenames, PR titles
  and branch names; pattern `WO-(?:[A-Z][A-Z0-9]*-)?\d+[A-Z]?` for text and `wo/(?:\d+|[a-z][a-z0-9]*-\d+[a-z]?)-?` for
  branches. Replace int-keyed dicts and `depends_on` lists; keep numeric products working (their key is the digit string).
- **Product profile (`factory.yaml`) section `work_orders:`** — `protocol: numeric | work-order-protocol`,
  `specs_glob` (recursive), `status_field` (`**Status:**`), `state_map` (protocol states to engine states),
  `claim: claim_file | draft_pr`, `status_record` (read-only path, e.g. `docs/project_management/WORK_ORDER_STATUS.md`),
  `agent_process` (product `AGENT_PROCESS.md` is included in the prompt), `no_status_file_edits: true`.
- **Claim by draft PR:** in `draft_pr` mode the runner claims by creating the branch and a draft PR; no claim JSON.
- **Readiness gate:** only WOs whose status is Ready (protocol) are dispatchable; the dashboard shows protocol states.
- **Second instance:** `FACTORY_INSTANCE=<name>` namespaces prefs path, launchd labels, Docker compose project, host ports
  and the memory directory. `make agent-install INSTANCE=aegisflux` installs a parallel set. Default (unset) is unchanged.
- **Safety defaults for agents:** `AGENT_PERMISSION_MODE` default becomes `acceptEdits` with the tool allowlist for
  `protocol` products; a worker-host check like AegisFlux `scripts/pm/dispatch.py`.
- Tests for each parser with numeric and protocol inputs; a fixture product directory with five protocol WOs.

**Out of scope:**
- Multi-product in one instance; changing Clarion's configuration; auto-merging protocol-product PRs (the owner merges).

## Approach

Introduce `services/common/wo_ref.py` and migrate callers in small commits (parser first, then resolver, then
status-site, then runner), keeping a compatibility shim `int(key)` only where a numeric product is configured. Read the
protocol statuses with the same rule as AegisFlux `scripts/pm/wo_status.py` (`**Status:**` first word match). Reuse
AegisFlux's `scripts/pm/agent_prompt.md` ideas for the protocol prompt. Instance namespacing via one helper
(`services/common/instance.py`).

## Acceptance Criteria

- [ ] With `factory.yaml` `work_orders.protocol: work-order-protocol`, the dashboard lists AegisFlux's Ready WOs with IDs like `WO-UX-032` and states from the WO files.
- [ ] A dispatched WO produces a branch matching the WO's `Branch:` field and a draft PR titled `type(area): WO-UX-032 - title`; no claim file is written.
- [ ] PR watchdog, reviewer and reconcile jobs map AegisFlux PRs to their WOs by title and branch.
- [ ] Clarion (numeric) behavior and tests are unchanged.
- [ ] Two instances run side by side with distinct ports, prefs, launchd labels and compose projects.
- [ ] `make ci-local` passes.

## Verification Steps

```bash
make ci-local
python3 -m pytest tests/unit/test_wo_ref.py tests/unit/test_wo_reconcile.py -v
FACTORY_INSTANCE=aegisflux make doctor DOCTOR_ARGS='--product ~/workspace/github/dentroio/aegisflux'
```

---

## Execution

**Branch:** `wo/1107-product-work-order-protocol-support`
**Risk tier:** P1
**PR title:** `feat(factory): WO-1107 — product Work Order Protocol support`
**Auto-merge:** no (P1 — notify human)

**PM docs to update after merge:** `docs/project_management/PROGRESS.md` row; `docs/wiki/Product-Profile.md` (new `work_orders:` section); `docs/adopters/CONTRACT.md`.

## Closeout

- **Verification evidence:**
- **Follow-on WOs filed:**
- **Residual risks:**
