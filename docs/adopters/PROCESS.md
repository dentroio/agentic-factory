# PROCESS.md — generic agent process

A product-agnostic cheatsheet for coding agents. Copy into a consumer repo as `AGENT_PROCESS.md` (or keep this file and point `CLAUDE.md` / `AGENTS.md` / Cursor rules at it).

This is **not** a rewrite of this repository’s root `AGENT_PROCESS.md`. Factory development continues to use the root file. Consumers use this (or the copy in the template repo).

---

## Risk tiers

| Tier | Typical work | Human verifies the running product? | Who merges? |
|------|----------------|--------------------------------------|-------------|
| **P0** | Auth, secrets, anything that can leak or lock out | Always | Human |
| **P1** | API contracts, schema, migrations | Always | Human |
| **P2** | Features, UI, most fixes | Yes, then CI | Auto-merge after CI + review LGTM |
| **P3** | Docs / PM markdown only | No | PR required on protected `main` |

One line of application code makes it at least P2. P3 is “no running service is affected.”

Dispatch-ready WOs use the canonical shape in [WO_SPEC_FORMAT.md](WO_SPEC_FORMAT.md): `Problem`, `What to Build`, `Out of scope` or `Do NOT change`, `Acceptance Criteria`, and `Execution`, plus `Priority`, `Effort`, `Services`, and dependencies. Narrative headings in drafts are fine, but normalize them before dispatch.

---

## Work Order flow (P0–P2)

1. Sync `main`.
2. Branch `wo/NNN-short-slug` (worktrees recommended if several agents share a machine).
3. **First commit:** claim file `docs/factory/runs/WO-NNN.json` — then push so the factory board can see the claim.
4. Implement only what the spec lists.
5. Run **your** verify command (tests, staging URL, container rebuild — whatever makes “the file changed” mean “the product changed”).
6. **Stop.** Ask a human to confirm the running product. Do not commit until they do.
7. Local CI gate (`make ci-local` or the equivalent in the consumer repo).
8. Stage **explicit paths** — never `git add -A`.
9. Open a PR whose title contains `WO-NNN`.
10. P2: auto-merge after CI + AI review LGTM. P0/P1: human merges.

P3: PR still required on protected `main`; skip the human product checkpoint.

---

## Claim file (mandatory first commit)

See [CLAIM_SCHEMA.md](CLAIM_SCHEMA.md). Commit message: `docs(factory): claim WO-NNN`.

---

## Never

- Never commit application code straight to `main`.
- Never `git add -A` or `git add .`.
- Never skip the human checkpoint on P0–P2.
- Never skip the local CI gate before opening a PR.
- Never mix another WO’s files onto this branch.
- Never auto-merge on CI green alone if an AI review comment has not posted yet.
- Never hardcode secrets.
- Never `|| true` a step that must be allowed to fail the job.

---

## Hotfix (no WO spec)

Unplanned breakage: `fix/short-description`, push immediately (the claim), fix, CI, PR. Risk tier still applies.
