# Agentic Engineering Factory — Engineer Overview

## What the Factory Is

The Agentic Engineering Factory is a GitHub repository template that provides a complete, opinionated system for running AI agents on a software project. It ships as a template — you create your repository from it, fill in a handful of project-specific placeholders, run `make agent-setup` once, and a production-grade agent infrastructure is operational.

The factory is extracted from an active development project. Everything in it has been used in production, not designed speculatively.

### The Philosophy

The factory is built around a single principle: **gate on risk, not on trust.**

Agents are capable of handling the majority of engineering work autonomously. But the cost of a false autonomy — an agent breaks production, corrupts data, ships a security regression — vastly exceeds the cost of a false gate — a human reviews a change that would have been safe to auto-merge. The factory encodes this asymmetry into a risk tier model that determines, per work order, whether a human approves or an agent merges.

The corollary is that for work below the risk threshold, the system should not slow things down for the sake of process. A P2 work order — additive feature, new test, minor refactor — should go from implementation to merged without a human ever looking at it, as long as CI passes and the AI review is clean. That is the target state for routine work.

The second principle: **the CI gate is the contract.** `make ci-local` mirrors the GitHub Actions CI pipeline exactly. An agent that runs the local gate before pushing will never surprise CI. An agent that skips it eventually breaks the main branch and erodes the team's trust in the system.

The third principle: **memory compounds.** Every lesson saved to the `memory/` directory is available to every future agent session. A project that accumulates 50 memory entries — project-specific invariants, past failure modes, non-obvious constraints — is dramatically easier to work on than one where agents rediscover the same facts every conversation.

---

## Creating Work Orders

Work orders are the unit of work the factory dispatches. There are two ways to create them.

### From the factory dashboard (recommended)

1. Open **Settings → Plan → Create WO** at `http://localhost:8099/settings/plan/wos/new`
2. Describe what you want to build in plain language — one paragraph is enough
3. Choose which AI generates the structured spec (Claude, Cursor, Codex, Gemini via subscription CLI, or Anthropic API)
4. Review and edit the generated fields: title, priority, effort, services, problem, what to build, acceptance criteria
5. Optionally set dependencies (Depends On) and milestone associations (Blocks)
6. Click **Open PR** — the factory creates the spec file and adds the WO to PLAN.json in one PR

After the PR merges, the orchestrator picks up the WO on its next poll cycle and dispatches it to the next available agent.

### From a GitHub issue (GitHub Actions flow)

Label any GitHub issue `new-wo`. The `planning-agent.yml` workflow fires, calls Claude with the issue title and body, drafts a WO spec, and opens a PR. The human reviews the spec and merges. From that point, the WO enters the same queue and dispatch lifecycle as a dashboard-created WO.

### Editing existing WOs

Open **Settings → Plan**, click the ✎ button next to any open WO, edit the raw markdown spec, and click **Open PR**. Changes go through a PR so the agent always works from the reviewed version.

### Managing the queue

- **⏸ Hold** — prevents the orchestrator from dispatching a WO. Use this when a dependency hasn't merged yet or when you want to defer a WO without removing it from the queue.
- **▶ Resume** — re-enables a held WO. Hold state persists across restarts.

---

## The 12 GitHub Actions Workflows

The factory ships with 12 workflow files. Nine are production-ready and activate automatically; three are templates to fill in.

### Production Workflows (active immediately)

**`ai-review.yml` — AI Code Review (blocking)**

Triggers on every PR opened or updated against `main`. Diffs source files against `main`, sends the diff and PR title/body to Claude, and posts a structured review comment with a verdict table. If the verdict is "Review required," the job exits 1, which blocks merge via GitHub's required status check enforcement. "Needs attention" and "LGTM" verdicts allow merge to proceed.

Token-saving rules built in: skips Dependabot PRs entirely; skips any push where the HEAD commit contains `[pr-watch-fix]`, `[ai-review-apply]`, or `[ci-autofix]` (auto-generated commits that were already reviewed on the prior push); uses a concurrency group with `cancel-in-progress: true` so rapid pushes cancel the in-progress review rather than paying for a review that will be immediately superseded. Cost: approximately $0.02–$0.05 per meaningful push.

**`planning-agent.yml` — WO Spec Drafting (GitHub Issues path)**

Triggers when a GitHub issue is labeled `new-wo`. Determines the next WO number by scanning the `docs/project_management/work_orders/` directory, calls `planning_agent.py` with the issue title and body, and opens a PR containing the drafted WO spec. Human reviews the spec and merges; then the orchestrator dispatches it. This is one of two paths for creating WOs — the other is the factory dashboard UI.

**`verifier.yml` — Post-Merge AC Verification**

Triggers when a PR merges to `main` and its title contains a `WO-NNN` reference. Extracts the acceptance criteria from the linked WO spec file, compares them against the merged diff, and posts a verification report on the closed PR. If any criterion is explicitly not met, the workflow exits 1 and creates a follow-up GitHub issue labeled `bug` and `needs-triage`. That issue can itself be labeled `new-wo` to kick off the planning agent for the follow-up.

**`ci-failure-notifier.yml` — Agent CI Feedback Loop**

Triggers when the CI workflow fails. Finds the open PR for the failing branch, downloads the failure logs, filters to key failure lines (errors, assertions, exceptions), and posts a structured comment on the PR. Replaces any previous failure comment rather than stacking. This closes the feedback loop that would otherwise require a human to notice the failure and relay it to the agent. The agent reads the comment, fixes the code on the same branch, and pushes — CI re-runs automatically.

**`ci-auto-fix.yml` — Self-Healing CI**

Triggers on CI failure for agent PRs (PRs with the `agent-pr` label or opened by known bot accounts). Downloads failure logs, sends them along with the PR diff to Claude, and asks for a minimal search-and-replace patch. Applies the patch directly to the checked-out branch and pushes. Includes a hard limit of two auto-fix attempts per PR — tracked via labels (`ci-autofix-attempted`, `ci-autofix-failed`) — to prevent runaway API costs. Build failures and diffs touching more than 10 files are skipped (too complex for safe auto-fix). A loop guard checks the HEAD commit message for `[ci-autofix]` before making any API calls.

**`merge-advisor.yml` — Human Merge Decision Support**

Triggers after the AI Code Review workflow completes. Aggregates all available signals — CI status, AI review verdict, verifier verdict, risk tier from the WO spec, diff risk indicators (schema changes, auth changes, shared files, potential breaking changes), and PR completeness (WO link, migration notes, test plan, summary length). Sends this signal summary to Claude and posts a single synthesized merge recommendation: "Ready to merge," "Review before merging," or "Do not merge." Replaces any previous advisory comment to avoid stacking. Always exits 0 — the merge advisor is decision support, not a gate.

**`post-merge-memory.yml` — Automatic Memory Compaction**

Triggers on every push to `main`. Diffs the last two commits, sends the diff to the memory agent, and receives either a structured memory file or the sentinel string `NOTHING_TO_REMEMBER`. If a memory file is written, the workflow creates a branch, commits the file, and opens a PR for human review. The human can merge as-is (lesson saved), edit the file to rename it to a descriptive topic, or close without merging. A loop guard skips runs where the triggering commit message contains `memory(auto)` to prevent infinite loops.

**`auto-update-prs.yml` — Keep Agent PRs Current**

Triggers on every push to `main`. Finds all open PRs with auto-merge enabled that are behind `main` and calls GitHub's "Update Branch" API on each. This ensures that when multiple agent PRs queue up behind each other, they stay current with `main` and CI keeps running.

**`ai-review-applier.yml` — Auto-Apply Review Suggestions**

Triggers after the AI Code Review workflow completes, but only on agent PRs with a "Needs attention" verdict. Extracts the Suggestions section from the review comment, sends it along with the diff to Claude, and applies search-and-replace edits to the branch files. Commits with the `[ai-review-apply]` tag (loop guard) and pushes. The AI review re-runs on the updated commit — if suggestions were addressed, the verdict moves to "LGTM" and auto-merge fires.

### Templates to Fill In

**`ci.yml.template` → `ci.yml`**

Copy to `.github/workflows/ci.yml` and fill in stack-specific placeholders: lint command, test command, build command, language runtime version. The job names must match exactly what is registered as required status checks in the GitHub Ruleset.

**`deploy.yml.template` → `deploy.yml`**

Only needed for projects with a remote deployment target (staging server, Kubernetes, Heroku, etc.). Fill in the deploy command and health endpoint URL. Skip entirely for local Docker projects.

---

## The Agent Scripts

All scripts are in `scripts/` and are callable both from GitHub Actions and from the local command line.

**`ai_review.py`** — Core review logic. Loads the diff, builds a system prompt from seven universal checks plus project-specific checks from `review_context.txt`, calls Claude (max_tokens=2048), writes a structured markdown review to `--output`. Anchors verdict search to the `### Verdict` section to prevent false matches from suggestion text. Exits 1 for "Review required"; exits 0 for "LGTM" and "Needs attention" (informational).

**`planning_agent.py`** — Converts issue title and body into a filled WO spec. Uses the WO template defined in the script and passes project context from `review_context.txt` as additional signal. The model fills every section of the spec including risk tier assignment, file paths, and the `## Execution` section that agents read before starting implementation.

**`verifier_agent.py`** — Auto-discovers the linked WO spec by parsing the `WO-NNN` reference in the PR title, extracts the `## Acceptance Criteria` section, and asks Claude to evaluate each criterion against the diff. Exits 1 if the verdict is "Criteria not met."

**`merge_advisor.py`** — Runs regex-based risk detection over the diff (schema patterns, auth patterns, shared file patterns, breaking change patterns), checks PR completeness, loads the WO spec and extracts the acceptance criteria, aggregates all signals into a summary, and sends everything to Claude for the advisory. Never exits 1.

**`memory_agent.py`** — Sends the merged diff to Claude with the prompt: "What would NOT be obvious to a fresh agent reading this codebase?" Returns either `NOTHING_TO_REMEMBER` or a structured memory file with YAML frontmatter and a body following the `feedback/project/reference/user` type taxonomy. One memory per PR maximum.

**`observability_agent.py`** — Polls a configurable metrics endpoint, compares `error_rate_pct`, `p99_latency_ms`, and named service statuses against thresholds from `observability_thresholds.json`. On violation, calls Claude to write an incident report in WO Problem format. Exits 1 on any violation, which triggers the observability workflow to create a GitHub issue.

**`factory_status.py`** — Health check tool. Scans the repo for placeholder text, checks for the Makefile, CI workflow, Anthropic secret, GitHub label, branch ruleset, and memory seed. Prints a color-coded status report. Run at any time: `python3 scripts/factory_status.py`.

**`ai_fix.py`** and **`ai_review_apply.py`** — Support scripts for the self-healing CI and review applier workflows respectively. Both use a search-and-replace edit format rather than full-file rewrites to minimize the risk of Claude overwriting code it did not see in context. Both run on `claude-sonnet-4-6` — Opus is not needed for targeted search-and-replace edits and costs ~10x more.

**`pre_pr_check.py`** — Zero-cost static pre-PR checker. Runs as part of `make ci-local`. Checks the diff vs `origin/main` for the same patterns the Claude reviewer looks for: hardcoded secrets, SQL injection, bare `except: pass`, shell `|| true` bypasses, TypeScript `as any` casts, and unguarded external API calls. No API call — pure regex analysis. The goal is to catch obvious issues before the first push, eliminating the push → review → fix → re-review token loop. Project-specific checks can be added in `scripts/pre_pr_checks_project.py`.

---

## The Risk Tier Model

Every work order is assigned one of four risk tiers. The tier determines the merge workflow and cannot be bypassed.

| Tier | Scope | Merge Path |
|------|-------|-----------|
| P0 | Auth, security, multi-tenant data isolation, breaking API contracts | Human must approve and merge — no exceptions |
| P1 | DB schema migrations, new API routes, cross-service interfaces | Human must approve and merge |
| P2 | Feature additions, UI changes, new tests, refactors | Agent enables auto-merge after CI passes |
| P3 | Docs, PM files, comments, typos | Agent commits directly to `main` |

The planning agent (or the AI draft in the factory UI) assigns a tier when creating the WO spec. The human reviewing the spec confirms or adjusts it. From that point, the tier is embedded in the spec and all downstream agents read it before starting work.

The merge advisor's signal summary always includes the risk tier. For P0/P1 PRs, it is the first thing the human reviewer sees.

---

## How AI Code Review Works

The review script builds a two-part system prompt:

**Universal checks (always applied):**
1. Hardcoded secrets — API keys, passwords, tokens in source code
2. Shell `|| true` bypasses — silenced CI failures
3. Bare exception handling — `except:` or `except Exception: pass`
4. Type safety — `any` in TypeScript, untyped Python parameters
5. SQL injection — string-interpolated queries
6. Missing error handling at system boundaries
7. Test coverage blind spots — new business logic without tests

**Project-specific checks** are loaded from `scripts/review_context.txt`. These are numbered plain-text rules that teams write for their own codebase: "Every DB write must call `db.commit()` afterward," "Every new API route must have an auth dependency," "Never read secrets from `os.environ` — use the Vault client." These checks are added as additional rows to the verdict table in the review comment.

The verdict is parsed by anchoring to the `### Verdict` section header and scanning only the lines below it. This avoids false positives from the words "LGTM" or "Needs attention" appearing in code snippets or the Suggestions section above the verdict. If the `### Verdict` section is missing (e.g., response was truncated at the token limit), the script exits 1 rather than silently passing a truncated review.

---

## The PR Lifecycle

Both dashboard-created and GitHub Issues-created WOs follow the same PR lifecycle once the spec is merged into main.

```
WO spec merged to main (via UI-created PR or planning-agent.yml)
         |
         v
Orchestrator picks up WO from PLAN.json queue (next poll cycle)
         |
         v
Agent-runner claims WO, creates branch wo/NNN-slug
         |
         v
Implements the work in a worktree
         |
         v
Quality gate: make ci-local + bandit + semgrep + JS/TS scan
         |
         v
Peer review chain: security → architecture → correctness → performance
         |
         v
Human checkpoint: agent stops, asks user to verify before committing
         |
         v
Agent opens PR with Summary / WO link / Migration notes / Test plan / UI Verification
P2: gh pr merge --auto --squash
         |
    _____|_____
   |           |
   v           v
ai-review    ci.yml
   |           |
   | (if fail) |
   v           v
ai-review-applier   ci-failure-notifier → ci-auto-fix
   |           |
   |___________|
         |
         v
merge-advisor posts recommendation
         |
 P2: auto-merge fires when all checks pass
 P0/P1: human reviews advisory and merges
         |
    _____|_____
   |           |
   v           v
verifier    post-merge-memory
(AC check)  (lesson extraction)
   |           |
   v           v
follow-up    memory PR if
issue if     lesson found
AC not met
         |
         v
Orchestrator dispatches next WO from queue
```

---

## Agent Backends

The agent-runner supports four subscription-based AI backends — no per-token billing:

| Backend | Used for | CLI | Notes |
|---------|----------|-----|-------|
| `claude` | WO execution + peer review | `claude --print` | Claude subscription; `--dangerously-skip-permissions` for agentic run |
| `cursor` | WO execution + peer review | `agent --print` | Cursor subscription |
| `codex` | WO execution + peer review | `codex exec -` | OpenAI Codex subscription |
| `gemini` | WO execution + peer review | `gemini --yolo -p` | Google Gemini subscription |
| `claude-api` | WO spec drafting only | Anthropic SDK | Requires `ANTHROPIC_API_KEY` in secrets vault |

The **draft server** (`draft_server.py`) starts as a daemon thread inside the agent-runner process on port 8101. When the factory UI generates a WO spec using a subscription CLI backend, the orchestrator proxies the request to this server. The server probes which CLIs are installed and available, so the New WO form always shows accurate backend availability.

---

## Setup Time and Requirements

A team with an existing project needs:

- A GitHub repository (create from this template)
- An Anthropic API key from [console.anthropic.com](https://console.anthropic.com) *(for GitHub Actions AI review — the only component that can't use a subscription CLI)*
- macOS with Docker Desktop installed *(for the runtime stack)*
- 15–20 minutes to run through setup

**Setup steps:**

```bash
# 1. Create repo from template
gh repo create your-org/your-project --template dentroio/agentic-factory --private

# 2. One-time credential setup (macOS Keychain)
make agent-setup   # prompts for GitHub token, repo, Slack webhook, Anthropic key

# 3. Start the factory
make up
open http://localhost:8099

# 4. Open Settings → Authentication to verify credentials are live
# 5. Add ANTHROPIC_API_KEY to GitHub repo secrets (for AI review workflows)
```

The setup wizard in `ENGINEER.md` walks through CI workflow, branch protection, AI review context, and memory initialization. Run `python3 scripts/factory_status.py` at any time to see what's done and what's missing.

---

## What You Customize vs. What You Get Out of the Box

| Component | Out of the box | You customize |
|-----------|---------------|---------------|
| AI review universal checks | 7 checks, always applied | Nothing — these run as-is |
| Project-specific review checks | Empty placeholder | `scripts/review_context.txt` — add your invariants |
| Risk tier definitions | P0/P1/P2/P3 defined | Nothing — tiers are universal |
| CI workflow | Template with placeholders | Fill in lint, test, build commands for your stack |
| CD workflow | Template (optional) | Fill in deploy command and health endpoint, or skip |
| Observability thresholds | 1% error rate, 2000ms p99 | `scripts/observability_thresholds.json` |
| WO spec template | Fully defined | Optionally extend `## Execution` section fields |
| Memory taxonomy | 4 types defined | Nothing — extend by adding new memory files |
| Agent process rules | `AGENT_PROCESS.md` §10 placeholder | Replace with your project's code invariants |
| Parallel coordination rules | Defined in §6 | Add your project's shared files to the list |
| Agent backend preference | `claude` default | Settings → Agents in the factory dashboard |

The CI workflow and Makefile are the only required customizations. Everything else has a working default.
