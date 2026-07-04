# Agentic Engineering Factory

A template for building software with AI agents — human-in-the-loop where it matters, autonomous where it's safe.

Extracted from an active development project. Still evolving.

---

## Live Dashboard + Runtime Stack

The factory ships Docker services that run alongside your project:

| Service | Port | Profile | Purpose |
|---------|------|---------|---------|
| `factory-status` | 8099 | default | Web dashboard — Overview, PM, Engineering, Plan Authoring, Threads, Settings |
| `orchestrator` | 8100 | default | Dispatch REST API, WO lifecycle, thread storage, secrets vault, hold/unhold queue |
| `pr-watchdog` | — | default | Tracks every open PR: CI state, stale detection, merge eligibility |
| `agent-runner` | host | optional | Autonomous WO executor — subscription CLI backends (Claude, Cursor, Codex, Gemini); draft server on port 8101 |

**Start them (macOS — uses Keychain for secrets):**

```bash
make agent-setup              # one-time: stores GitHub token + repo in macOS Keychain
make up                       # reads Keychain → .env.runtime → starts Docker services
open http://localhost:8099
```

**First time on a new machine:**

```bash
make agent-setup              # prompts for GitHub token, repo, Slack webhook, Anthropic key
make up
# Then open Settings → Authentication to verify credentials are live
```

**Rebuild after code changes:**

```bash
make restart                  # rebuild all images and recreate containers
```

**Environment variables** (set via `make agent-setup` or `Settings → Authentication`):

```env
GITHUB_TOKEN=ghp_...          # classic PAT: repo + read:org  (required)
GITHUB_REPO=your-org/your-repo                                 (required)
ANTHROPIC_API_KEY=sk-ant-...  # optional — only needed for claude-api draft backend
SLACK_WEBHOOK_URL=https://hooks.slack.com/...  # optional notifications
```

Optional tuning (`.env` file or docker-compose override):

```env
SITE_TITLE=My Factory         # dashboard title
REFRESH_SECONDS=60            # page auto-refresh interval
WO_PATH=docs/project_management/work_orders
RUNS_PATH=docs/factory/runs
PLAN_PATH=docs/factory/PLAN.json
POLL_INTERVAL=300             # orchestrator + watchdog poll cadence (seconds)
MAX_PARALLEL_WOS=2            # max concurrent agent assignments
POST_COMMENTS=false           # set true to have watchdog post GitHub PR comments
NTFY_URL=https://ntfy.sh/your-topic  # push notifications alternative to Slack
```

### Agent backends

The agent-runner supports four AI backends, all subscription-based — no per-token billing:

| Backend | How it runs | Requires |
|---------|-------------|---------|
| `claude` | `claude --print` CLI | Claude subscription + CLI logged in |
| `cursor` | `cursor --print` CLI | Cursor subscription + CLI logged in |
| `codex` | `codex exec -` CLI | OpenAI Codex subscription |
| `gemini` | `gemini -p` CLI | Google Gemini subscription |
| `claude-api` | Anthropic SDK (Docker) | `ANTHROPIC_API_KEY` in secrets |

The agent-runner starts a local HTTP server (`draft_server.py`) on port **8101**. The orchestrator proxies WO draft requests to this server when using subscription backends — so the Docker container never needs your CLI session credentials.

---

## What's in the box

| File / Dir | Purpose |
|------------|---------|
| `AGENT_PROCESS.md` | Single source of truth for agents: risk tiers, WO flow, branch/PR rules, parallel coordination |
| `CLAUDE.md` | Claude Code entry point — read automatically by `claude` CLI |
| `AGENTS.md` | OpenAI/Codex/generic entry point |
| `.cursor/rules/agent-process.mdc` | Cursor IDE entry point (`alwaysApply: true`) |
| `Makefile.template` | Copy to `Makefile` — fill in `{{FILL IN}}` sections for your stack |
| `.env.example` | Environment variable reference for the container runtime |
| **Container Runtime** | |
| `docker-compose.status.yml` | Brings up all factory services; `agent` profile enables agent-runner |
| `services/status-site/` | FastAPI + Jinja2 status dashboard (Overview, PM, Engineering, Plan, Threads, Settings) |
| `services/orchestrator/` | Dispatch REST API — claim/checkin/validate/complete, thread storage, image serving, notifications |
| `services/pr-watchdog/` | PR lifecycle monitor — CI health, stale PRs, merge eligibility |
| `services/agent-runner/` | Autonomous WO executor — subscription CLI backends, quality gate, peer review chain |
| `services/agent-runner/backends/` | Pluggable AI backends: `claude.py`, `cursor.py`, `codex.py`, `gemini.py` |
| `services/agent-runner/draft_server.py` | Local HTTP daemon (port 8101) — probes installed CLIs, serves `POST /api/draft` to orchestrator |
| `services/agent-runner/quality_gate.py` | Parallel CI + bandit + semgrep + JS/TS security scan |
| `services/agent-runner/review_chain.py` | 4-reviewer AI review chain (security, architecture, correctness, performance) |
| `services/agent-runner/prompt_builder.py` | Agent mandate injected into every WO prompt (security, performance, quality rules) |
| **CI / Review** | |
| `.github/workflows/ai-review.yml` | Blocking AI code review on every PR — exits 1 on "Review required" |
| `.github/workflows/ci.yml.template` | Copy to `ci.yml` — fill in lint/test/build steps |
| `.github/workflows/deploy.yml.template` | Copy to `deploy.yml` — parameterized CD pipeline with smoke tests |
| `.github/workflows/verifier.yml` | Post-merge → checks AC from WO spec against diff → opens follow-up issue on failure |
| `.github/workflows/ci-failure-notifier.yml` | CI fails → posts details + log excerpt on the PR |
| `.github/workflows/merge-advisor.yml` | Synthesizes all signals → posts ✅/⚠️/❌ merge recommendation |
| `.github/workflows/post-merge-memory.yml` | Post-merge → extracts lessons → opens memory PR |
| `.github/workflows/observability.yml` | Scheduled → polls health endpoint → creates incident issue on anomaly |
| `.github/dependabot.yml.template` | Monthly dependency updates with PR limits — prevents Actions minute floods |
| `scripts/ai_review.py` | Claude-powered code review — 7 universal checks + project-specific context |
| `scripts/review_context.txt` | Project-specific checks added to the AI reviewer |
| `scripts/planning_agent.py` | Converts issue title+body into a filled WO spec |
| `scripts/verifier_agent.py` | Verifies acceptance criteria from WO spec against a PR diff |
| `scripts/merge_advisor.py` | Synthesizes CI, AI review, risk tier, diff analysis into merge recommendation |
| `scripts/memory_agent.py` | Extracts non-obvious lessons from a merged PR diff |
| `scripts/observability_agent.py` | Polls metrics endpoint, detects threshold violations |
| `scripts/observability_thresholds.json` | Configurable error rate, latency, service health thresholds |
| **PM / Memory** | |
| `docs/factory/PLAN.json` | Priority queue + milestone definitions — the orchestrator and status site both read this |
| `docs/project_management/` | WO spec template, progress tracker, capability registry |
| `memory/` | Persistent agent memory across conversations |

---

## The fastest path: talk to the Project Engineer

After creating your repo from this template, open Claude Code in the repo and say:

> **"Read ENGINEER.md and help me set up the factory."**

The Project Engineer agent will check what's already configured, walk you through CI, CD, branch protection, AI review context, and the memory system — one step at a time. Most projects are fully set up in 15–20 minutes.

---

## Manual bootstrap

### 1. Create your repo from this template

```bash
gh repo create your-org/your-project --template dentroio/agentic-factory --private
git clone git@github.com:your-org/your-project.git
cd your-project
```

### 2. Find-replace the project name placeholder

```bash
# macOS
find . -not -path './.git/*' -type f | xargs grep -l '{{PROJECT_NAME}}' | \
  xargs sed -i '' 's/{{PROJECT_NAME}}/YourProjectName/g'
```

### 3. Set up the Makefile

```bash
cp Makefile.template Makefile
# Edit Makefile — fill in all {{FILL IN}} sections for your stack
```

### 4. Configure the container runtime

```bash
make agent-setup              # stores secrets in macOS Keychain — prompts for each value
make up                       # reads Keychain → starts Docker services
open http://localhost:8099
```

Open **Settings → Authentication** to verify credentials are live, or update them without restarting.

### 5. Set up CI

```bash
cp .github/workflows/ci.yml.template .github/workflows/ci.yml
# Edit ci.yml — fill in {{...}} sections for your stack
```

### 6. Add your ANTHROPIC_API_KEY secret (optional)

Only required if you want the **claude-api** draft backend (direct Anthropic API calls from Docker). Subscription-based backends (Claude, Cursor, Codex, Gemini CLIs) don't need it.

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: your key from [console.anthropic.com](https://console.anthropic.com)

You can also set it at runtime via **Settings → Authentication** in the factory dashboard.

### 7. Configure GitHub Ruleset (required status checks)

In your GitHub repo: **Settings → Rules → Rulesets → New ruleset**

Add these as required status checks for `main`:
- `Secret Detection (Gitleaks)`
- `Lint`
- `Unit Tests`
- `Build`
- `Claude Code Review`

### 8. Add project-specific AI review checks

Edit `scripts/review_context.txt` — add invariants that the AI reviewer should flag.

### 9. Customize AGENT_PROCESS.md §10

Replace the placeholder in §10 (Critical Code Patterns) with your project's actual invariants — DB commit rules, auth gates, migration registration, etc.

### 10. Initialize memory

Edit `memory/MEMORY.md` and `memory/examples/project_overview.md` with your project details.

### 11. Write your first work order

Copy `docs/project_management/work_orders/WO-000-template.md` to `WO-001-initial-setup.md`.
The `## Execution` section is what agents read to start working.

### 12. Define your plan

Edit `docs/factory/PLAN.json` — set your milestones and initial WO priority queue.
The orchestrator and status dashboard both read this file from GitHub on each poll cycle.

---

## The factory pattern

### Risk tiers

Every work order has a risk tier that determines the merge workflow:

| Tier | Examples | Merge |
|------|----------|-------|
| **P0** | Auth, security, data loss risk | Human reviews and approves |
| **P1** | Core features, schema changes | Human reviews and approves |
| **P2** | Additive features, tests, docs | Agent opens PR → `gh pr merge --auto --squash` |
| **P3** | Docs, PM files only | Agent commits directly to `main` |

### Deployment model declaration

Before agents start working, the project declares its deployment model in `AGENT_PROCESS.md` under `## Development Environment`. Two models are supported:

**Local Docker (single dev machine, no CD)**
Code changes must be pushed into the running Docker containers before verification. Agents run `make deploy-changed` after implementing a WO — this auto-detects which services changed, rebuilds and redeploys them, and blocks until healthy.

**CD-based (staging/production)**
Code changes are deployed automatically after merging to main via `deploy.yml`. Agents verify against the staging URL after merge. No local container rebuild needed.

### Agent SDLC ownership

Each WO is owned end-to-end by an agent:

1. **Claim** — agent creates `docs/factory/runs/WO-NNN.json` (atomic git lock)
2. **Branch** — `wo/NNN-slug` is the claim; no two agents touch the same branch
3. **Implement** — agent codes, rebuilds containers, verifies
4. **Human checkpoint** — agent stops and asks the human to verify before committing
5. **PR** — agent opens the PR with UI verification steps in the body
6. **CI + AI Review** — automated gates run on every PR
7. **Merge** — P2 auto-merges; P1/P0 wait for human approval
8. **Watchdog** — pr-watchdog tracks CI, posts stale warnings, flags eligibility
9. **Post-merge** — verifier checks AC, memory agent extracts lessons

### Multi-agent coordination

When multiple agents work concurrently (multiple sessions, or multiple workstations):

- **Claim file as mutex** — creating `docs/factory/runs/WO-NNN.json` is an atomic git operation; the second agent's push fails fast
- **One agent per service** — no two agents touch the same service simultaneously
- **Branch as claim** — agents check for `origin/wo/NNN-*` before starting
- **Shared files are sequential** — `adapter.py`, `main.py`, routing, `PROGRESS.md` — no parallel edits
- **Single orchestrator** — run the orchestrator on one machine only; it is the serialization point for dispatch

### The CI gate

Every agent runs `make ci-local` before opening a PR. The local gate mirrors CI exactly:

```
lint → test → check-migrations → build
```

No `|| true` bypasses. A broken step must be visible.

### AI code review

The `ai-review.yml` workflow runs on every PR:

1. Diffs source files against `main`
2. Calls Claude with 7 universal checks + your project-specific checks
3. Posts a structured review comment
4. **Exits 1 if verdict is "Review required"** — blocks merge via GitHub Ruleset

### Memory compounds

Every correction saved to `memory/` persists across sessions. A project with 50 saved feedback entries is dramatically easier to work on than one where agents rediscover the same invariants every conversation.

---

## Full SDLC loop

```
Production anomaly / new requirement
            │
            ▼
  observability.yml ──► GitHub issue (labeled 'incident' or 'new-wo')
                                 │
                     planning-agent.yml ──► WO spec PR ──► human reviews & merges
                                                                     │
                                                   orchestrator reads PLAN.json priority queue
                                                                     │
                                                         agent picks up WO (claims it)
                                                                     │
                                                                     ▼
                                                             implements on branch
                                                                     │
                                              human checkpoint ◄── deploys to containers
                                                  (verify it works)
                                                                     │
                                                               make ci-local
                                                                     │
                                                               opens PR
                                                                     │
                                                   ┌─────────────────┴─────────────────┐
                                                   │                                   │
                                            ai-review.yml                     ci.yml (lint/test/build)
                                                   │                                   │
                                                   └─────────────────┬─────────────────┘
                                                                     │
                                                      pr-watchdog monitors CI health
                                                                     │
                                                        merge (P2 auto / P1 human)
                                                                     │
                                                      ┌──────────────┴──────────────┐
                                                      │                             │
                                               verifier.yml             post-merge-memory.yml
                                               (AC check)               (lesson extraction)
                                                      │                             │
                                           follow-up issue if            memory PR if lesson
                                            criteria not met                found
                                                                             │
                                                             orchestrator dispatches next WO ◄┘
```

---

## Creating and managing work orders

### From the UI (recommended)

1. Open **Settings → Plan → Create WO**
2. Describe what you want to build in plain language — one paragraph
3. Choose which AI generates the structured spec (Claude, Cursor, Codex, Gemini, or Anthropic API)
4. Review and edit the generated fields (title, priority, effort, problem, acceptance criteria)
5. Click **Open PR** — the factory creates the spec file and adds the WO to PLAN.json in one PR

### Editing existing WOs

Each open WO row in **Settings → Plan** has an ✎ button that opens the raw markdown spec in an editor. Saving opens a PR against main — the agent won't pick up the WO until it's merged.

### Queue management

- **⏸ Hold** — prevents the orchestrator from claiming a WO (useful when a dependency isn't merged yet)
- **▶ Resume** — re-enables a held WO
- Hold state persists across factory restarts (`/data/held_wos.json` in the orchestrator volume)

---

## Philosophy

**Agents own the SDLC, humans own the decisions.**

Agents handle the mechanical work — branching, coding, testing, PRs, cleanup. Humans set priorities (PLAN.json), approve risky changes (P0/P1), and verify the product works before each commit. The factory is the structure that keeps that division clean.

**The CI gate is the contract.**

`make ci-local` is what CI runs. If it passes locally, it passes in CI. Agents that skip it will eventually break the main branch and lose trust.

**Risk tier drives autonomy.**

P2/P3 work is fully autonomous. P1/P0 work requires human approval. The cost of a false-positive block (human reviews a safe change) is low. The cost of a false-negative (agent breaks production) is high. Gate on risk tier, not on trust level.

---

## License

MIT — use freely, attribution appreciated.

Built by [dentroio](https://github.com/dentroio).
