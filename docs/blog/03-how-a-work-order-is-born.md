# Part 3 — How a Work Order is born

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

Work Orders do not spawn from a backlog tool. They are created in git. Usually a human writes them. Sometimes a planning agent drafts them from a GitHub issue. Always a human owns priority, risk tier, and acceptance criteria — the three fields that decide whether the factory is allowed to auto-merge.

If an agent writes its own P0 acceptance criteria, it is grading its own exam. We do not do that.

This post is about where specs come from, and about the specialist agents that create work *without implementing it*.

## Path 1 — A human saw the product lie

The most common origin is the least glamorous: someone uses the product.

the first fix WO widened a lookback window so “Import Found Services” was no longer empty. Once the list populated, the same person could see the real problems: cramped modal, useless names, discovery-protocol junk. That observation became the redesign WO — written as a spec, not as “please fix discovery” in a chat. The chat is how you *notice*. The spec is how you *dispatch*.

Audits work the same way. A canvas or a hardening review produces a numbered sequence. Each finding becomes a WO with the problem copied from the audit, not reinvented by the implementer. Identity Quality Loop, Policy Workflow-First, Enforce spine — programs of WOs, each small enough to cold-start.

The rule when an implementing agent finds extra work: **do not expand this WO.** Finish, or stash. File a follow-on. Follow-ons keep git history and CI blame clean. They also keep the human’s verification steps honest. You cannot ask someone to “confirm the tab” if the PR also rewrote classification.

## Path 2 — The planning agent (issue → draft spec)

GitHub Actions workflow `planning-agent.yml` watches for issues labeled `new-wo`. When that label appears — including issues opened with the label already attached, which GitHub does *not* fire as a separate `labeled` event — the workflow:

1. Computes the next WO number from existing spec filenames.
2. Runs `scripts/planning_agent.py` with the issue title and body (Claude, same family as the reviewer, different job).
3. Opens a pull request that **only** adds the drafted markdown.

The planning agent is instructed to produce Problem, Goal, Scope, Approach, Acceptance Criteria, Verification Steps, and Execution. It does **not** implement code. A human adjusts risk tier and AC, then merges the spec PR. Only then is the WO eligible for an implementation agent.

This split is load-bearing. Drafting and implementing in one session is how you get a spec that describes whatever the model already decided to build. The planning agent exists so that “we should do X” can become a reviewed artifact *before* anyone touches `services/`.

It also failed silently once. For a stretch of calendar, the workflow had never fired — the `labeled`-only trigger missed issues created with the label in one API call. Two Dependabot-bridge issues sat orphaned. That is why the **automation watchdog** exists (you will meet it again in Part 6): unattended factory agents can die with nobody watching. Green and red look identical on a dashboard you do not open.

## Path 3 — Dependabot as an accidental product manager

Simple dependency bumps that pass CI merge like any other PR. When Dependabot opens a bump **and CI fails**, `dependabot-wo-bridge.yml` treats it as a breaking change:

```
Dependabot PR → CI red
  → workflow opens a GitHub issue with `new-wo`
  → planning agent drafts a WO spec
  → human reviews the spec
  → implementation agent does the real migration
```

The alternative is merging a red Dependabot PR, or asking an implementer to “fix CI” with no spec. That is how breaking upgrades land without a migration plan. The bridge is not intelligent in the LLM sense. It is a specialist with one job: **do not let a failed bump pretend to be a version bump.**

## Path 4 — The factory queue

`docs/factory/PLAN.json` is the dispatch board: WO number, title, phase (`now` / `backlog`), priority, effort, dependencies, pin flag, status. Humans control phase, priority, effort, and pin. Status is synced from spec files, claim files, and PR state.

An **agent-runner** in the separate `agentic-factory` repo can poll this queue, claim the next WO, and invoke Claude, Cursor, Codex, or GitHub-hosted Codex depending on `PREFERRED_AGENT`. The spec does not change when the backend does. That is the point of Part 2’s Execution block: it is backend-agnostic.

**Number allocation is an operational hazard.** WO numbers have been reused because the factory, the `work_orders/` directory, claim files, and commit history can disagree. Allocate the next number by checking all four. The planning agent’s “highest filename + 1” is necessary and not sufficient. A collision is not a cute oops; it is two agents who think they own the same identity.

## Path 5 — Docs impact, decided at birth

Every implementation WO is supposed to declare what documentation rides in the same PR:

```yaml
docs_impact:
  wiki:
    - wiki/docs/operator/secure/groups.md
  canonical_docs:
    - docs/design/IDENTITY_AND_CORRELATION_ARCHITECTURE.md
  marketing_log: true
```

If `marketing_log` is true, the agent appends `docs/MARKETING_UPDATE_LOG.md` so investor decks and demo scripts do not lag the product by a quarter. Wiki pages get `last_verified` and `covers_wos`. This is unglamorous and it is how operator docs stay coupled to the code that invalidated them.

## Who is allowed to create work?

| Creator | May write | May not decide alone |
|---------|-----------|----------------------|
| Human (engineer, reviewer, audit) | Entire spec | — |
| Planning agent | Draft spec | Risk tier, AC, merge |
| Dependabot bridge | An issue | The WO itself |
| Implementing agent | A *follow-on* spec for leftover work | Expanding the current WO |
| Oryntra / Review Studio | Change requests from UI annotation | Dispatch without a human Approve |

Oryntra belongs in the next post as a visual agent, but it belongs here as an origin story: a circle on a screenshot is a better problem statement than “the button is wrong,” and it still becomes a Work Order or a change request **after** a human approves. The factory is allowed to draft. It is not allowed to invent priority.

## The leftover is a feature

the redesign WO’s spec listed out-of-scope items on purpose. Live testing then found more candidate-quality bugs (public destinations, DNS query names leaking in as hostnames, mangled titles). Those stayed in the redesign WO because they were the same concern. The subnet-classifier idea did *not*. It was filed as the follow-on WO.

That distinction — **same concern vs. new design** — is the human job at birth and during review. Agents are bad at it. They will happily keep going. The spec, and the person who refuses to grow it, are how a Saturday night remains one PR.

A Work Order that exists is not yet work. Someone has to execute it — and “someone” is not one model. The next post is the cast: every agent that touches the product, including the ones that never write a feature.

**Next:** [Part 4 — The agents that build the product](04-the-agents-that-build-the-product.md)
