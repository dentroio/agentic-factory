# Building with Agents and Work Orders — Blog Series

**Last Updated:** 2026-08-30
**Status:** Authoritative source copy for a 9-piece public series (intro + 8 parts)
**Distribution:** Public
**Canonical Reference:** `AGENT_PROCESS.md` (what agents execute). These posts are the story.

This directory is the **public, sanitized** blog-ready series (copied from a private product’s internal essays, then generalized). Each file is a complete essay, not an outline. Publish in order, **starting with the intro**. When adapting for a public audience, follow [Publishing notes](#publishing-notes) at the bottom.

A second copy ships in [dentroio/agentic-factory-template](https://github.com/dentroio/agentic-factory-template/tree/main/docs/blog).

Consumers should follow `docs/adopters/PROCESS.md` (or a copy as `AGENT_PROCESS.md` in their repo). This engine repo still uses root `AGENT_PROCESS.md` for factory development. Do not paste that file into a blog; it is a runbook. These posts are why the runbook exists.

| # | Post | File | Captures |
|---|------|------|----------|
| 0 | Intro — How we are building the product with agents | [`00-intro.md`](00-intro.md) | High-level product backdrop; development direction; who the series is for |
| 1 | Why we build with Work Orders | [`01-why-work-orders.md`](01-why-work-orders.md) | The constraint (Docker-baked code), the unit of intent, two factories |
| 2 | Anatomy of a Work Order | [`02-anatomy-of-a-work-order.md`](02-anatomy-of-a-work-order.md) | Spec structure, cold-start test, risk tiers, out of scope |
| 3 | How a Work Order is born | [`03-how-a-work-order-is-born.md`](03-how-a-work-order-is-born.md) | Humans, planning agent, Dependabot bridge, the queue |
| 4 | The agents that build the product | [`04-the-agents-that-build-the-product.md`](04-the-agents-that-build-the-product.md) | **Full roster:** implementers, factory specialists, Cursor specialists, visual review, product agents |
| 5 | From spec to a running product | [`05-spec-to-running-product.md`](05-spec-to-running-product.md) | Worktrees, claim files, rebuild, the human checkpoint |
| 6 | GitHub, CI, and who is allowed to merge | [`06-github-ci-and-the-gate.md`](06-github-ci-and-the-gate.md) | PR Gate, review/fix/advise loop, pr-watch, merge authority |
| 7 | Many agents, one repo | [`07-many-agents-one-repo.md`](07-many-agents-one-repo.md) | Parallel coding agents; the agents *inside* the product |
| 8 | What actually makes this work | [`08-what-makes-this-work.md`](08-what-makes-this-work.md) | Invariants encoded three times, honest limits, the compounding loop |

**Through-line story** used across the series: the import UI (the first fix WO made the import list non-empty; the redesign WO redesigned the page and cleaned candidate quality; the follow-on WO was filed from a question during review rather than stuffing more into the redesign). Use it. Readers follow a character better than they follow a process diagram.

---

## The full agent roster (quick map)

Part 4 is the essay. This table is the index so a writer never omits a name.

### Layer A — Implementers (write product code)

| Agent | Where it runs | Superpower | Hard limit |
|-------|---------------|------------|------------|
| **Claude Code** | Developer Mac (CLI / IDE) | Full the product context, Docker, `AGENT_PROCESS.md` via `CLAUDE.md` | Must ask a human before commit |
| **Cursor** | Developer Mac (Agent mode) | Same process via `.cursor/rules/`; can spawn specialist subagents | Same human checkpoint |
| **OpenAI Codex** | Developer Mac | Same process via `AGENTS.md` | Same |
| **Factory Codex (GitHub Actions)** | `codex-dispatch.yml` in the cloud | Fire-and-forget on a WO spec; no laptop | **No Docker.** Cannot prove the running product. After-merge rebuild required |

A pluggable **agent-runner** (`dentroio/agentic-factory`) can dispatch any of Claude / Cursor / Codex / `github-codex` from `PREFERRED_AGENT`. The WO spec does not change when the backend does.

### Layer B — Factory specialists (do not implement the feature)

| Agent | Trigger | Job |
|-------|---------|-----|
| **Planning agent** | GitHub issue labeled `new-wo` | Draft a WO spec PR. Human edits risk tier and AC. Never writes product code. |
| **AI code reviewer** | Every PR to `main` | Claude reads the diff against the product-specific patterns. Advisory comment: LGTM / Needs attention / Review required. |
| **AI review applier** | Review = “Needs attention” on an agent PR | Applies mechanical suggestions; one pass; commit tagged `[ai-review-apply]` |
| **CI auto-fix** | CI red on an agent PR | Claude patches from logs + diff; max 2 attempts; `[ci-autofix]` |
| **Merge advisor** | After AI review completes | Synthesizes CI + review + risk tier into Ready / Review / Do not merge. Never blocks. |
| **Multi-agent review chain** | Factory quality gate (P2–P0) | Different models for security / architecture / correctness / performance. CRITICAL findings block factory validate. |
| **Dependabot → WO bridge** | Dependabot PR whose CI failed | Opens a `new-wo` issue instead of merging a breaking bump |
| **Automation watchdog** | Factory workflows fail repeatedly | Files a tracking issue so silent breakage cannot hide for weeks |
| **Mark-WO-done** | PR with `WO-NNN` in the title merges | Stamps PLAN / claim / PROGRESS / spec complete |
| **Auto-update PRs** | Every push to `main` | Merges `main` into open `wo/*` branches so they do not rot |

### Layer C — Cursor specialists (called by the implementing agent)

| Subagent | Job |
|----------|-----|
| **Explore** | Fast codebase search when the WO names a symptom, not a file |
| **Bugbot** | Review of local diffs when explicitly asked |
| **Security Review** | Security pass on local diffs when explicitly asked |
| **CI investigator** | One failing PR check → root-cause summary |
| **Shell** | Isolated command execution |
| **best-of-n runner** | Parallel attempts in isolated git worktrees |

### Layer D — Human visual loop

| Tool | Job |
|------|-----|
| **Oryntra / Review Studio** | Browser review of the live UI; annotations (circles, notes) become change requests; Approve & implement hands a package back to the IDE agent |
| **Factory Status Site** | Kanban of WOs, active agents, PR queue, CI health (`localhost:8099`) |

### Layer E — Agents inside the product (the product)

Operators talk to **in-product chat**. Scheduled jobs talk to the **AI Harness**. Nothing mutating runs without the **Approval Queue**. Full tour: Part 7. Catalog: `your product's agent catalog (if any)`.

Chat specialists include Policy, CVE Remediation, Cross-Cluster Analyst, Grouping Analyst, Policy Advisor, Data Quality, Identity, Intent Advisor, Threat, Clustering, Enforcement Advisor, Network Engineer, Conversational fallback, Compliance (partial). Scheduled: Policy Compliance, Onboarding, Threat. Deterministic (not LLM): Traffic Auto-Proposer.

---

## Publishing notes

Safe to keep in public posts: the process, risk tiers, human checkpoint, Docker-baked-code constraint, the idea of claim files and worktrees, the rhyme between factory and in-product approval queues.

Strip or generalize: open WO numbers, unshipped dates, known-bug specifics, repo secrets (`ANTHROPIC_API_KEY`, `GH_PAT`), the local admin password, internal hostnames.

Completed, merged examples (the import UI) are the preferred illustrations.

Each post ends with a one-line hook to the next. Keep those when publishing as a series; drop them if a post is ever reused standalone.
