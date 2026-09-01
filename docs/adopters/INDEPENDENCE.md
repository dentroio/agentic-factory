# Factory independence — engineering archive

**Distribution:** Internal-Only (Engineering)  
**Status:** **Complete** (I1–I7 landed). Kept as a historical checklist — not an onboarding guide.

**For new adopters:** use [Getting Started](../wiki/Getting-Started.md), [Adopting](../wiki/Adopting.md), and [Product Profile](../wiki/Product-Profile.md).

---

## What shipped

| Item | Outcome |
|------|---------|
| Docs / template / blog | Public adopter kit + [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) |
| I1–I4 | `factory.yaml` profile loader; generic runner / quality gate / PM |
| I5 | No product passwords in public engine; doc-writer skips unset product wiki repo |
| I6 | Product-owned `factory.yaml` in private product repos (not engine defaults) |
| I7 | Adopter acceptance on a template-derived repo; live Clarion-pointed instance unchanged |

**Hard rule that remains true:** genericize the engine; load product behavior from `factory.yaml` (or a temporary local overlay), not from hardcoded strings in this public repo.

## Original program text

The sections below are the original work-order style instructions used during the program. They are retained for archaeology; do not treat “Still required” lines as open work.

---

## Hard rules

1. **Clarion stays the live product** for the existing factory instance (`GITHUB_REPO=dentroio/clarion` in Keychain). After independence, that instance must still dispatch Clarion WOs correctly.
2. **A stranger** clones this engine, sets `GITHUB_REPO` to the template (or their app), and the **agent-runner** must not mention Clarion, Clarion UI login, `src/clarion/`, or `COMPOSE_PROJECT_NAME=clarion`.
3. **Do not** bake product passwords into this public repo. Remove any that are already here.
4. **Do not** replace live `.github/workflows/` with product-template workflows. `doc-writer.yml` may skip the Clarion job when `CLARION_REPO` is unset.
5. Verify on a **second checkout** (or the template) before declaring done. Do not use Clarion as the only test target.

---

## WO-I1 — Product profile (contract)

**Priority:** P1 · **Where:** this engine + template; Clarion yaml later (WO-I6)

Define a small file the runner reads from the **product worktree** (not from engine git):

Suggested path: `factory.yaml` at product repo root (or `docs/factory/profile.yaml`).

Minimum fields:

```yaml
name: my-app
verify: "make ci-local"
ui_url: "http://localhost:8765"
ui_verify_hint: "Open the demo page; confirm the heading matches the WO."
compose_project: ""          # empty = do not set COMPOSE_PROJECT_NAME
patterns_file: "docs/factory/patterns.md"  # optional; missing = generic mandate only
```

Engine behavior:

- If the file is missing → generic prompts, run `make ci-local` if present else skip rebuild with a logged warning.
- If present → use those fields. **Clarion’s copy of this file is private** (WO-I6). Until it exists, a **local-only** fallback is allowed: `FACTORY_PROFILE=/path/to/clarion-profile.yaml` or keep reading `clarion_patterns.md` **only when** `GITHUB_REPO` matches the configured live product (env `FACTORY_LEGACY_PRODUCT=dentroio/clarion`). Prefer the yaml; the env fallback is temporary so Steve’s factory does not break mid-migration.

Ship a `factory.yaml` + short `docs/factory/patterns.md` in **agentic-factory-template**.

---

## WO-I2 — Agent runner prompts and verify steps

**Priority:** P1 · **Files:** `services/agent-runner/prompt_builder.py`, `runner.py`, `reviewer.py`

Replace Clarion-hardcoded strings with profile + `GITHUB_REPO`:

| Location | Today | Required |
|----------|--------|----------|
| `prompt_builder.py` `build_prompt` | “Clarion AI Factory”; `clarion_patterns.md` | “product `{GITHUB_REPO}`”; patterns from profile or generic mandate |
| `runner.py` `_analyze_failure` | “Clarion worktree” | “product worktree” |
| `runner.py` `_generate_validation_steps` | Product UI URL + login baked in | `ui_url` + `ui_verify_hint` from profile; **no passwords in engine git** |
| `runner.py` ~767 | “This is the Clarion product repo” | “This is `{GITHUB_REPO}`, not the factory engine” |
| `reviewer.py` | “Clarion network security platform”; same login | Generic senior-engineer review + profile UI hint |

`clarion_patterns.md`: stop using it as the default for every clone. Move content to Clarion (WO-I6) or keep the file **gitignored / not shipped** in public clones. Public engine may keep the file only behind `FACTORY_LEGACY_PRODUCT` until WO-I6 lands.

---

## WO-I3 — Quality gate and Compose

**Priority:** P1 · **File:** `services/agent-runner/quality_gate.py`

- Do not default `COMPOSE_PROJECT_NAME` to `clarion`. Use profile `compose_project` or omit.
- Do not assume Clarion `frontend-check` / two-container `correlation_engine` rebuild. Infer services from the **product** diff + profile, or run only `verify` from `factory.yaml`.
- `make ci-local` must be the **product** worktree’s Makefile (template has one). If the product has no `ci-local`, fail with a clear message pointing at `factory.yaml` `verify:`.

---

## WO-I4 — Orchestrator PM and tools

**Priority:** P1 · **File:** `services/orchestrator/orchestrator.py`

- PM system prompt: not “PM for the Clarion project”. Use product `name` from profile or the `GITHUB_REPO` slug.
- Tool descriptions: drop `src/clarion/...` examples; use generic paths or profile examples.
- `_query_clarion_connectors` / Clarion preflight: run **only** if profile enables it (or `FACTORY_LEGACY_PRODUCT` matches). Strangers must not hit a Clarion API.
- Comments that say “defaults to Clarion” → “defaults to `GITHUB_REPO`/`WO_PATH`”.

`occupancy.py`: rename user-facing strings from “Clarion claim file” to “product claim file”.

---

## WO-I5 — Public leaks and clone noise

**Priority:** P0 (secrets) / P2 (noise)

- **P0:** Remove product admin passwords from public engine git (`runner.py`, `reviewer.py` history will still contain them — rotate the Clarion local admin password if that login is still valid).
- Do not ship `services/agent-runner/memory/factory_memory.json` lessons that name Clarion internals (`adapter.py`, etc.). Seed empty or engine-only lessons.
- `doc-writer.yml`: if `vars.CLARION_REPO` is unset, **skip** the Clarion wiki job (do not default `dentroio/clarion`). Stranger forks must not try to push to a private product.
- `templates/github/automation-watchdog.yml` workflow name list: do not require “Update Clarion + Factory Wikis” on product repos.
- `agent-setup.sh`: print that `GITHUB_REPO` is the **product** (template or BYO), never imply Clarion. Optional: if repo empty, print the template URL.

---

## WO-I6 — Clarion product profile (private repo, after I1–I4)

**Priority:** P1 · **Where:** `dentroio/clarion` only

Add `factory.yaml` (and patterns) so **Steve’s** factory keeps Clarion rebuilds, UI verify, and Compose project name **without** those strings living as engine defaults.

Until this merges, `FACTORY_LEGACY_PRODUCT=dentroio/clarion` on the Mac is acceptable.

---

## WO-I7 — Acceptance: stranger clone

**Priority:** P1 · **Do this last**

On a machine (or dir) **without** a Clarion clone:

1. Clone `agentic-factory`, `make agent-setup`, set `GITHUB_REPO` to a repo created from `agentic-factory-template`.
2. `make up` — dashboard lists template WOs.
3. Dispatch WO-001 (change greeting). Agent must not be told it is Clarion.
4. `make run` in the template; human sees the new heading; PR opens on the **template** repo.
5. Confirm engine live instance still: Keychain still Clarion, a Clarion WO still gets Clarion verify/rebuild (profile or legacy env).

If step 3 still injects Clarion paths or login, I2/I3 are not done.

---

## Suggested order

I5 (strip passwords from public git) → I1 (profile contract) → I2 + I3 (runner) → I4 (PM) → I6 (Clarion yaml) → I7 (stranger test). Merge PR 293 whenever CI is green so docs are on `main` before I7.

## Out of scope (do not do in this program)

- Rewriting Clarion `AGENT_PROCESS.md` or deleting Clarion `docs/blog/`
- `factory.yaml` adapters that change orchestrator **defaults** for the live Clarion-pointed process until I6 exists
- Publishing Clarion WO bodies or `PROGRESS.md`
- Replacing this engine’s live GitHub Actions with the template’s demo CI
