# Part 8 — What actually makes this work

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

Eight posts is a long way to walk for a sentence you could have tweeted: *we use AI to write code.*

That sentence is true and worthless. Lots of teams use AI to write code. Some of them ship. Some of them ship a green PR that restored multicast DNS as a “service.” The difference is not the model. The difference is the box the model is allowed to move in, and the human who still has to look at the box.

This post is the honest capstone: what compounds, what stays human, what still breaks.

## The spec is the product decision

Agents fill in files once the decision is made. They are bad at noticing that the import UI should be a tab rather than a modal unless you write that down. Time on Problem / Out of scope / Acceptance criteria is not overhead. It is the design review, moved to the only moment it still changes the outcome.

The cold start test is a kindness to the next agent and a discipline for the author. If you cannot write the WO without sitting next to the implementer, you are not ready to dispatch. Chat feels like sitting next to them. Chat does not survive the weekend or the second model.

## The same invariants, three times

When an agent forgets `db.commit()`, we want it to fail cheap:

1. **Prose** in `AGENT_PROCESS.md` — every front door points here
2. **Static analysis** in local CI checks — no token bill
3. **Advisory LLM review** on the PR diff — the product-shaped, not generic nits

When (2) has a blind spot — it has; RBAC on `@app` routes in `main.py` used to be invisible — a real incident becomes a Work Order that tightens the checker. The factory improves by encoding the last failure. That is slower than a motivational poster and faster than the third outage.

Gitleaks scanning the whole clone, the planning agent never firing, mark-done rewriting `pr_url` to itself, `GH_PAT` expiring into silence: each is now a comment in a workflow file. Read those comments. They are the series in commit form.

## Humans still own the high-leverage points

| Human | Agent |
|-------|--------|
| Priority, risk tier, “is this even a WO?” | Implementation inside the spec |
| Click through the running UI | Rebuild, lint, tests, PR boilerplate |
| Merge P0/P1 | Auto-merge P2 after that UI check |
| Split a too-big WO; file follow-ons | Stay in scope |
| Write or approve the spec | Draft a spec from an issue (planner only) |
| False-positive vs real review finding | Apply mechanical suggestions |
| Approve a live-environment change | Queue the card |
| Lab-certify Network Engineer | Ship the specialist behind a warning |

The user-verification checkpoint is the load-bearing beam. Remove it and CI will still be green. The product will still lie. Oryntra makes the beam more precise. It does not remove it.

Auto-merge is the most misunderstood line in the series. It is not “the model ships to production.” It is “a person already saw the tab, and we will not make them click Merge on GitHub for a P2.” If you skip Part 5 and keep Part 6’s auto-merge, you have built a pipe from hallucination to `main`.

## Containers force honesty

Because images bake code, “tests passed on the host” is not “the product changed.” Forcing `your verify/rebuild command` + smoke + a human URL makes the factory compatible with a Docker-composed pile of services. A repo that is `npm start` could drop the rebuild. We cannot. Vite is not nginx. Remote Codex cannot pretend otherwise. After Merge is a real step, not a footer.

## Parallelism without a manager

Worktrees, branch-as-claim, shared-file sequencing: several agents on one Mac without a standup to assign files. They require agents *follow* the protocol. A rogue `git checkout -b feature/foo` is invisible. The Status Site will not save you from work you refused to claim.

One Compose stack means runtime is shared even when git is not. Two rebuilds of the same shared service is a lost WO, not a race you can win with optimism.

## A cast, not a god-model

Part 4 exists so you do not ask one creature to plan, implement, review, merge, and enforce.

The planner does not write a product source file. The reviewer does not merge P0. The applier does not interpret Review required. The watchdog does not implement features; it yells when the planner is dead. in-product chat does not open GitHub PRs. Cursor does not push live-environment changes. Oryntra does not skip rebuilds.

Privilege is the product. Confusion of privilege is how “we use agents” becomes a security incident.

## Honest limits

- Specs go stale. Agents implement a WO that no longer matches `main` if nobody rebases. `wo-start` cuts from `origin/main`; auto-update-PRs exist because that is still not enough once the PR is open.
- Claim files and `PLAN.json` drift. Merge-time marking is a backstop.
- AI review is a pattern checker, not a substitute for a human on auth.
- Remote agents cannot rebuild Docker. UX WOs run locally.
- WO number collisions have happened. Check four sources.
- Front doors (`CLAUDE.md`, `AGENTS.md`, Cursor rules) can drift from `AGENT_PROCESS.md`. The process file wins; update the doors in the same change.
- In-product catalog drifts too (priorities, who is actually in-product chat-routed). Trust code over a dated table; file a WO to fix the table.
- Network Engineer can touch live gear and is not fully certified. Status honesty is a feature.
- The factory can look busy (CI running, PRs opening) while a trigger is wrong and no spec is ever drafted. Watchdogs are not optional.

## The loop that compounds

```
Better WO specs
  → the right implementer (local vs cloud) does the right layer of work
    → containers actually change
      → a human sees the truth
        → leftover work becomes the next spec, not a surprise diff
          → CI and local static checks encode the last scar
            → product agents ship as WOs
              → operators get an Approval Queue that rhymes with the merge queue
                → better specs
```

That is not a flywheel slide. It is a Saturday import tab and a Monday onboarding card and a workflow comment that says *we learned this the hard way*.

## What to do on Monday if you are not us

You do not need the product's services to steal the shape:

1. **A unit of intent** the model can cold-start (not a ticket title).
2. **One process file** every IDE points at.
3. **A forbidden list** (scope, secrets, silent `|| true`).
4. **A verification that matches how you actually run** (containers, a staging URL, a device lab — whatever would make “tests passed” a lie).
5. **A human gate on the irreversible step** (merge, deploy, or enforcement).
6. **Specialists with one job** (plan ≠ implement ≠ review ≠ merge).
7. **Loop guards** on anything that commits back to a branch.
8. **A board that only believes claims**, not vibes.

Start with (1) and (5). The rest is how you survive the third agent.

## The last image

An agent rebuilt a container, asked a human to click a tab, and would not commit until the multicast noise was gone. Another agent, on a schedule, will queue a cluster assignment and wait for an operator. A third will comment on a PR and refuse to block `main` if the API is down. A fourth will file an issue because the planner has not run in a week.

None of them is “the AI that builds the product.”

The Work Order is. The process file is. The human who looked at localhost is.

That is the series.

**Start again:** [Intro](00-intro.md) · [Part 1 — Why we build with Work Orders](01-why-work-orders.md) · [Series index](README.md)
