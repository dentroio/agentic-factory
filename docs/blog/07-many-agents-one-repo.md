# Part 7 — Many agents, one repo

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

One implementer, one Work Order, one worktree: Part 5. Reality is Saturday with three WOs in flight, one shared PostgreSQL, and an operator who will open in-product chat on Monday and ask who `10.20.30.40` is.

This post is coordination — coding agents who must not share a checkout or a migration file — and then the other swarm: the agents *inside* the product, who must not share an enforcement action without a person.

If those two swarms feel like different products, the series has failed. They are the same instinct at two blast radii.

## Worktrees: parallelism is git-shaped

Without worktrees, Agent A’s `git checkout wo/200-…` rips Agent B off `wo/100-…`. With them:

```
repo root (usually on main)
└── .worktrees/          (gitignored)
    ├── wo-100-auth-fix/
    ├── wo-200-new-widget/
    └── wo-529-service-discovery-redesign/
```

`make wo-list` shows them. `make wo-clean` force-removes a dead one. `make wt-clean` removes worktrees whose claim file says `complete`. `make sync` dry-runs stale detection so they do not accumulate like motel keys.

Coordination is not a Slack message. It is:

1. Spec on `main` (the work is defined)
2. Branch `wo/NNN-*` on origin (the work is claimed)
3. Claim JSON (who, which step)
4. PR title contains `WO-NNN`
5. After merge, claim + spec + PLAN + PROGRESS all say complete

Skip a layer and the next agent or the next cleanup script does the wrong thing. That is why the claim is the *first* commit, not a sticky note at the end.

## One stack, sequential shared files

One shared runtime. Different services in different WOs can rebuild in parallel. Two WOs that both touch the same shared package must stagger deploys or the second image wins and the first human is clicking a ghost.

Always one agent at a time:

- The migration registry
- The API gateway route table
- Shared PM trackers (`PROGRESS.md`, capability registry)

P3 docs WOs touch no services. Run as many as you want.

A practical check before starting:

```bash
git fetch origin
git branch -r | grep wo/ | while read b; do
  git diff --name-only origin/main...$b 2>/dev/null | grep -q "^src/" && echo "touches src/: $b"
done
```

Cursor’s **best-of-n** subagent runs extra worktrees on purpose. The parent still merges one winner. Two winners on one WO is not parallelism. It is a fork you will squash by hand.

Factory Codex in GitHub Actions does not get a Mac worktree. It gets a cloud checkout. It still must not pick a WO whose branch exists. The orchestrator’s claim API and `wo-start`’s “branch exists on origin” guard are the same rule in two buildings.

## The Status Site is not decoration

`localhost:8099` (or wherever you pointed `agentic-factory`) is how a cast remains a cast instead of a fog. WO board, active work, PR queue, CI health. Data: GitHub + spec files + claim JSON.

If the board is empty, you do not have zero work. You have agents who skipped Step 2 of Part 5.

## The other swarm — agents inside the product

Monday. An operator does not open a worktree. They open in-product chat.

A message hits `POST /api/ai/chat`. The orchestrator asks every specialist `can_handle()`. Highest priority that says yes, wins. Policy Agent sits at 100 so “draft a policy” never falls through to the chatbot. Conversational sits at 1 so *something* answers. Several agents still share priority 5; ties are registration order. That is a known scar, not a design flex.

The specialist may call tools: read data, search docs, retrieve its own memory. If it wants a **mutating** action against a live system, the tool registry does not do it. The approval gateway queues a card: agent, trigger, finding, proposed action, evidence, confidence. Approve executes and writes an audit row. Reject records a reason. Defer waits.

That card is Part 5’s “please click the running UI” wearing an operator’s badge.

### Scheduled, no one asked

Three jobs run because the network does not wait for a question.

**Onboarding** (every 15 minutes) finds endpoints that are not in a cluster, scores them, and queues assignments at ≥70% confidence. Medium confidence notifies. Low confidence stays quiet. Memory keeps it from nagging the same MAC forever.

**Policy Compliance** (every 6 hours) looks at external rules *the product created* and asks whether a human edited them out from under the intent. Critical/High drift becomes a remediation proposal, not a silent re-push.

**Threat** watches behavior — volume spikes, new destinations, odd auth — and queues isolation only when severity earns it.

A fourth cousin is not an LLM at all: **Traffic Auto-Proposer** turns NetFlow into `policy_intents` with `status=proposed`. Off by default. Deterministic analytics. Operators confuse it with Policy Agent; the catalog exists so we do not. Provenance badges exist for the same reason.

### Circuit breakers and memory

The harness is not a prompt in a cron. Per-agent memory in PostgreSQL, TTL, UPSERT. Circuit breakers that open after repeated failure so a wedged scheduled agent does not hammer an external control plane. Autonomy settings: observe / manual / auto_approve — and auto_approve is still bounded by policy, not “YOLO live change.” We do not run Level 3.

### MCP: the product as a tool for *other* AIs

Claude Desktop can call read-only tools: search endpoints, identity timeline, clusters, topology, posture, attack paths, docs, even “ask in-product chat.” No writes in v1. Audit on every call. The product is allowed to be a tool. It is not allowed to be a confused deputy.

### Network Engineer, with a warning

The Network Engineer agent can SSH/NETCONF/SNMP a live device. It is large. It is not fully lab-certified. Shipping a specialist that can touch production gear before the factory’s own “verify on localhost” instinct has been applied to *that* agent would be irony we do not need. The catalog marks it. Honest status is part of the factory.

### in-product chat is not Cursor

Wrong layer, from Part 4:

| Ask | Who |
|-----|-----|
| Who is this IP? | Identity Agent |
| Draft a deny from guests to servers | Policy Agent → human in Policy Builder |
| Quarantine a CVE-exposed cluster | CVE agent → Approval Queue |
| Add an import tab | Work Order → Cursor/Claude → PR Gate |
| Circle a misaligned badge | Oryntra → implementer |

If you prompt in-product chat to open a GitHub PR, you are using the product as an IDE. If you prompt Cursor to push a live-environment change, you are using the IDE as an enforcement plane. Both will sometimes “work.” Both skip the gate built for that blast radius.

## How the two swarms train each other

Every in-product agent was itself a Work Order. Dimension 1 ships Dimension 2. The AI reviewer can check that a new agent follows the product’s agent-adding guide. The Onboarding Agent classifies endpoints the way a new WO classifies work: evidence, confidence, human approval. Policy Compliance enforces design invariants at runtime the way local CI checks enforce them at commit time.

That is the compounding loop Part 8 will name. You cannot see it until you have seen both swarms in one Saturday-to-Monday story:

Saturday: three worktrees, one shared-file lock, a human on the running UI.  
Monday: in-product chat, an onboarding card, an operator who was not in the git log.

Same factory. Different door.

**Next:** [Part 8 — What actually makes this work](08-what-makes-this-work.md)
