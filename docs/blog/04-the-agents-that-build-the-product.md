# Part 4 — The agents that build the product

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

If you only remember one thing from this post, remember this: **the product is not built by “an AI.”** It is built by a cast with different jobs, different privileges, and different ways to fail.

The implementer you see in the IDE is the actor on stage. Offstage there is a planner who is not allowed to write product code, a reviewer who is not allowed to merge, a fixer who is only allowed two attempts, a visual reviewer who speaks in screenshots, and a row of product agents that will never open a pull request but will one day propose a live-environment change to an operator.

Treating them as one creature is how you either over-trust (the implementer also “reviewed” itself) or under-use (you never let the planner draft, so every spec starts as a chat).

This is the roster.

---

## Layer A — Implementers

These agents write the product. They all read the same law: `AGENT_PROCESS.md`. They enter through different doors so we do not maintain three factories.

| Door | Platform |
|------|----------|
| `CLAUDE.md` | Claude Code (CLI or IDE) |
| `AGENTS.md` | OpenAI Codex |
| `.cursor/rules/agent-process.mdc` (`alwaysApply: true`) | Cursor Agent |

The doors are short and redundant on purpose. They repeat the container rebuild table, the risk-tier merge rules, and the “ask the human before commit” checkpoint so an agent that only skims the first file still cannot skip the dangerous parts.

### Claude Code

Local, on the developer Mac. Docker is up. This is the original factory implementer: claim the WO, work in a worktree, rebuild with `your verify/rebuild command`, stop for human verification, open the PR. It has the full repo, the running stack on localhost, and no excuse for skipping a rebuild.

### Cursor

Same machine, same Docker, same law, different IDE. Cursor’s always-on rule file is how this series is being written. Cursor can also **spawn specialist subagents** (Layer C) without the human opening a second chat: explore the tree, investigate a red CI check, run a security review on the diff. The parent agent still owns the WO. Subagents do not get their own claim files. If they did, the board would lie.

### OpenAI Codex (local)

Same process via `AGENTS.md`. Useful as a second implementer in parallel with Claude or Cursor on a *different* WO — not as a rubber stamp on the same diff. Two models on one branch is how you get a fight over formatting and a lost claim protocol.

### Factory Codex on GitHub Actions

`codex-dispatch.yml` is the remote cousin. A human or the factory orchestrator fires `workflow_dispatch` with a WO id. The job checks out `main`, builds a prompt from the spec markdown plus a quality mandate (tests, no secrets, RBAC on new routes), runs `codex exec`, commits as Factory Codex, and opens a PR.

**Hard limit: no Docker.** This agent cannot rebuild a shared backend service. It cannot click the feature in a browser. It is the right backend for P3 docs and for WOs whose verification is `make ci-local` plus an **After Merge** section that tells a human which containers to bake. It is the wrong backend for “the tab must look right.” Remote agents that pretend they verified UI are how stale frontend images ship.

The factory **agent-runner** (`dentroio/agentic-factory`) makes this a config knob: `PREFERRED_AGENT=claude|cursor|codex|github-codex`. The Work Order does not change. The runner claims, streams checkins, and still requests human sign-off. Dispatch is not unsupervised merge.

### What every implementer is forbidden to do

The “Never” list is the other half of direction. Agents are extremely good at the shortcut that locally “works.”

Never commit code straight to `main`. Never `git add -A`. Never skip `make sync`. Never skip the human checkpoint on P0–P2. Never skip `make ci-local` before the PR. Never mix another WO’s files onto this branch. Never auto-merge on CI green without reading the AI review. Never hardcode secrets. Never `|| true` a failing step. Never `your rebuild command` from inside a worktree (`your verify/rebuild command` builds *this* tree; the other command builds main, and your work is invisible). Never recreate Compose services without `--no-deps` (supporting infra can lose its brains).

Direction is constraints, not vibes.

---

## Layer B — Factory specialists

None of these implement the feature. If they start editing a product source file “to help,” the factory has jumped the rails.

### Planning agent

Issue labeled `new-wo` → draft spec PR. Met in Part 3. Job: turn a paragraph into a Work Order. Privilege: markdown only. Failure mode: silent non-firing (fixed trigger + watchdog).

### AI code reviewer

Every PR to `main`, Claude reads the Python/TS/TSX diff and comments **LGTM**, **Needs attention**, or **Review required**.

It is **advisory at GitHub’s required-check layer** — the workflow exits 0 so a flaky LLM cannot deadlock `main`. Hard blocking of the product scars is the local CI gate and `ci.yml`. Implementers and `pr-watch` still obey the *comment*: Review required means fix the code; Needs attention means think; LGTM means P2 may auto-merge.

Skip conditions exist so we do not pay for noise: Dependabot, commits tagged `[pr-watch-fix]` / `[ai-review-apply]` / `[ci-autofix]`, empty diffs, GitHub “Update branch” merges.

Why a second model on the author’s PR? Because the implementer already had full the product context. A reviewer that is the *same session* will agree with itself. A reviewer that only sees the diff will still miss product truth (that is the human’s job) but it will catch `db.execute` without `commit`, a migration file nobody registered, a new route with no `require_role()`. Those are the bugs that have already reached `main` once.

### AI review applier

When the comment is Needs attention, this workflow applies the Suggestions section as a commit tagged `[ai-review-apply]`. One pass per cycle. It does **not** apply Review required — that needs a real code change from the implementer. Only agent PRs (`agent-pr` label or known bots). Human PRs are reviewed by humans, not auto-patched. Loop guard: if HEAD is already `[ai-review-apply]`, stop. Otherwise you get a polite infinite argument.

### CI auto-fix

CI red on an agent PR → Claude gets logs + diff → minimal search-and-replace. Max two attempts. `[ci-autofix]` loop guard. Structural build failures are not patched; those need a person. This agent exists because implementers fail lint, and waiting for a human to add a missing newline is how a factory dies of boredom.

### Merge advisor

After AI review completes, a synthesizer reads CI, the review verdict, risk tier from the WO spec, and diff risk, then posts one of: **Ready to merge** (with a verify checklist), **Review before merging**, **Do not merge** (with blockers). It never blocks. It is a staff engineer in comment form for the human who still owns P0/P1.

### Multi-agent review chain

In the factory runner, after CI, a *chain* of reviewers can run before `/api/validate`. Different concerns, often different models:

| Concern | Default backend | Blocks on |
|---------|-----------------|-----------|
| Security | Codex | CRITICAL, HIGH |
| Architecture | Claude | CRITICAL |
| Correctness | Claude | CRITICAL, HIGH |
| Performance | Codex | CRITICAL |

P3: no chain. P2: security + correctness. P1: those plus architecture. P0: all four.

The point is adversarial review. What Claude misses, Codex may catch. What both miss, the human still has to see in the UI. CRITICAL findings block factory validate. They do not replace Part 5’s localhost click.

### Dependabot → WO bridge

Failed bump → `new-wo` issue. Part 3. Specialist, not a coder.

### Automation watchdog

Watches planning-agent, the Dependabot bridge, and auto-update-PRs. On repeated consecutive failures, files **one** tracking issue per workflow and closes it when the workflow succeeds again. Built after the planning agent’s zero-run history. Factory agents that nobody watches are not autonomous. They are abandoned.

### Mark-WO-done

PR title contains `WO-NNN` and the PR merges → stamp PLAN, claim file, PROGRESS, spec. Ignores `pm-sync` PRs so the bookkeeping PR cannot retrigger itself. That loop has happened: dozens of “mark WO done” PRs rewriting `pr_url` to point at themselves. Specialists need loop guards too.

### Auto-update PRs

Every push to `main` merges `main` into open `wo/*` branches (and auto-merge / Dependabot PRs). `PROGRESS.md` conflicts take main’s version. Other conflicts wait for the implementer. Uses a PAT so the push counts as human and **re-triggers CI** (GITHUB_TOKEN pushes do not). Without this, P0/P1 branches rot until a human hits “This branch is out of date.”

---

## Layer C — Cursor specialists

The parent Cursor agent can launch subagents. They are not WO owners.

**Explore** — fast search when the spec names a symptom (“click does nothing”) and not a path. Returns a map. The parent still decides.

**Bugbot** — diff review when explicitly asked. Cousin of the GitHub AI reviewer, on the local change, before the PR exists.

**Security Review** — same, security-shaped. Explicit ask only. Not a substitute for P0 human merge.

**CI investigator** — one failing PR check → short root cause. Saves the parent from drowning in a 9-minute log.

**Shell** — isolated commands.

**best-of-n runner** — parallel attempts in isolated git worktrees. Useful for a gnarly algorithm. Dangerous if both winners get committed; the parent must pick.

These specialists are how Cursor is more than “Claude in a different skin.” They are still not allowed to skip the human checkpoint.

---

## Layer D — The human visual loop

### Oryntra / Review Studio

When an agent changes UI, text is a lossy channel. “The button is in the wrong place” is not a spec. Oryntra embeds the product in Review Studio. The human circles, arrows, annotates. MCP tools (`collaborate_now`, `await_review_feedback`, `submit_review_response`) let the IDE agent facilitate without asking the human to paste screenshots into chat.

**Approve & implement** hands a package to the IDE (`handoff_to_ide`). Then the *implementer* (Layer A) does the WO loop: rebuild, smoke, ask again if the change is user-visible.

Oryntra can bind a session to a factory WO (`bind_factory_session`) so annotations land on the right thread, or export an approved change request as a new WO (`export_artifact_to_factory`). Visual review is an origin of work (Part 3) and a verifier of work (Part 5). It is not an implementer.

### Factory Status Site

A small dashboard, typically `http://localhost:8099`, pointed at the GitHub repo. Independent of the product's runtime. WO board, active work (claim files), PR queue, CI health. Without a claim file you see “a branch exists.” With one you see “Cursor — implementing — started 12 minutes ago.” Observability is how a cast of agents does not become a fog.

---

## Layer E — Agents inside the product

These agents do not build the product. They *are* the product, for operators. They belong in this post so nobody finishes the series thinking “agents” meant only Cursor.

**in-product chat** is the chat sidebar. An orchestrator routes by `can_handle()` and priority. Higher priority wins. Conversational is priority 1: the fallback, not the star.

**The AI Harness** runs scheduled jobs: load YAML specs, bound tools, memory, circuit breakers, an approval gateway. Mutating tools do not execute; they queue.

**The rule:** AI proposes; humans approve. No Level 3 “just push the live change.” Level 1 reports. Level 2 waits on `/agents/approvals`.

A short tour — enough to respect them; the full catalog is `your product's agent catalog (if any)` and Part 7.

| Agent | How you meet it | Autonomy |
|-------|-----------------|----------|
| Policy Agent | “Draft a policy that…” | Recommend an intent |
| Intent Advisor | “I want to prevent guests from…” | Translate NL → structured intent |
| CVE Remediation | “CVE-2024-…” | Propose quarantine; queue |
| Policy Advisor | “Why does this policy match this?” | Explain only |
| Identity | An IP or MAC | Timeline across sources |
| Data Quality | “What’s stale?” | Report |
| Grouping Analyst | “Is this cluster coherent?” | Propose split; queue |
| Cross-Cluster Analyst | “This device is in the wrong group” | Propose move/merge; queue |
| Clustering | “Re-run grouping” | Propose; queue |
| Enforcement Advisor | “What’s our posture?” | Advise |
| Network Engineer | “What does the switch show?” | Live SSH/NETCONF — powerful, not fully lab-certified |
| Threat | Chat + schedule | Alerts; high severity queues isolation |
| Policy Compliance | Every 6 hours | Drift vs external rules the product created; queue Critical/High |
| Onboarding | Every 15 minutes | New endpoints vs clusters; ≥70% confidence queues assignment |
| Conversational | Everything else | Wiki RAG + DB tools |
| Compliance | Partial | Framework mapping; not fully in-product chat-routed |
| Traffic Auto-Proposer | Scheduler (off by default) | **Not an LLM** — NetFlow → proposed intents |

External clients (Claude Desktop, etc.) can call a **read-only MCP server** — search endpoints, clusters, topology, docs. No write tools in v1. Every call audit-trailed.

The rhyme with Layer A is the point: coding agents queue a merge behind a human click; product agents queue an enforcement behind an operator click. Same factory instinct. Different blast radius.

---

## How to choose who acts

| Situation | Who |
|-----------|-----|
| Spec exists, UI must be true | Local Claude or Cursor (Docker) |
| Spec exists, docs-only | GitHub Codex or any local agent; skip containers |
| “We should do X” is still a paragraph | Planning agent, then a human |
| PR is open, lint red | CI auto-fix, then implementer if it fails twice |
| PR comment Needs attention | Applier, then implementer if it was a real design issue |
| P0 auth diff | Implementer + human merge; review chain; **no** auto-merge |
| Button looks wrong in the browser | Oryntra annotation → implementer |
| Operator asks “who is 10.1.2.3?” | Identity Agent in in-product chat, not a coding agent |
| Two implementers, one shared registry file | One waits (Part 7) |

The anti-pattern is asking in-product chat to write a migration, or asking Cursor to approve a live-environment push. Wrong layer. Wrong gate.

---

You now know who is in the building. The next post is the path the *implementer* walks when the spec is ready: worktrees, claim files, baking images, and the moment they are required to shut up and ask.

**Next:** [Part 5 — From spec to a running product](05-spec-to-running-product.md)
