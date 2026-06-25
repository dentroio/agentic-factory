# Agentic Engineering Factory — Technical Architecture

## System Overview

The factory is a collection of GitHub Actions workflows, Python scripts, and configuration files that run entirely within GitHub's infrastructure. There are no external servers, no databases, no message queues, and no proprietary platforms. The only external dependency is the Anthropic API.

### Components and Data Flow

```
GitHub Issues
    |
    | label: 'new-wo'
    v
planning-agent.yml
    |── calls ──> planning_agent.py ──> Anthropic API (claude-sonnet-4-6)
    |<── WO spec markdown ───────────────────────────────────────
    |── git push WO spec to branch ──> GitHub PR opened
    |                                        |
    |                              human reviews & merges
    |                                        |
    |                              Agent reads ## Execution section
    |                                        |
    |                              implements on wo/NNN-slug branch
    |                                        |
    |                              make ci-local (local gate)
    |                                        |
    |                              git push + PR opened
    |
    |── (on push to PR branch) ──> ci.yml (lint / test / build)
    |                                  |
    |                          failure |
    |                                  v
    |                         ci-failure-notifier.yml
    |                              |── downloads job logs
    |                              |── filters to error lines
    |                              └── posts comment on PR
    |                                  |
    |                         (agent PRs only)
    |                                  v
    |                         ci-auto-fix.yml
    |                              |── logs + diff ──> ai_fix.py ──> Anthropic API
    |                              |<── search-and-replace edits ──────────────
    |                              |── applies edits to branch files
    |                              └── git push [ci-autofix] ──> CI re-runs
    |
    |── (on PR open/update) ──> ai-review.yml
    |                              |── git diff origin/main...HEAD (source files only)
    |                              |── diff ──> ai_review.py ──> Anthropic API
    |                              |<── structured review markdown ─────────────
    |                              |── posts review comment on PR
    |                              └── exits 1 if "Review required" (blocks merge)
    |                                  |
    |                         (on ai-review complete)
    |                                  v
    |                         ai-review-applier.yml (agent PRs, "Needs attention" only)
    |                              |── extracts Suggestions section from comment
    |                              |── suggestions + diff ──> ai_review_apply.py ──> Anthropic API
    |                              |<── search-and-replace edits ───────────────────────────
    |                              |── applies edits, git push [ai-review-apply]
    |                              └── AI review re-runs
    |
    |── (on ai-review complete) ──> merge-advisor.yml
    |                              |── reads CI check statuses (GitHub API)
    |                              |── reads AI review verdict from PR comments
    |                              |── runs regex risk detection over diff
    |                              |── loads WO spec, extracts AC + risk tier
    |                              |── all signals ──> merge_advisor.py ──> Anthropic API
    |                              |<── merge advisory markdown ────────────────
    |                              └── posts advisory comment (replaces previous)
    |
    | (merge: P2 auto / P0/P1 human)
    v
    main branch
    |
    |── (on push to main) ──> post-merge-memory.yml
    |                              |── git diff HEAD~1 HEAD (source files only)
    |                              |── diff ──> memory_agent.py ──> Anthropic API
    |                              |<── memory file or NOTHING_TO_REMEMBER ─────
    |                              └── if memory: git push branch ──> PR opened
    |
    |── (on push to main) ──> auto-update-prs.yml
    |                              └── finds behind auto-merge PRs ──> GitHub "Update Branch" API
    |
    |── (on push to main) ──> verifier.yml
    |                              |── finds WO spec from merged PR title
    |                              |── extracts Acceptance Criteria section
    |                              |── AC + diff ──> verifier_agent.py ──> Anthropic API
    |                              |<── verification report ─────────────────────
    |                              |── posts report on merged PR
    |                              └── if "Criteria not met": creates follow-up issue

Scheduled (every 15 minutes):
observability.yml
    |── fetches METRICS_ENDPOINT
    |── checks error_rate_pct, p99_latency_ms, service statuses
    |── if violations: violations ──> observability_agent.py ──> Anthropic API
    |<── incident report markdown ───────────────────────────────────────────
    └── creates GitHub issue labeled 'incident', 'needs-triage'
            |
            | human labels 'new-wo'
            v
    planning-agent.yml  (loop back to top)
```

---

## Workflow Deep Dives

### `ai-review.yml`

**Trigger:** `pull_request` events `opened` and `synchronize` on `main`. Skips `dependabot[bot]`.

**Steps:**
1. Checkout with `fetch-depth: 0` to get full history for the diff.
2. `git diff origin/main...HEAD` filtered to source extensions (`.py`, `.ts`, `.tsx`, `.go`, `.java`, `.rs`) with `node_modules` and `vendor` excluded. Line count written to `GITHUB_OUTPUT`.
3. If line count > 0: install `anthropic`, run `ai_review.py` with `continue-on-error: true`. The `continue-on-error` is critical — it allows the post-review steps to run even when the script exits 1.
4. Post the review as a PR comment via `actions/github-script`. The header changes to include "❌ Review Required (merge blocked)" when the review step outcome was `failure`.
5. If `steps.claude_review.outcome == 'failure'`: `exit 1`. This step has no `continue-on-error` — it is the actual gate.

**Failure modes:**
- `ANTHROPIC_API_KEY` not set: script exits 1 with error message. The gate fires. To suppress on API outage, add `continue-on-error: true` to the gate step (not recommended).
- Diff exceeds 4,000 lines: truncated at that line count with a notice appended to the diff.
- Empty diff (docs-only PR): script writes a hardcoded "No source file changes — LGTM" review and exits 0.

**Required status check name:** `Claude Code Review` (must match the `name:` field in the `jobs.ai-review` stanza exactly).

---

### `planning-agent.yml`

**Trigger:** `issues` event type `labeled`. Conditional: `github.event.label.name == 'new-wo'`.

**Steps:**
1. Determine next WO number by listing `docs/project_management/work_orders/WO-*.md`, extracting the numeric suffix with grep, sorting numerically, and incrementing.
2. Slugify the issue title: lowercase, replace non-alphanumeric with hyphens, truncate at 50 characters.
3. Run `planning_agent.py` with `--title`, `--body`, `--next-wo-num`, `--output`.
4. Create a branch `wo/NNN-spec-draft`, commit the output file, push, and open a PR using `actions/github-script`.

**Output path:** `docs/project_management/work_orders/WO-NNN-${slug}.md`. Configurable via the `WO_SPECS_DIR` repository variable.

**Failure modes:**
- Issue body is empty: script receives `"(no body provided)"` and still produces a spec (lower quality).
- WO directory does not exist: `os.makedirs` in the script creates it.
- Concurrent labels: if two issues are labeled `new-wo` within the same GitHub Actions queue, both runs compute the same next WO number. The second push will fail because the branch already exists. The second run can be manually re-triggered.

---

### `verifier.yml`

**Trigger:** `pull_request` event type `closed` on `main`. Conditional: `merged == true` AND `title contains 'WO-'`.

**Steps:**
1. Checkout with `fetch-depth: 0`.
2. `git diff base_sha...merge_commit_sha` to get exactly what merged.
3. Run `verifier_agent.py` with `--pr-title` (used to discover the WO spec file) and `--diff`.
4. Post the verification report as a comment on the merged PR.
5. If `steps.verify.outcome == 'failure'`: create a follow-up GitHub issue with `bug` and `needs-triage` labels. The issue body includes the full verification report and instructions to label it `new-wo`.

**WO spec discovery:** `verifier_agent.py` parses `WO-(\d+)` from the PR title, then scans the WO directory for a file matching `WO-NNN-*.md`. If not found, the script writes a "no spec found" report and exits 0 (non-blocking).

**Verdict parsing:** Same bottom-up scan as `ai_review.py` — scans reversed lines for `"Criteria not met"`, then `"All criteria met"` or `"Partial"`. Exits 1 only on explicit `"Criteria not met"` match.

---

### `ci-failure-notifier.yml`

**Trigger:** `workflow_run` on the `CI` workflow, type `completed`.

**Steps:**
1. Find the open PR for the failing branch using `pulls.list` filtered by branch name.
2. Fetch failed jobs from `actions.listJobsForWorkflowRun`.
3. Download logs for up to 2 failed jobs. Filter log lines to those matching error/failure patterns, excluding `node_modules` and deprecation warnings. Truncate to 30 key lines per job and 8,000 characters total.
4. Delete any previous `## ⚠️ CI Failure` comment on the PR (replace, don't stack).
5. Post the failure comment with job name, failed step name, filtered log excerpt, and full run URL.

**No AI call in this workflow** — it is a pure log-relay. Cheap to run, reliable, no API dependency.

---

### `ci-auto-fix.yml`

**Trigger:** `workflow_run` on `CI`, type `completed`, conclusion `failure`.

**Guard rails (all checked before any API call):**
- HEAD commit message contains `[ci-autofix]` → stop immediately (loop guard).
- No open PR found for the branch → stop.
- PR is not an agent PR (no `agent-pr` label, not a known bot account) → stop.
- PR has `ci-autofix-failed` label (hit the 2-attempt limit) → stop, post manual-fix comment.
- Any failed job name matches `/build/i` → skip fix (structural issues need human).
- Diff touches more than 10 files → skip fix (too complex).

**Fix application:** `ai_fix.py` outputs a JSON result with `can_fix` (bool), `applied_files` (list), `summary` (str), and `reason` (str). Edits use a search-and-replace format — Claude outputs the exact string to find and its replacement. The script applies each edit to the actual file on disk before the workflow commits. If `can_fix` is false or `applied_files` is empty, the workflow posts the fallback failure comment instead.

**Attempt tracking:** First attempt adds label `ci-autofix-attempted`. Second attempt (label already present) adds `ci-autofix-failed`. The `ci-autofix-failed` label is the permanent stop signal. Remove it manually to re-enable auto-fix on a PR.

---

### `merge-advisor.yml`

**Trigger:** `workflow_run` on `AI Code Review`, type `completed`. Conditional: triggering event was `pull_request`, actor is not Dependabot.

**Signal collection:**
- CI status: fetches all check runs for the HEAD SHA, counts failures excluding `Merge Advisory` itself.
- AI review verdict: scans PR comments for bodies starting with `## 🤖 AI Code Review`, looks for `**LGTM**`, `**Needs attention**`, or `**Review required**`.
- Verifier verdict: scans for `Post-Merge Verification` comments (pre-merge verifier runs are rare but supported).
- Diff risk indicators: regex-based detection for schema patterns, auth patterns, shared file patterns, breaking change patterns.
- PR completeness: regex checks on title and body for WO reference, migration notes, test plan mention, body length, co-author tag.
- WO spec: discovered by `WO-NNN` in PR title, acceptance criteria extracted if found.

**Advisory post:** Replaces any previous `## 🔀 Merge Advisory` comment (avoids stacking on force-push cycles). Always exits 0 — the advisor is never a gate.

---

### `post-merge-memory.yml`

**Trigger:** `push` to `main`. Conditional: HEAD commit message does not contain `memory(auto)` (loop guard).

**Memory file format:**
```
---
name: short-kebab-slug
description: one-line summary for relevance matching
metadata:
  type: feedback | project | reference | user
---

Body text: the lesson, with "Why:" and "How to apply:" lines for feedback/project types.
```

**File naming:** `auto_{slug}.md` where slug is derived from the WO number in the PR title (`wo042`) or from slugifying the commit message. Collision-safe: appends `_2`, `_3`, etc. if the name is taken.

**Non-blocking by design:** The memory agent script always exits 0. A missing API key, an empty diff, and a `NOTHING_TO_REMEMBER` response are all handled gracefully. Memory failure never fails the merge.

---

### `observability.yml`

**Trigger:** Schedule `*/15 * * * *` (every 15 minutes). Also supports `workflow_dispatch` for manual testing.

**Threshold checks (in order):**
1. Endpoint unreachable (fetch error) → violation.
2. `status` field not in `("ok", "healthy", "up", None)` → violation.
3. `error_rate_pct` or `error_rate` exceeds `thresholds.error_rate_pct` → violation.
4. `p99_latency_ms` or `latency_p99_ms` exceeds `thresholds.p99_latency_ms` → violation.
5. Named services in `thresholds.unhealthy_services` with non-healthy status → violation.

**On violation:** Calls Claude to write an incident report in `## Problem / ## Suggested Investigation` format (under 300 words). Creates a GitHub issue with `incident` and `needs-triage` labels. The issue body instructs the reader to label it `new-wo` to trigger the planning agent — closing the full SDLC loop from production anomaly to implementation.

**`--no-ai` flag:** The `observability_agent.py` script accepts `--no-ai` to skip the Claude call and write a raw violation list. Useful for testing threshold detection without an API key.

---

## The Verdict System in `ai_review.py`

### Prompt design

The system prompt is composed in two parts: `UNIVERSAL_CHECKS` (always present) and `project_section` (injected when `review_context.txt` exists or `PROJECT_REVIEW_CONTEXT` env var is set). The project section instructs Claude to add additional rows to the verdict table.

The response format is prescribed exactly in `RESPONSE_FORMAT`. Claude is told to return a `### Summary`, a `### Checks` table, a `### Suggestions` section, and a `### Verdict` section in that order. The verdict must be exactly one of `**LGTM**`, `**Needs attention**`, or `**Review required**`.

### Anchored verdict parsing

The verdict is parsed by anchoring to the `### Verdict` section header, then scanning only the lines below it:

```python
lines = review.splitlines()
verdict_start = next(i for i, ln in enumerate(lines) if ln.strip() == "### Verdict")
verdict_lines = lines[verdict_start:]
for line in verdict_lines:
    if "Review required" in line:
        sys.exit(1)
    if "Needs attention" in line:
        sys.exit(0)
    if "LGTM" in line:
        sys.exit(0)
```

Anchoring to the section header prevents false positives when the words "LGTM" or "Needs attention" appear in code snippets or the Suggestions section earlier in the review. If the `### Verdict` section is missing (response was truncated at the token limit), the script exits 1 rather than silently passing a truncated review. The token limit is set to 2048 to accommodate large diffs, and `stop_reason == "max_tokens"` is checked before parsing.

### Exit code semantics

- `0` — LGTM or Needs attention. Needs attention is informational — the `ai-review-applier.yml` may auto-apply the suggestions, but merge is not blocked.
- `1` — Review required (any ❌ failure in the Checks table). The workflow step fails (`continue-on-error: true` allows downstream steps to run). The final gate step (`if: steps.claude_review.outcome == 'failure'`) then runs `exit 1` without `continue-on-error`, which is what actually fails the required status check in GitHub.

This two-step exit code design is necessary because GitHub Actions marks a job as failed when any step exits non-zero — but with `continue-on-error: true`, you can continue and still post the review comment before failing the job.

### Token cost management

Three mechanisms keep API costs low:

1. **Skip auto-generated commits.** The `ai-review.yml` workflow checks the HEAD commit message before making any API call. Commits tagged `[pr-watch-fix]`, `[ai-review-apply]`, or `[ci-autofix]` are auto-generated by the factory itself and were already reviewed on the prior push. Reviewing them again adds no value.

2. **Cancel superseded reviews.** The workflow uses `concurrency: cancel-in-progress: true` scoped to the PR number. If a developer pushes two commits in quick succession, the first in-progress review is cancelled before the Anthropic API call completes.

3. **Sonnet for fix scripts.** `ai_fix.py` and `ai_review_apply.py` both run on `claude-sonnet-4-6`. These scripts produce targeted search-and-replace edits, not architectural reasoning — Opus is not needed and costs ~10x more per call.

### Pre-PR static check (`pre_pr_check.py`)

`scripts/pre_pr_check.py` runs as part of `make ci-local` and checks the same patterns as the Claude reviewer — without making an API call. It analyzes the `git diff origin/main...HEAD` for hardcoded secrets, SQL injection, bare `except: pass`, shell `|| true` bypasses, TypeScript `as any` casts, and unguarded external API calls.

The goal is to eliminate the push → Claude review finds issue → fix → re-review loop. If `pre_pr_check.py` finds a problem, the agent fixes it locally in the same session and never pushes the broken code. The Claude review then sees clean code and returns LGTM in one pass.

Project-specific checks (e.g. "every DB write must call `db.commit()`") can be added without modifying the core script. Create `scripts/pre_pr_checks_project.py` with a `project_checks(diff: str) -> list[CheckResult]` function; the runner imports it automatically.

---

## The Memory System

### Structure

The `memory/` directory contains flat markdown files with YAML frontmatter. The `MEMORY.md` index file in the same directory is the entry point that Claude Code reads at the start of every conversation. It contains one-line pointers to the individual topic files.

Each memory file has:
- `name`: kebab-case slug used for collision avoidance
- `description`: one-line summary that Claude uses to decide whether the memory is relevant to the current task
- `metadata.type`: `feedback` (a behavioral rule), `project` (a fact about the codebase or program), `reference` (where to find something), or `user` (preferences)

### Automatic extraction

`memory_agent.py` is prompted to identify things that are "non-obvious or surprising" and that a fresh agent reading the codebase would not discover. This framing prevents the agent from writing memories about what the PR did (that is already in git log) and steers it toward hidden invariants, pitfalls, and non-obvious constraints.

The instruction "one memory per PR maximum — pick the most important" prevents the memory directory from filling with low-signal entries.

### Human review gate

Every auto-extracted memory goes through a PR before landing in `main`. The PR body presents three options: merge as-is, edit to rename and improve, or close without merging. This gate prevents low-quality or incorrect memories from accumulating in the persistent store.

### Compounding effect

Over time, the memory directory becomes the project's institutional knowledge base. Each entry reduces the probability that a future agent makes the same mistake or asks the same question. A project with 50–100 memory entries has a measurably different quality floor than one where agents start cold.

---

## The Observability Agent

The observability agent is a pull-based health monitor. It does not receive push notifications — it polls the configured endpoint every 15 minutes and compares the response against configurable thresholds.

**Endpoint contract:** The endpoint must return JSON. It should include at minimum a `status` field. Optional but supported: `error_rate_pct`, `p99_latency_ms`, and a `services` object with named service statuses. If your health endpoint does not match these field names exactly, the threshold check returns no violations (endpoint reachability is still checked).

**Threshold file format:**
```json
{
  "error_rate_pct": 1.0,
  "p99_latency_ms": 2000,
  "unhealthy_services": ["database", "cache"]
}
```

**Incident issue lifecycle:** The issue is labeled `incident` and `needs-triage`. A human (or automated rule) labels it `new-wo` to trigger the planning agent. The planning agent drafts a WO spec for the incident. The spec is reviewed and merged. An agent picks up the `## Execution` section and implements the fix. The verifier checks the acceptance criteria post-merge. This is the full SDLC loop closing on a production signal.

---

## How to Extend the Factory

### Adding a project-specific CI check

1. Add the job to `.github/workflows/ci.yml`.
2. Add the corresponding step to `make ci-local` in `Makefile`.
3. Add the job `name:` to the required status checks in the GitHub Ruleset. The name must match exactly.
4. Add a note to `AGENT_PROCESS.md §9` so agents know what to expect from CI.

### Adding a project-specific AI review check

Add a numbered item to `scripts/review_context.txt`. The format is plain text — be specific. "Every DB write must call `db.commit()` after `execute()`" is useful. "Follow best practices for database operations" is not.

These checks are injected into the system prompt as `PROJECT-SPECIFIC CHECKS` and appear as additional rows in the verdict table alongside the seven universal checks.

### Adding a custom agent

1. Write a Python script in `scripts/` following the same pattern: parse arguments, check for `ANTHROPIC_API_KEY`, call `anthropic.Anthropic().messages.create()`, write output to `--output`, exit 0 or 1 based on outcome.
2. Create a workflow in `.github/workflows/` that installs `anthropic`, calls the script, and handles the output (post comment, create issue, open PR, etc.).
3. If the workflow should block merge, register its job `name:` as a required status check in the GitHub Ruleset.

### Replacing Claude with another model

All scripts use `model="claude-sonnet-4-6"`. Change this string in each script. The scripts use the Anthropic SDK directly — to use a different provider, replace the `anthropic.Anthropic()` client with the appropriate SDK and adjust the `messages.create()` call signature.

### Extending the WO spec format

The WO template is defined in `scripts/planning_agent.py` as `WO_TEMPLATE`. Add fields to the template and update the `SYSTEM_PROMPT` to instruct Claude to fill them in. Also update `AGENT_PROCESS.md §4` so human reviewers know what to expect in the spec.

---

## Security Model

### Secrets

One secret is required: `ANTHROPIC_API_KEY`, stored in GitHub repository secrets under Settings → Secrets and variables → Actions. It is read in the workflows as `${{ secrets.ANTHROPIC_API_KEY }}` and passed to scripts via environment variable.

The `GITHUB_TOKEN` used by `actions/github-script` is the automatic token GitHub provisions per workflow run. Its permissions are declared explicitly in each workflow's `permissions:` block — the factory uses the minimum necessary permissions for each workflow.

### What the agents can do

- Read repository files (via checkout).
- Write to PR branches (via `git push` with `GITHUB_TOKEN` write permission).
- Post PR comments and create issues (via `GITHUB_TOKEN` with `pull-requests: write` and `issues: write`).
- Call the Anthropic API with the repository's API key.
- Call the configured health endpoint (outbound HTTP from GitHub Actions runners).

### What the agents cannot do

- Read the value of repository secrets (GitHub does not expose secret values via API).
- Push directly to `main` (blocked by the branch ruleset).
- Merge PRs that require human approval (P0/P1 tiers — auto-merge is not enabled for these).
- Access external systems not explicitly configured (no database access, no cloud provider credentials).

### Prompt injection risk

The workflows pass PR titles, PR bodies, issue titles, and issue bodies into Claude prompts. A malicious actor could craft an issue title or PR body containing instructions intended to manipulate the agent's output. Mitigations:

- The planning agent and code reviewer use `system` prompts with explicit output format instructions. Deviations from the format produce output that fails to parse correctly (non-blocking) or produces a clearly unusual review (visible to the human reviewer).
- The verifier, memory agent, and merge advisor all produce output that is posted as a comment for human visibility. Injected instructions would produce visible anomalies.
- No workflow takes automated action based purely on AI output without a loop guard (commit message tags, label checks) that limits the blast radius of a runaway loop.

---

## Known Limitations and Trade-offs

**Diff truncation.** All scripts truncate diffs at 2,000–4,000 lines. Very large PRs receive partial reviews. The mitigation is process: large PRs should be split into smaller ones. The factory does not enforce PR size but the AI review comment notes when truncation occurred.

**WO spec discovery is title-based.** The verifier and merge advisor find the linked WO spec by parsing `WO-NNN` from the PR title. PRs that do not follow the title convention are not linked to their specs. Enforce the title convention in `AGENT_PROCESS.md §8` and the PR template.

**Observability is polling, not streaming.** The 15-minute schedule means anomalies can go undetected for up to 15 minutes. For stricter SLOs, reduce the cron interval or supplement with a webhook-based alerting system that calls the workflow via `workflow_dispatch`.

**CI auto-fix is bounded.** The 2-attempt limit on `ci-auto-fix.yml` is intentional. Without it, a flaky test or an environment-specific failure could run up significant API costs. The limit means some CI failures require human intervention.

**Memory is not searched semantically.** The `MEMORY.md` index and individual memory files are read by Claude Code at the start of each conversation, but the agent does not perform a semantic search across all memory files during a task. The `description` field in each file's frontmatter is the signal Claude uses to decide relevance. Keep descriptions specific and accurate.

**No merge queue.** The `auto-update-prs.yml` workflow approximates GitHub Merge Queue behavior (available on Team/Enterprise plans) by updating behind branches on every push to `main`. Under high concurrency — many agent PRs merging in quick succession — there can be a brief window where a PR merges on a stale SHA. The required status checks mitigate this: a PR must have passing checks on its HEAD SHA to merge.

**Agent PR detection is heuristic.** `ci-auto-fix.yml` and `ai-review-applier.yml` identify agent PRs by the `agent-pr` label or by checking if the PR author is in a hardcoded list of bot accounts (`github-actions[bot]`, `claude-code-bot`). Add your agent account usernames to this list in both workflows.
