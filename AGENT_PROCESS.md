# Agent Process — {{PROJECT_NAME}}

> **Version:** 1.0  
> **Template source:** [dentroio/agentic-factory](https://github.com/dentroio/agentic-factory)  
> **This file is the single source of truth for all agents working on this repository.**

All agents (Claude Code, Cursor, Codex, custom runners) MUST read this document before starting any implementation task.

---

## §1 Risk Tiers & Merge Authority

Every work order (WO) is assigned a risk tier that determines who can merge.

| Tier | Scope | Branch Required | Merge Authority |
|------|-------|-----------------|-----------------|
| **P0** | Auth, security, multi-tenant data isolation, breaking API contracts | Yes (`fix/` or `wo/`) | **Human must approve and merge — no exceptions** |
| **P1** | DB schema migrations, new API routes, cross-service interfaces | Yes (`wo/`) | **Human must approve and merge** |
| **P2** | Feature additions, UI changes, new tests, refactors | Yes (`wo/`) | Auto-merge after CI passes (`gh pr merge --auto --squash`) |
| **P3** | Docs, PM files, comments, typos | No — commit directly to `main` | Direct push to main |

**Hotfix track:** For urgent bug fixes that don't need a full WO spec, use a `fix/` branch. See §5.

---

## §2 Work Order Execution Flow

Every non-trivial task starts as a Work Order (WO) spec in `docs/project_management/work_orders/`.

```
1. Read the WO spec — especially the ## Execution section
2. Read ## Development Environment (below) — know where the app runs before writing code
3. Create the branch:  git checkout -b wo/NNN-short-description
4. Implement the work
5. Deploy and verify (see §2a)
6. Run the local CI gate: make ci-local  (must pass before pushing)
7. Sync with main before opening the PR:
     git pull --rebase origin main
   If rebase conflicts: git rebase --abort && git merge origin/main --no-edit
8. Open the PR with a UI Verification section (see §4 template)
9. P2: queue auto-merge:  gh pr merge --auto --squash
   P0/P1: notify the human and wait
10. Update PM docs: PROGRESS.md, CAPABILITY_STATUS.md
```

Never push directly to `main` for P0/P1/P2 work.

---

## §2a Deploy and Verify

**This step differs depending on the project's deployment model. Read `## Development Environment` to know which applies.**

### Local Docker projects (no CD)

After implementing, rebuild every backend service you changed and confirm the feature works before running `make ci-local` or opening a PR.

```bash
# Auto-detect changed services, rebuild + redeploy, wait for healthy
make deploy-changed

# Or rebuild one service manually
make build-svc SVC=<service-name>
make wait-healthy
```

Then verify the specific feature: new API endpoint with `curl`, new migration with a `psql` column check, service startup with `make logs-svc`.

For **frontend changes**: if the project uses a dev server (Vite, Next.js dev), changes are live instantly — no rebuild needed. Open the browser and confirm.

**If you are a remote agent** (running on cloud infrastructure, not on the developer's machine): you cannot run `docker compose` or reach `localhost`. Stop at `make ci-local`. In the PR body, write explicit numbered UI Verification steps so the developer can test manually.

### CD-based projects

After merging to main, `deploy.yml` deploys to staging automatically. Verify features at the staging URL listed in `## Development Environment`. Do not attempt to verify against localhost — there is no local deployment.

### UI Verification (required for every PR)

Whether local Docker or CD, every PR must include a `## UI Verification` section in its body (see §4 PR template). This is how the human reviewer knows what to click in the browser to confirm the feature works.

If the WO has no frontend impact, write: `No UI changes — backend / API only.`

---

## §3 Local CI Gate (run before every PR)

```bash
make ci-local
```

This mirrors the PR gate exactly. A PR that fails CI will not merge. Do not open a PR without running this first.

The `ci-local` target should include:
- Lint (language-appropriate formatter + linter)
- Unit tests
- Type check (if applicable)
- Build check

---

## §4 Work Order Spec Format

Every WO spec lives at `docs/project_management/work_orders/WO-NNN-slug.md` and includes:

```markdown
# WO-NNN: Title

**Status:** 📋 Open | 🔄 In Progress | ✅ Complete (YYYY-MM-DD)
**Priority:** P0 | P1 | P2 | P3
**Effort:** ~Xh

## Background
Why this work is needed.

## What Needs to Happen
Specific, actionable steps.

## Acceptance Criteria
Numbered, machine-checkable conditions for done.

## Testing
| Check | How |

## Execution
- **Branch:** `wo/NNN-slug`
- **Risk tier:** P2 — auto-merge after CI passes
- **PR title:** `feat(...): WO-NNN — Title`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** none | WO-NNN
- **PM docs to update:** PROGRESS.md row, CAPABILITY_STATUS.md section

### UI Verification
1. Open {{APP_URL}} — log in as {{TEST_USER}}
2. Navigate to {{exact menu path}}
3. {{Specific action: click X, fill in Y, save}}
4. Expected: {{exact result — label, badge, row in table}}
5. Confirm no errors in browser DevTools console

(Replace with "No UI changes — backend / API only." for backend-only WOs.)
```

The `## Execution` section is what allows any agent to pick up a WO cold without asking questions. The `### UI Verification` subsection is what the developer (or QA) follows in the browser to confirm the feature works — write it before implementation so the acceptance target is clear.

### PR body template

Every PR must use this body structure:

```markdown
## Summary
- What changed and why

## Work Order
WO-NNN — [title](docs/project_management/work_orders/WO-NNN-slug.md)

## Migrations
- [ ] No new migration files  (or: migration added, registered, uses IF NOT EXISTS guards)

## Test plan
- [ ] make ci-local passes
- [ ] Relevant unit tests pass or were added

## UI Verification
1. Open {{APP_URL}} — log in as {{TEST_USER}}
2. Navigate to {{exact page}}
3. {{Action}}
4. Expected: {{exact result}}
5. Confirm no errors in browser DevTools console

(Replace with "No UI changes — backend / API only." if no frontend impact.)

🤖 Generated with [Claude Code / Cursor / Codex]
```

---

## §5 Hotfix Track

For urgent fixes that don't have a WO spec:

1. Branch from main: `git checkout -b fix/short-description`
2. Fix the issue
3. Run `make ci-local`
4. Open PR with this body template:
   ```
   ## Problem
   What is broken and how it was detected.

   ## Fix
   What was changed and why.

   ## Verification
   How to confirm the fix works.
   ```
5. Apply the risk tier from §1 — P0/P1 hotfixes still require human merge.

---

## §6 Parallel Agent Coordination

When multiple agents work simultaneously:

- **One agent per service** — if two agents touch the same service, they will conflict. Branch existence = claimed.
- **Shared files are sequential, not parallel** — files touched by every WO must be edited one at a time:
  - Migration runner / adapter registration file
  - API route registry
  - `PROGRESS.md` and other PM docs
  - `Makefile`
- **Safe to parallelize:** independent services, independent test files, independent WO specs
- **Check before starting:** `git branch -r | grep wo/` — if a branch exists for your service, wait or coordinate.

---

## §7 Branch Naming

| Type | Pattern | Example |
|------|---------|---------|
| Work Order | `wo/NNN-short-description` | `wo/243-expand-python-tests` |
| Hotfix | `fix/short-description` | `fix/auth-token-refresh` |
| Feature (no WO) | `feat/short-description` | `feat/dark-mode-toggle` |

---

## §8 Commit Message Format

```
type(scope): WO-NNN — Short description

Optional longer body explaining the why.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`

---

## §9 GitHub Actions (CI Pipeline)

Every PR runs these jobs. All must pass before merge:

| Job | What it checks |
|-----|---------------|
| lint | Formatter + linter (project-specific) |
| test | Unit test suite |
| build | Build/compile check |
| migration-check | Schema migration registry is consistent |
| ai-review | Claude code review — exits 1 on "Review required" verdict |

After the AI review completes, the **Merge Advisor** (`merge-advisor.yml`) posts a synthesized recommendation comment on every P0/P1 PR. It is always the last comment before a human reviewer looks at the PR.

### How to read the merge advisory

The merge advisor gives you one of three recommendations:

| Recommendation | Meaning |
|---------------|---------|
| ✅ **Ready to merge** | All signals green, checklist is short — safe to merge after a quick scan |
| ⚠️ **Review before merging** | Warnings exist (e.g. thin test coverage, shared file touched) — check the listed items before merging |
| ❌ **Do not merge** | A blocking signal found (CI failure, "Review required" from AI, unmet AC) — do not merge until resolved |

The advisory also gives you:
- **Signal summary table** — CI, AI review, verifier, schema changes, auth changes, test coverage at a glance
- **What to verify** — 2–5 specific things to check by hand (named files, endpoints, tables)
- **If this breaks production** — exact rollback commands for this specific change

The merge advisor never blocks the merge itself — that is the job of the required status checks. It is decision support, not a gate.

---

## §10 Critical Code Patterns

> **Replace this section with project-specific invariants that agents must know.**
> Examples from a FastAPI + PostgreSQL project:

- Always `db.commit()` after every write — `execute()` does NOT auto-commit
- Every new migration file must be registered in the migration runner — there is NO auto-discovery
- Every new API route must have an authorization dependency
- After any backend code change: rebuild the service image (`docker compose build <svc>`)

---

## §11 Never Do

- Never force-push to `main`
- Never skip the CI gate (`--no-verify`, commenting out tests, etc.)
- Never commit secrets, credentials, or `.env` files
- Never modify a shared file (migration runner, route registry) on two branches simultaneously
- Never mark a WO complete without updating `PROGRESS.md`
- Never merge a P0/P1 PR without human review, even if CI passes
