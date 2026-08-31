# Part 2 — Anatomy of a Work Order

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

A Work Order that says “the map needs to be fixed” will get you a pull request. It will not get you the pull request you wanted.

Agents are inexpensive to start and expensive to course-correct. They follow the strongest sentence in the file. If that sentence is a half-remembered solution (“add `pointer-events: none`”), they will add it even if the real bug is a D3 drag threshold. If the sentence is a symptom with a file path, a route, and a suspected cause, they will investigate inside a box you defined.

This post is the box.

## What a Work Order is

A Work Order (WO) is a markdown file in the repo, named `WO-NNN-short-slug.md`. It is the complete brief an agent needs to implement one slice of work. A well-formed WO passes the **cold start test**: an agent with zero chat history can read it and implement it correctly without asking clarifying questions.

That test is not a slogan. It is how we decide a spec is ready for dispatch. If you cannot write the WO without sitting next to the implementer, you do not understand the change yet. Write the spec until you do. The time you spend is the design review, moved earlier — which is the only place a design review still helps an agent.

A Work Order is **not**:

- a vibe (“make the map better”)
- a solution smuggled into a problem statement
- a dumping ground for three unrelated fixes
- a substitute for an architecture doc when the work still needs a decision

When the work is large, we write a **program** (a parent document) and split it into several WOs with explicit `Depends on:` edges. Agents implement one WO at a time. Parallelism comes from multiple WOs, not from one agent “also fixing that other thing while it’s here.”

## The sections that matter

Specs in the wild vary — some use Goal / Scope / Approach, some use Problem / What to Build. The information is the same. The canonical template lives in `docs/adopters/WO_SPEC_FORMAT.md`. Here is what each section is *for*, which is more useful than another copy of the template.

### Problem — the symptom, not the fix

**Why this work exists.** What an operator or developer can see. File paths, route names, table names, error messages.

Good:

> The Network Map allows hover-on-device but click-on-device does nothing. The click handler in `InfrastructureMap.tsx` fires (confirmed in the console) but the selected device panel does not open. Likely cause: an overlay absorbing pointer events, or a D3 drag/click conflict.

Bad:

> The map needs to be fixed.

The good version gives the agent a place to put a breakpoint. The bad version gives it permission to rewrite the map.

Keep solutions out of this section. The moment you write “we need `pointer-events: none`” in Problem, you have pre-committed to a fix you have not verified. Put guesses in Problem as *likely causes*. Put the chosen fix in What to Build after you mean it.

### What to Build — enough to implement

Files to create or modify. Function signatures. API contracts (method, path, body, response shape). Schema. Component hierarchy. An agent reading this section should need no extra archaeology.

This is also where you say **how to verify** at a technical level: which service to rebuild, which curl to run, which query parameter the new tab uses (`?view=discovery`).

If you find yourself writing “figure out the right approach,” stop. Either the WO is still a research spike (write that explicitly: read-only, produce a follow-on spec), or you are not ready to dispatch.

### Out of scope — the most underrated section

Name the tempting extras and refuse them. This is how agents stay autonomous without becoming chaotic.

From the real the import UI redesign:

> Source-group attribution per candidate — flagged as a nice-to-have, needs its own join; not attempted here. Any change to how `l7_metadata` itself is populated — out of scope.

During live review the user asked about using the product's discovered subnets instead of private-range. That became the next Work Order. The agent did not “helpfully” expand the diff. Out of scope is what made that possible.

If you skip this section, the agent will treat every adjacent smell as part of the job. You will review a PR that fixes your bug and also rewrites a table you did not ask to touch.

### Acceptance criteria — tests, not vibes

Each criterion must be checkable by a command, a URL, or a visible UI result.

- “The import page is a full-width tab, not a modal.”
- “Multicast and discovery-protocol-noise destinations no longer appear.”
- “`make smoke-test` passes.”
- “`GET /api/v1/endpoints` returns `{data, meta}`.”

“Works correctly” is not a criterion. “Looks good” is not a criterion. Those are feelings. Agents cannot grade feelings, and humans will disagree about them after the fact.

### Execution — the agent’s runbook

This block looks like bureaucracy. It is coordination.

- **Branch:** `wo/NNN-short-name` — the claim visible in `git branch -r`. Two agents do not take the same WO because the branch already exists.
- **Risk tier:** P0–P3 — who verifies, who merges (see below).
- **PR title:** includes `WO-NNN` so merge-time automation can stamp the board complete.
- **Pre-PR gate:** `make ci-local`.
- **Depends on:** another WO number, or none.
- **User verification:** exact clicks at `https://localhost`, or “backend only — here is the curl.”
- **PM docs:** `PROGRESS.md`, capability registry, wiki pages.
- **docs_impact:** which canonical docs and wiki pages update in the *same* PR, and whether marketing needs a log line.

Skip Execution and the next agent invents a branch name, forgets the human checkpoint, and leaves `PROGRESS.md` lying.

## Risk tiers are an autonomy budget

Risk tier answers: how much can the factory decide without a human?

| Tier | Typical work | Human verifies the running system? | Who merges? |
|------|----------------|--------------------------------------|-------------|
| **P0** | Auth, RBAC, secrets, lockout, data leak | Always | Human |
| **P1** | API contracts, schema, migrations, pipelines | Always | Human |
| **P2** | Features, UI, connectors, most fixes | Yes, *then* CI | Auto-merge after CI + AI review LGTM |
| **P3** | Docs and PM tracking only | No | Still a PR (`main` is protected); no Docker |

Decision tree, used as written:

```
Does it touch authentication, authorization, secrets, or user data?
  → P0

Does it change an API contract, DB schema, or behavior operators depend on?
  → P1

Does it add or fix product behavior (UI, routes, connectors)?
  → P2

Is it markdown / PM files only — zero runtime change?
  → P3
```

One line of Python, TypeScript, or SQL makes it at least P2. P3 is not “small.” P3 is “no running service is affected.”

This is the sentence people miss: **P2 auto-merge is not unsupervised shipping.** The human already saw the feature on localhost before the agent was allowed to commit. Auto-merge means “do not make a person click Merge on a UI copy change that CI and the reviewer already passed.” P0 still requires a human on the GitHub button, because green tests do not prove you did not lock everyone out.

Effort (S / M / L / XL) is a dispatch hint, not a contract. S is hours, M is about a day, L is two to three days. XL should almost always be split. An XL Work Order is how you get an agent that is still “almost done” on Friday with a 4,000-line diff nobody can review.

## Status is a protocol, not a mood

| Status | Meaning |
|--------|---------|
| Open | Spec exists on `main`; nobody has claimed it |
| In progress | Claim file on a `wo/NNN-*` branch |
| Complete (dated) | Merged; claim file says `complete` |
| Blocked | Agent stopped; `notes` explain why |
| Abandoned | Stopped without finishing; `notes` required |

The spec file, the claim JSON, `PROGRESS.md`, and `PLAN.json` can drift. They have drifted. Merge-time automation is the backstop. The implementing agent is still supposed to mark complete **in the implementation PR**, because after merge, `main` is protected and you cannot sneak a stamp onto the claim file. Cleanup tooling that looks for `complete` will never see the worktree if you skip it. That is not hypothetical; it is why the rule exists.

## Anti-patterns that produce the wrong PR

| Anti-pattern | What happens | Fix |
|--------------|--------------|-----|
| Vague problem | Agent rewrites a page | Symptom + path + likely cause |
| Solution in Problem | Agent implements your first guess | Problem = symptom; Build = chosen fix |
| Missing paths | Agent “updates the auth middleware” in the wrong file | Name the exact file path |
| Vague AC | Nobody can say done | A command or a URL |
| Missing service tag | Agent does not rebuild; you review stale Docker | `**Services:** frontend` |
| Missing Execution | Invented branch, skipped checkpoint | Always include the block |
| “Depends on the auth WO” | Race | `Depends on: WO-290` |

## A spec that worked

The redesign WO did not say “improve the import UI.” It said the UI was a cramped modal for a page-scale review; that a protocol field was fetched and never shown; that names were built from the first DNS label so `z.example.test` became “Z”; that discovery-protocol noise was offered as real items.

It named the backend filters, the frontend tab pattern (`?view=discovery`), and what not to touch. Acceptance criteria were visible: full-width tab, meaningful names, no discovery-protocol noise, Protocol column, dark mode, `make ci-local`, **live-verified in the browser by the user before commit**.

That last criterion is the series in one line. The spec does not end at “the agent thinks it works.” It ends at a human in the product.

Write specs like that and Part 4’s agents have something to execute. Write specs like “make it better” and you will meet those agents anyway — they will just build the wrong product.

**Next:** [Part 3 — How a Work Order is born](03-how-a-work-order-is-born.md)
