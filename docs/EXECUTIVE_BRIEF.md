# Agentic Engineering Factory — Executive Brief

## What It Is

The Agentic Engineering Factory is an open-source GitHub template that gives software teams a complete, structured system for building products with AI agents. Instead of using an AI assistant to answer questions or write one-off code snippets, teams using the factory have AI agents running the full engineering cycle: turning a problem description into a work specification, writing the code, reviewing it for quality and security issues, deciding when it is safe to merge, capturing lessons for future sessions, and watching production for anomalies. The factory ships as a GitHub repository template — a team creates their own project from it in minutes, fills in a few project-specific details, and the full system is operational.

---

## The Problem It Solves

Software teams adopting AI agents face three compounding problems.

**Engineering velocity is capped by human review bandwidth.** An agent can generate code in seconds, but that code sits in a queue waiting for a human to read it, assess it, and approve it. The faster agents produce output, the more the human review bottleneck dominates.

**Agent work is unstructured without rails.** Agents working without a defined process rediscover the same project constraints in every session, make conflicting changes when multiple agents work in parallel, bypass testing when nothing enforces it, and create PRs that are impossible to review because they lack context. The result is velocity without control.

**The feedback loop is broken.** When CI fails on an agent's PR, nothing automatically tells the agent what broke. When code merges, nothing extracts what was learned. When production degrades, nothing routes the signal back to an implementation queue. Humans end up as the relay between every automated system — which is exactly what automation was supposed to eliminate.

---

## How It Works

- **Work orders define every task.** Before any code is written, a structured specification describes the problem, the acceptance criteria, the risk level, and the exact steps for implementation. AI agents generate these specs from plain-language issue descriptions and open them as pull requests for human review.

- **Risk tiers determine how much autonomy an agent gets.** Security and schema changes always require a human to approve and merge. Routine feature additions and test work auto-merge after CI passes. Documentation commits go directly to the main branch. The system never makes the agent guess how much authority it has.

- **Every PR is reviewed by Claude before it can merge.** An AI reviewer checks every code change for hardcoded secrets, swallowed errors, missing test coverage, SQL injection risk, and project-specific invariants. A "Review required" verdict blocks the merge automatically. This runs on every PR, 24 hours a day, with no human needed for the review step.

- **CI failures route back to the agent automatically.** When automated tests fail on an agent's PR, the system posts the exact failure output as a comment on that PR. The agent reads the comment, fixes the code, pushes, and CI re-runs — no human relay required. For straightforward failures, the system attempts an automatic fix before falling back to the manual loop.

- **Every merge produces a lesson.** After each PR merges, an AI agent reads the diff and extracts anything non-obvious that future agents should know. It writes this as a structured memory file and opens a PR to commit it. The project's memory compounds over time — a project with 50 saved lessons is dramatically easier for agents to work on than a fresh one.

---

## What Teams Get

| Output | How It Happens |
|--------|---------------|
| Work order specs from plain-language issues | Planning agent drafts the spec; human reviews and merges |
| Code reviewed 24/7 against 7 security and quality checks | AI review runs on every PR automatically |
| Autonomous merge for safe changes | P2-tier PRs merge without human touch after CI passes |
| CI failures surfaced directly to the agent | CI failure notifier posts logs as PR comments |
| Automatic CI self-repair | CI auto-fix attempts a patch on agent PRs before escalating |
| Acceptance criteria verified post-merge | Verifier agent checks each criterion against the merged diff |
| Incident issues created from production anomalies | Observability agent polls the health endpoint every 15 minutes |
| Persistent cross-session memory | Memory agent extracts lessons and opens PRs to commit them |
| Synthesized merge recommendations for human reviewers | Merge advisor aggregates all signals into a single ✅ / ⚠️ / ❌ |

---

## Business Value

**Speed.** Routine work — tests, documentation, additive features — ships without a human in the merge path. Human attention concentrates on the changes that actually warrant it: security, schema changes, core architecture.

**Quality.** AI code review runs on every change with no fatigue, no oversight gaps, and consistent criteria. Projects accumulate a growing memory of hard-won lessons that agents consult at the start of every session.

**Cost.** The AI review that protects every PR costs approximately $0.01–$0.05 per PR. The full agent loop — planning, review, memory — costs less than a few dollars per work order. These are fractions of the cost of a single engineering hour.

**Control.** The risk tier model means teams never have to choose between autonomy and safety. High-risk work always has a human in the loop. Safe work ships at agent speed.

---

## Who It Is For

The factory is built for two audiences:

**Startups and small teams building products with AI agents.** They have limited engineering bandwidth and want agents to carry the routine workload — feature additions, tests, documentation, minor fixes — so human engineers focus on architecture and critical decisions.

**Engineering teams that want to adopt AI coding agents responsibly.** They need structure, not just capability. The factory gives them branch policies, review gates, parallel coordination rules, and a memory system — the infrastructure that makes agents trustworthy on a production codebase.

---

## How to Adopt It

The factory is available at [github.com/dentroio/agentic-factory](https://github.com/dentroio/agentic-factory) under the MIT license. To start:

1. Click "Use this template" on GitHub to create your project repository.
2. Open the repository in Claude Code and say: "Read ENGINEER.md and help me set up the factory."
3. The Project Engineer agent walks through configuration — CI, branch protection, AI review context, memory — in 15–20 minutes.

No infrastructure to provision. No new tools to install. The factory runs entirely on GitHub Actions with one external dependency: an Anthropic API key.
