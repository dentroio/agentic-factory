# WO-1091 — Adoption DX: factory doctor, init, stranger-clone checks

**Created:** 2026-09-04
**Priority:** P2
**Effort:** M
**Services:** docs, scripts
**Depends on:** —
**Status:** ✅ Done

---

## Problem

The engine is product-agnostic (`factory.yaml`, adopter kit, independence I1–I7), but first-time adoption still fails in silent ways: wrong `LOCAL_REPO_PATH`, missing `factory.yaml`, prefs pointing at the engine instead of the product, and BYO setup that is checklist-only. There is no single command that says “wired correctly,” and no regression gate that a stranger clone stays Clarion-free on the default path.

## What to Build

1. **`scripts/factory_doctor.py`** (+ `make doctor`)
   - Read prefs from `~/.config/factory-agent/prefs` and env overrides.
   - Check: `GITHUB_REPO` shape; `LOCAL_REPO_PATH` exists and is a git checkout; remote `owner/name` matches `GITHUB_REPO` (fail on mismatch); product `factory.yaml` (or `docs/factory/profile.yaml`) loads; `verify` first token is runnable or Makefile target exists; WO specs dir present; optional `gh` reachability for product labels / WO path.
   - Warn (not fail) when `FACTORY_LEGACY_PRODUCT` is set for a non-matching repo.
   - Exit 0 only when hard checks pass; print fix hints for each failure.
   - Support `--product PATH` to doctor a product tree without relying on prefs (for CI/tests).

2. **`scripts/factory_init.py`** (+ `make init`)
   - Scaffold a product repo (path arg, default cwd): `docs/project_management/work_orders/`, `docs/factory/runs/.gitkeep`, `docs/factory/patterns.md`, root `factory.yaml`, copy `docs/adopters/PROCESS.md` → `AGENT_PROCESS.md`.
   - Optional `--sample-wo` writes a minimal `WO-001-hello.md`.
   - Non-interactive flags: `--name`, `--verify`, `--ui-url`, `--force` (overwrite). Refuse to clobber without `--force`.
   - Print next steps (labels, point engine prefs, `make doctor`).

3. **Stranger-clone / no-leak regression**
   - `tests/unit/test_stranger_clone.py`: default `load_profile` + patterns contain no Clarion; public agent-facing files (`scripts/agent-setup.sh`, `services/agent-runner/prompt_builder.py`, root `README.md`) must not name Clarion as the default product; `clarion_patterns.md` is only loaded when legacy env matches.
   - Keep `FACTORY_LEGACY_PRODUCT` path working for the live Clarion instance (do not delete legacy loader).

4. **UI-first product onboarding**
   - Host `product_setup.py` + draft-server `GET/PUT /api/product`, `POST /api/product/clone`
   - Orchestrator proxies; live-update `GITHUB_REPO` on secrets PUT
   - Settings → Authentication: local path, clone, prepare files, restart hint
   - Overview CTA when product not ready
5. **Docs** — Getting Started / Adopting / BYO / Dashboard Guide UI-first

## Out of scope

- Linux Keychain / systemd parity
- Self-contained GitHub Actions pack / vendoring scripts into products
- Hosted remote runner
- Quarantining `clarion_patterns.md` out of the repo (legacy still needed for live instance)
- Auto-remount without `make restart`
- Multi-repo local paths in Settings → Projects

## Do NOT change

- Live Clarion legacy profile behavior when `FACTORY_LEGACY_PRODUCT` matches `GITHUB_REPO`
- Engine `.github/workflows/` required checks

## Acceptance Criteria

- [x] `python3 scripts/factory_doctor.py --product <tmp>` fails with a clear message when `factory.yaml` is missing; passes after `factory_init` scaffolds that tree
- [x] `python3 scripts/factory_init.py --path <tmp> --name demo --non-interactive` creates the expected files without network
- [x] `make doctor` and `make init` are documented Makefile targets
- [x] `tests/unit/test_stranger_clone.py` and doctor/init/product_setup unit tests pass under `make ci-local`
- [x] Default (non-legacy) profile patterns contain no `clarion` / `Clarion` strings
- [x] Draft server exposes bearer-gated `/api/product` and `/api/product/clone`
- [x] Orchestrator proxies those routes; `PUT /api/secrets` with `GITHUB_REPO` updates in-memory repo
- [x] Auth UI can set local path / clone / scaffold without hand-editing prefs
- [x] Overview shows setup CTA when product is not ready

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `docs/work_orders/WO-1091-adoption-dx-doctor-init.md` | This spec |
| Create | `scripts/factory_doctor.py` | Adoption wiring checks |
| Create | `scripts/factory_init.py` | BYO scaffold |
| Create | `services/agent-runner/product_setup.py` | Host prefs / clone / scaffold |
| Create | `tests/unit/test_factory_doctor.py` | Doctor unit tests |
| Create | `tests/unit/test_factory_init.py` | Init unit tests |
| Create | `tests/unit/test_product_setup.py` | Product setup unit tests |
| Create | `tests/unit/test_stranger_clone.py` | No-Clarion default path |
| Modify | `services/agent-runner/draft_server.py` | `/api/product*` |
| Modify | `services/orchestrator/orchestrator.py` | Proxy + live GITHUB_REPO |
| Modify | `services/status-site/main.py` | Auth save + Overview CTA |
| Modify | `services/status-site/templates/settings_authentication.html` | Product checkout UI |
| Modify | `services/status-site/templates/dashboard.html` | Setup banner |
| Modify | `Makefile` | `doctor` / `init` targets |
| Modify | `docs/wiki/Getting-Started.md` | UI-first onboarding |
| Modify | `docs/wiki/Adopting.md` | UI-first wiring |
| Modify | `docs/wiki/Dashboard-Guide.md` | Auth product fields |
| Modify | `docs/adopters/BYO.md` | Prefer UI then init |
| Modify | `README.md` | Fastest path |

## Execution

- **Branch:** `wo/1091-adoption-dx-doctor-init`
- **Risk tier:** P2
- **Services:** docs, scripts, status-site, orchestrator, agent-runner
- **PR title:** `feat(adoption): WO-1091 — factory doctor, init, and UI product onboarding`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** none
- **User verification required:** Yes — Auth UI path/clone/scaffold + `make doctor` against live prefs
- **PM docs to update:** PROGRESS.md, CAPABILITY_STATUS.md
