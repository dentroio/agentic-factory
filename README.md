# Agentic Engineering Factory

A **runtime** for building software with AI agents — human-in-the-loop where it matters, autonomous where it's safe.

This repository is the **engine** (dashboard, orchestrator, runner). Your application lives in another GitHub repo. Point `GITHUB_REPO` at it. You do not need any other private product.

| Start here | Link |
|------------|------|
| Two-repo model | [Adopting](docs/wiki/Adopting.md) |
| Setup walkthrough | [Getting Started](docs/wiki/Getting-Started.md) |
| Product template (Use this template) | [dentroio/agentic-factory-template](https://github.com/dentroio/agentic-factory-template) |
| Existing app | [Bring your own repo](docs/adopters/BYO.md) |
| Generic agent process | [docs/adopters/PROCESS.md](docs/adopters/PROCESS.md) |
| Essays | [docs/blog](docs/blog/README.md) |
| Full wiki | [docs/wiki/Home.md](docs/wiki/Home.md) |

Do **not** use this engine repo’s GitHub “Use this template” button to start an app. That copies Docker services. Use [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) for a demo product, then replace `demo/` with your code.

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
make agent-setup              # when asked for GitHub repo, enter owner/your-product
make up
open http://localhost:8099
```

All credentials and tuning options are managed from **Settings → Authentication** and **Settings → Agents** in the dashboard — see [Dashboard Guide](docs/wiki/Dashboard-Guide.md). Editing `.env` directly is only needed for the one-time repo bootstrap described in [Getting Started](docs/wiki/Getting-Started.md); everything else is UI-driven and takes effect without a restart.

**Rebuild after code changes:** `make restart`

**Security model:** Orchestrator (`8100`) and dashboard (`8099`) bind to `127.0.0.1`. Orchestrator requests require `Authorization: Bearer <API_SECRET>` (a machine token in Keychain — not a human login). Dashboard **reads** are open on loopback; **writes** require that bearer token or a same-origin browser `Origin` (`http://127.0.0.1:8099`). Secrets are stored encrypted in Vault, not plaintext. Details in [Reliability](docs/wiki/Reliability.md).

### Agent backends

Four subscription CLI backends (`claude`, `cursor`, `codex`, `gemini`) plus one API backend (`claude-api`). Subscription backends run on your host machine and use your existing CLI login — Docker never touches your credentials. See [Agent Backends](docs/wiki/Agent-Backends.md) for setup per backend.

---

## What's in the box

| File / Dir | Purpose |
|------------|---------|
| `docs/adopters/` | Generic process, contract, BYO checklist — for **product** repos |
| `docs/blog/` | Public essay series on Work Orders and agents |
| `templates/github/` | Workflow **copies** to paste into a product repo (do not replace this engine’s live Actions) |
| `AGENT_PROCESS.md` | Process for agents working **on this engine** |
| `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/agent-process.mdc` | Engine front doors |
| `Makefile.template`, `.env.example` | Optional copies if you vendor engine-style Make/CI into a product |
| `services/status-site/` | FastAPI + Jinja2 status dashboard |
| `services/orchestrator/` | Dispatch REST API — claim/checkin/validate/complete, thread storage, intelligence loop |
| `services/vault/` | HashiCorp Vault container — encrypted secrets |
| `services/pr-watchdog/` | PR lifecycle monitor — CI health, stale PRs, merge eligibility |
| `services/agent-runner/` | Autonomous WO executor — runs **natively via launchd** (`scripts/agent-install.sh`), never in Docker |
| `.github/workflows/` | **This engine’s** CI and specialists — leave them |
| `scripts/` | `ai_review.py`, `planning_agent.py`, `verifier_agent.py`, `merge_advisor.py`, `memory_agent.py`, `observability_agent.py` |
| `docs/factory/PLAN.json` | Engine-side queue artifacts |
| `docs/wiki/` | Full documentation — start at [Home](docs/wiki/Home.md) |
| `memory/` | Persistent agent memory for **factory** development |

---

## Fastest path

**1. Product:** create a repo from [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) (or point at an existing app — [BYO](docs/adopters/BYO.md)).

**2. Engine:** clone this repo, run `make agent-setup`, set `GITHUB_REPO` to `owner/your-product`, then `make up`.

**3. Manual walkthrough:** [Getting Started](docs/wiki/Getting-Started.md).

**Developing this engine** (not a product): open Claude Code *here* and say:

> **"Read ENGINEER.md and help me set up the factory."**

That Project Engineer path configures **this** repository (CI, branch protection, review context). Product repos use [PROCESS.md](docs/adopters/PROCESS.md) and [SETUP.md](https://github.com/dentroio/agentic-factory-template/blob/main/SETUP.md) instead.

---

## The factory pattern

Every work order has a risk tier that determines the merge workflow:

| Tier | Examples | Merge |
|------|----------|-------|
| **P0** | Auth, security, data loss risk | Human reviews and approves |
| **P1** | Core features, schema changes | Human reviews and approves |
| **P2** | Additive features, tests, docs | Agent opens PR → `gh pr merge --auto --squash` |
| **P3** | Docs, PM files only | Agent opens PR → `gh pr merge --auto --squash` |

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
