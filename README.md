# Agentic Engineering Factory

A template for building software with AI agents — human-in-the-loop where it matters, autonomous where it's safe.

Extracted from an active development project. Still evolving.

---

## What's in the box

| File / Dir | Purpose |
|------------|---------|
| `AGENT_PROCESS.md` | Single source of truth for how agents work: risk tiers, WO flow, branch/PR rules, parallel agent coordination |
| `CLAUDE.md` | Claude Code entry point — read automatically by `claude` CLI |
| `AGENTS.md` | OpenAI/Codex/generic entry point |
| `.cursor/rules/agent-process.mdc` | Cursor IDE entry point (`alwaysApply: true`) |
| `Makefile.template` | Copy to `Makefile` — fill in `{{FILL IN}}` sections for your stack |
| **CI / Review** | |
| `.github/workflows/ai-review.yml` | Blocking AI code review on every PR — exits 1 on "Review required" |
| `.github/workflows/ci.yml.template` | Copy to `ci.yml` — fill in lint/test/build steps |
| `.github/workflows/deploy.yml.template` | Copy to `deploy.yml` — parameterized CD pipeline with smoke tests |
| `scripts/ai_review.py` | Claude-powered code review — 7 universal checks + project-specific context |
| `scripts/review_context.txt` | Project-specific checks added to the AI reviewer |
| **SDLC Agents** | |
| `.github/workflows/planning-agent.yml` | Triggered by `new-wo` issue label → drafts WO spec → opens PR |
| `.github/workflows/verifier.yml` | Post-merge → checks AC from WO spec against diff → opens follow-up issue on failure |
| `.github/workflows/ci-failure-notifier.yml` | When CI fails → posts failure details + log excerpt on the PR so the agent knows what to fix |
| `.github/workflows/merge-advisor.yml` | After AI review → synthesizes all signals → posts ✅/⚠️/❌ merge recommendation |
| `.github/workflows/post-merge-memory.yml` | Post-merge → extracts lessons → opens memory PR |
| `.github/workflows/observability.yml` | Scheduled → polls health endpoint → creates incident issue on anomaly |
| `scripts/planning_agent.py` | Converts issue title+body into a filled WO spec |
| `scripts/verifier_agent.py` | Verifies acceptance criteria from WO spec against a PR diff |
| `scripts/merge_advisor.py` | Synthesizes CI, AI review, risk tier, diff analysis into merge recommendation |
| `scripts/memory_agent.py` | Extracts non-obvious lessons from a merged PR diff |
| `scripts/observability_agent.py` | Polls metrics endpoint, detects threshold violations |
| `scripts/observability_thresholds.json` | Configurable error rate, latency, service health thresholds |
| **PM / Memory** | |
| `docs/project_management/` | Progress tracker, capability registry, WO spec template |
| `memory/` | Persistent agent memory across conversations |

---

## The fastest path: talk to the Project Engineer

After creating your repo from this template, open Claude Code in the repo and say:

> **"Read ENGINEER.md and help me set up the factory."**

The Project Engineer agent will check what's already configured, walk you through CI, CD, branch protection, AI review context, and the memory system — one step at a time. Most projects are fully set up in 15–20 minutes.

To check status at any time:
```bash
python3 scripts/factory_status.py
```

---

## Manual bootstrap (if you prefer)

### 1. Create your repo from this template

Click **"Use this template"** on GitHub, or:

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

# Linux
find . -not -path './.git/*' -type f | xargs grep -l '{{PROJECT_NAME}}' | \
  xargs sed -i 's/{{PROJECT_NAME}}/YourProjectName/g'
```

### 3. Set up the Makefile

```bash
cp Makefile.template Makefile
# Edit Makefile — fill in all {{FILL IN}} sections for your stack
```

### 4. Set up CI

```bash
cp .github/workflows/ci.yml.template .github/workflows/ci.yml
# Edit ci.yml — fill in {{...}} sections for your stack
```

### 5. Add your ANTHROPIC_API_KEY secret

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: your key from [console.anthropic.com](https://console.anthropic.com)

### 6. Configure GitHub Ruleset (required status checks)

In your GitHub repo: **Settings → Rules → Rulesets → New ruleset**

Add these as required status checks for `main`:
- `Secret Detection (Gitleaks)`
- `Lint`
- `Unit Tests`
- `Build`
- `Claude Code Review`

### 7. Add project-specific AI review checks

Edit `scripts/review_context.txt` — add invariants that the AI reviewer should flag.
See the file for examples and format instructions.

### 8. Customize AGENT_PROCESS.md §10

Replace the placeholder in §10 (Critical Code Patterns) with your project's actual invariants:
patterns the AI must always follow (e.g., DB commit rules, auth gates, migration registration).

### 9. Initialize memory

Edit `memory/MEMORY.md` and `memory/examples/project_overview.md` with your project details.
These files persist across Claude Code conversations and give agents immediate orientation.

### 10. Write your first work order

Copy `docs/project_management/work_orders/WO-000-template.md` to `WO-001-initial-setup.md`
and fill it in. The `## Execution` section is what agents read to start working.

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

Before agents start working, the project declares its deployment model in `AGENT_PROCESS.md` under `## Development Environment`. Agents read this at the start of every session. Two models are supported:

**Local Docker (single dev machine, no CD)**
Code changes must be pushed into the running Docker containers before verification. Agents run `make deploy-changed` after implementing a WO — this auto-detects which services changed, rebuilds and redeploys them, and blocks until healthy. There is no staging URL; everything runs on `localhost`.

**CD-based (staging/production)**
Code changes are deployed automatically after merging to main via `deploy.yml`. Agents verify against the staging URL after merge. No local container rebuild needed.

The declaration tells agents: "if you can't reach localhost, stop at `make ci-local` and write verification steps for the human instead."

### The CI gate

Every agent runs `make ci-local` before opening a PR. The local gate mirrors CI exactly:

```
lint → test → check-migrations → build
```

For local Docker projects, `make ci-local` is preceded by `make deploy-changed` (container rebuild + health gate). The CI gate is code quality only — it does not deploy anything.

No `|| true` bypasses. A broken step must be visible.

### AI code review

The `ai-review.yml` workflow runs on every PR:

1. Diffs source files against `main`
2. Calls Claude with 7 universal checks + your project-specific checks
3. Posts a structured review comment
4. **Exits 1 if verdict is "Review required"** — blocks merge via GitHub Ruleset

Verdict meanings:
- **LGTM** — all checks pass
- **Needs attention** — warnings exist, merge allowed
- **Review required** — a check failed, merge blocked

### UI verification in every PR

Every PR body must include a `## UI Verification` section — a numbered checklist the developer can follow in the browser to confirm the feature works, without reading the code:

```
## UI Verification
1. Open http://localhost:5173 — log in as admin
2. Navigate to Settings → Connectors
3. Click Add Connector, select WLC 9800, fill in hostname
4. Expected: green "Connected" badge within 30 seconds
5. Confirm no errors in browser DevTools console
```

Backend-only PRs write: `No UI changes — backend / API only.`

This makes every PR self-describing for QA and human reviewers. The WO spec's `### UI Verification` subsection is where agents write these steps *before* implementing — it defines what "done" looks like in the browser.

### Parallel agent coordination

When multiple agents work concurrently:

- **One agent per service/module** — no two agents touch the same service simultaneously
- **Branch as claim** — creating a branch is the claim; agents check for existing branches before starting
- **Shared files are sequential** — `adapter.py`, `main.py`, gateway routing, `PROGRESS.md` — no parallel edits
- **Agents announce intent** in the PR description before touching shared files

### Memory system

The `memory/` directory persists across Claude Code conversations. It stores:

- `user` — who you are, how you like to work
- `feedback` — what the AI should do/avoid (corrections and confirmations)
- `project` — ongoing programs, decisions, blockers
- `reference` — where to find things in external systems

See `memory/examples/` for file format.

---

## Extending the factory

### Add a new CI check

1. Add the job to `.github/workflows/ci.yml`
2. Add the step to `make ci-local` in `Makefile`
3. Add it to the required status checks in your GitHub Ruleset
4. Update `AGENT_PROCESS.md` §9 so agents know to expect it

### Add a project-specific AI review check

Add a numbered item to `scripts/review_context.txt`. Be specific — vague checks produce vague feedback.

### Add a new work order type

Copy `docs/project_management/work_orders/WO-000-template.md` and fill in the sections.
The `## Execution` section is the agent's entry point — include branch name, risk tier, PR title, and files to touch.

---

## Full SDLC loop

The five agents form a complete cycle from production anomaly back to implemented fix:

```
Production anomaly
       │
       ▼
observability.yml ──► GitHub issue (labeled 'incident')
                               │
                 label 'new-wo'│ (human or auto)
                               ▼
                   planning-agent.yml ──► WO spec PR ──► human reviews & merges
                                                                   │
                                                       agent picks up WO Execution section
                                                                   │
                                                                   ▼
                                                           implements on branch
                                                                   │
                                                              make ci-local
                                                                   │
                                                              opens PR
                                                                   │
                                                   ┌──────────────┴──────────────┐
                                                   │                             │
                                               ai-review.yml              ci.yml (lint/test/build)
                                                   │                             │
                                                   └──────────────┬──────────────┘
                                                                  │
                                                         merge (P2 auto / P1 human)
                                                                  │
                                                     ┌────────────┴────────────┐
                                                     │                         │
                                              verifier.yml            post-merge-memory.yml
                                              (AC check)              (lesson extraction)
                                                     │                         │
                                          follow-up issue if           memory PR if lesson
                                           criteria not met               found
```

### Setup sequence for the full loop

In addition to the base bootstrap steps:

1. **Planning agent:** Add a `new-wo` label to your repo (Settings → Labels → New label)
2. **Observability:** Add `METRICS_ENDPOINT` as a repository variable (Settings → Variables → Actions)
3. **Deploy:** Copy `deploy.yml.template` → `deploy.yml`, fill in deploy + smoke test steps
4. **Thresholds:** Edit `scripts/observability_thresholds.json` for your error rate and latency SLOs

---

## Philosophy

**Agents are powerful but need guardrails.**

The factory gives agents enough structure to work autonomously on P2/P3 work while ensuring humans stay in the loop for anything risky. The key insight: the cost of a false autonomy (agent breaks prod) vastly exceeds the cost of a false gate (human reviews a safe change). Gate on risk tier, not on trust.

**The CI gate is the contract.**

`make ci-local` is what CI runs. If it passes locally, it passes in CI. Agents that skip it will eventually break the main branch and lose trust.

**Memory compounds.**

Every correction saved to `memory/` is a lesson that persists across sessions. A project with 50 saved feedback entries is dramatically easier to work on than one where agents rediscover the same invariants every conversation.

---

## License

MIT — use freely, attribution appreciated.

Built by [dentroio](https://github.com/dentroio).
