# Agentic Engineering Factory

A battle-tested template for building software with AI agents — human-in-the-loop where it matters, autonomous where it's safe.

Born from production use on the [Clarion](https://github.com/dentroio/clarion) project.

---

## What's in the box

| File / Dir | Purpose |
|------------|---------|
| `AGENT_PROCESS.md` | Single source of truth for how agents work: risk tiers, WO flow, branch/PR rules, parallel agent coordination |
| `CLAUDE.md` | Claude Code entry point — read automatically by `claude` CLI |
| `AGENTS.md` | OpenAI/Codex/generic entry point |
| `.cursor/rules/agent-process.mdc` | Cursor IDE entry point (`alwaysApply: true`) |
| `Makefile.template` | Copy to `Makefile` — fill in `{{FILL IN}}` sections for your stack |
| `.github/workflows/ai-review.yml` | Blocking AI code review on every PR — exits 1 on "Review required" |
| `.github/workflows/ci.yml.template` | Copy to `ci.yml` — fill in lint/test/build steps |
| `scripts/ai_review.py` | Claude-powered review script — universal checks + project-specific context |
| `scripts/review_context.txt` | Project-specific checks for the AI reviewer |
| `docs/project_management/` | Progress tracker, capability registry, WO spec template |
| `memory/` | Persistent agent memory across conversations |

---

## Bootstrap a new project in 10 minutes

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

Verdict meanings:
- **LGTM** — all checks pass
- **Needs attention** — warnings exist, merge allowed
- **Review required** — a check failed, merge blocked

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
