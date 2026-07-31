# Agentic Engineering Factory

A template for building software with AI agents — human-in-the-loop where it matters, autonomous where it's safe.

Extracted from an active development project. Still evolving.

**Full documentation lives in the [wiki](docs/wiki/Home.md).** This README is a quick orientation, not the manual.

---

## Live Dashboard + Runtime Stack

The factory ships Docker services that run alongside your project:

| Service | Port | Profile | Purpose |
|---------|------|---------|---------|
| `factory-status` | 8099 | default | Web dashboard — Overview, PM, Engineering, Plan Authoring, Threads, Settings |
| `orchestrator` | 8100 (localhost only) | default | Dispatch REST API, WO lifecycle, thread storage, hold/unhold queue |
| `vault` | 8201 (localhost only) | default | HashiCorp Vault — encrypted secrets storage; auto-inits and unseals on start |
| `pr-watchdog` | — | default | Tracks every open PR: CI state, stale detection, merge eligibility |
| `agent-runner` | host | optional | Autonomous WO executor — subscription CLI backends (Claude, Cursor, Codex, Gemini); draft server on port 8101 |

**Start it (macOS — uses Keychain for secrets):**

```bash
make agent-setup              # one-time: stores GitHub token, repo, and API keys in macOS Keychain
make up                       # reads Keychain → starts Docker services
open http://localhost:8099
```

All credentials and tuning options are managed from **Settings → Authentication** and **Settings → Agents** in the dashboard — see [Dashboard Guide](docs/wiki/Dashboard-Guide.md). Editing `.env` directly is only needed for the one-time repo bootstrap described in [Getting Started](docs/wiki/Getting-Started.md); everything else is UI-driven and takes effect without a restart.

**Rebuild after code changes:** `make restart`

**Security model:** The orchestrator port is bound to `127.0.0.1` (no LAN exposure). All write endpoints require a bearer token. Secrets are stored encrypted in Vault, not plaintext. Details in [Reliability](docs/wiki/Reliability.md).

### Agent backends

Four subscription CLI backends (`claude`, `cursor`, `codex`, `gemini`) plus one API backend (`claude-api`). Subscription backends run on your host machine and use your existing CLI login — Docker never touches your credentials. See [Agent Backends](docs/wiki/Agent-Backends.md) for setup per backend.

---

## What's in the box

| File / Dir | Purpose |
|------------|---------|
| `AGENT_PROCESS.md` | Single source of truth for agents: risk tiers, WO flow, branch/PR rules, parallel coordination |
| `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/agent-process.mdc` | Per-CLI entry points read automatically by each agent |
| `Makefile.template`, `.env.example` | Copy and fill in for your stack |
| `services/status-site/` | FastAPI + Jinja2 status dashboard |
| `services/orchestrator/` | Dispatch REST API — claim/checkin/validate/complete, thread storage, intelligence loop |
| `services/vault/` | HashiCorp Vault container — encrypted secrets |
| `services/pr-watchdog/` | PR lifecycle monitor — CI health, stale PRs, merge eligibility |
| `services/agent-runner/` | Autonomous WO executor — runs **natively via launchd** (`scripts/agent-install.sh`), never in Docker |
| `.github/workflows/` | AI review, CI templates, verifier, merge advisor, post-merge memory, observability, doc writer |
| `scripts/` | `ai_review.py`, `planning_agent.py`, `verifier_agent.py`, `merge_advisor.py`, `memory_agent.py`, `observability_agent.py` |
| `docs/factory/PLAN.json` | Priority queue + milestones — orchestrator and status site both read this |
| `docs/project_management/` | WO spec template, progress tracker, capability registry |
| `docs/wiki/` | Full documentation — start at [Home](docs/wiki/Home.md) |
| `memory/` | Persistent agent memory across conversations |

---

## The fastest path: talk to the Project Engineer

After creating your repo from this template, open Claude Code in the repo and say:

> **"Read ENGINEER.md and help me set up the factory."**

The Project Engineer agent checks what's already configured and walks you through CI, CD, branch protection, AI review context, and the memory system — one step at a time. Most projects are fully set up in 15–20 minutes.

For manual, step-by-step setup instead, see **[Getting Started](docs/wiki/Getting-Started.md)** in the wiki — it covers creating the repo from the template, GitHub ruleset configuration, first-time local setup, installing the agent runner, and writing your first work order.

---

## The factory pattern

Every work order has a risk tier that determines the merge workflow:

| Tier | Examples | Merge |
|------|----------|-------|
| **P0** | Auth, security, data loss risk | Human reviews and approves |
| **P1** | Core features, schema changes | Human reviews and approves |
| **P2** | Additive features, tests, docs | Agent opens PR → `gh pr merge --auto --squash` |
| **P3** | Docs, PM files only | Agent commits directly to `main` |

Each WO is owned end-to-end by an agent: claim → branch → implement → human checkpoint → PR → CI + AI review → merge → post-merge verification. `make ci-local` mirrors CI exactly and is the contract every agent runs before opening a PR — no `|| true` bypasses.

Full detail on risk tiers, multi-agent coordination, the SDLC loop, and AI review gating: **[Daily Workflow](docs/wiki/Daily-Workflow.md)**.

---

## Push notifications

The factory sends push notifications (via [ntfy.sh](https://ntfy.sh), optionally Slack) for events like WOs needing human review, agent errors, and merges. Setup is automatic with `make agent-setup`; manage topics and test delivery from **Settings → Authentication**. Details: [Notifications](docs/wiki/Notifications.md).

---

## Creating and managing work orders

Recommended path: **Settings → Plan → Create WO** in the dashboard — describe what you want in plain language, review the AI-generated spec, click Open PR. Full detail on editing, holding, and queue management: [Work Orders](docs/wiki/Work-Orders.md).

---

## Philosophy

**Agents own the SDLC, humans own the decisions.**

Agents handle the mechanical work — branching, coding, testing, PRs, cleanup. Humans set priorities (PLAN.json), approve risky changes (P0/P1), and verify the product works before each commit. The factory is the structure that keeps that division clean.

**The CI gate is the contract.** `make ci-local` is what CI runs. If it passes locally, it passes in CI.

**Risk tier drives autonomy.** P2/P3 work is fully autonomous. P1/P0 work requires human approval. Gate on risk tier, not on trust level.

---

## License

MIT — use freely, attribution appreciated.

Built by [dentroio](https://github.com/dentroio).
