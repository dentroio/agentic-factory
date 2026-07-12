---
title: "GitHub Integrations"
description: "Automated code review, planning, verification, and observability via GitHub Actions workflows"
last_verified: 2026-07-11
covers_wos: []
doc_owner: factory-team
---

# GitHub Integrations

The factory's GitHub Actions layer provides automated code review, planning, post-merge verification, and observability. These workflows run on GitHub's infrastructure — no local factory stack required.

All AI-calling workflows require `ANTHROPIC_API_KEY` in your GitHub repo secrets (**Settings → Secrets and variables → Actions → New repository secret**).

## planning-agent.yml

**Trigger:** Any GitHub issue labeled `new-wo`.

The planning agent converts the issue title and body into a structured WO spec. It calls Claude with the issue content and the next available WO number, producing a filled-in markdown spec with title, priority, effort, problem statement, and acceptance criteria.

The workflow creates a branch `wo/NNN-spec-draft`, commits the spec file, and opens a PR. You review the spec, make any edits, and merge. Once merged, the orchestrator picks up the WO on its next poll cycle.

This is one of three ways to create a WO (alongside the factory UI and the PM chat). The spec format and dispatch behavior are identical regardless of which path you use.

## dependabot-wo-bridge.yml

**Trigger:** A Dependabot PR's CI fails.

When a Dependabot dependency update breaks CI, this workflow automatically creates a `new-wo` labeled GitHub issue describing the failing PR and the nature of the failure. That label triggers `planning-agent.yml`, which drafts a WO spec for investigating and fixing the dependency issue.

The result: dependency failures that need human attention automatically enter the WO queue rather than silently sitting on a failing PR. See the PM chat section on [managing Dependabot PRs](PM-Chat.md) for how to handle these via chat.

## ai-review.yml

**Trigger:** Pull request opened or updated on `main`. Skips Dependabot PRs.

Diffs source files against `main` (`.py`, `.ts`, `.tsx`, `.go`, `.java`, `.rs`), calls Claude with seven universal checks plus your project-specific checks from `scripts/review_context.txt`, and posts the review as a PR comment.

The review produces one of three verdicts:
- **LGTM** — all checks pass, merge is not blocked
- **Needs attention** — issues noted, but merge is not blocked; the `ai-review-applier.yml` workflow may auto-apply suggestions
- **Review required** — one or more checks failed; merge is blocked until the issues are fixed

The `Claude Code Review` status check must be listed in your GitHub Ruleset required checks for the block to take effect.

Diffs exceeding 4,000 lines are truncated with a notice. Empty diffs (docs-only PRs) get an automatic "No source file changes — LGTM."

## verifier.yml

**Trigger:** A PR is merged to `main` and the PR title contains `WO-`.

After merge, the verifier reads the acceptance criteria from the linked WO spec and checks them against the merged diff. It posts a verification report as a comment on the merged PR.

If any acceptance criteria are marked "not met," the workflow creates a follow-up GitHub issue with `bug` and `needs-triage` labels. The issue body includes the full verification report and instructions to label it `new-wo` to trigger the planning agent — closing the loop from implementation back to planning.

The verifier is non-blocking. A failed verification creates an issue but does not revert the merge.

## post-merge-memory.yml

**Trigger:** Push to `main`. Skips commits tagged `memory(auto)` to prevent loops.

After every merge, the memory agent analyzes the diff and extracts "non-obvious or surprising" lessons — invariants, pitfalls, hidden constraints — that a fresh agent would not discover from the codebase alone.

If it finds something worth recording, it writes a memory file and opens a PR. The memory PR body presents three options: merge as-is, edit before merging, or close without merging. This human review gate prevents low-quality entries from accumulating.

If there is nothing to learn, the workflow exits cleanly without creating anything.

## merge-advisor.yml

**Trigger:** The AI code review workflow completes. Skips Dependabot PRs.

The merge advisor synthesizes all available signals and posts a merge recommendation comment:

- CI check status (passing/failing/pending)
- AI review verdict (LGTM / Needs attention / Review required)
- Regex-based risk detection over the diff (schema patterns, auth changes, shared file edits)
- PR completeness (WO reference, migration notes, test plan, body length)
- Acceptance criteria from the linked WO spec

The advisor posts ✅, ⚠️, or ❌ with an explanation. It always exits 0 — it is advisory, never a gate. Previous advisory comments are replaced on each update.

## ci-failure-notifier.yml

**Trigger:** The CI workflow fails.

When CI fails on a PR, this workflow finds the open PR for the failing branch, downloads the failed job logs, filters them to error/failure lines (excluding `node_modules` and deprecation warnings), and posts a comment on the PR with the job name, failed step, filtered log excerpt, and a link to the full run.

This workflow makes no AI calls — it is pure log relay. The goal is to give the agent (or you) the exact error without clicking into GitHub Actions.

## ai-review-applier.yml (auto-fix loop)

**Trigger:** The AI code review completes with a "Needs attention" verdict on an agent PR.

Extracts the Suggestions section from the AI review comment, sends the suggestions plus the diff to Claude, and receives search-and-replace edits. The workflow applies the edits to the branch and pushes them with a `[ai-review-apply]` commit tag. The AI review runs again on the new push.

This workflow only runs on agent PRs (identified by the `agent-pr` label or bot account username). It has a loop guard: commits tagged `[ai-review-apply]` do not trigger it again.

## auto-update-prs.yml

**Trigger:** Push to `main`.

When a commit lands on `main`, finds all open PRs that have auto-merge enabled and are behind `main`, then triggers GitHub's "Update Branch" on each. This merges `main` into the PR branch, which kicks off a fresh CI run. When CI passes, auto-merge fires automatically.

This closes the gap created by strict branch protection (branches behind `main` are blocked from merging). Without it, an agent's PR would sit waiting indefinitely after other PRs merged ahead of it.

## ci-auto-fix.yml

**Trigger:** CI fails on a PR labeled `agent-pr` or authored by a known bot account.

When CI fails on an agent PR, this workflow downloads the failure logs, fetches the PR diff, and calls Claude asking for a minimal patch to fix the failure. If Claude is confident about a fix, it applies search-and-replace edits to the branch files, commits with a `[ci-autofix]` tag, and pushes. CI re-runs automatically.

If Claude cannot determine a safe fix (complex logic, structural failure, low confidence), it falls back to posting a comment with the failure details.

Guard rails:
- Maximum 2 auto-fix attempts per PR (tracked via labels on the PR)
- `[ci-autofix]` commit tag prevents the workflow from triggering on its own commits
- Skips build failures — structural issues need human attention
- Only runs on agent PRs

## observability.yml

**Schedule:** Every 15 minutes. Also supports manual `workflow_dispatch`.

Polls the configured `METRICS_ENDPOINT` and compares the response against configurable thresholds in `scripts/observability_thresholds.json`:

```json
{
  "error_rate_pct": 1.0,
  "p99_latency_ms": 2000,
  "unhealthy_services": ["database", "cache"]
}
```

On a threshold violation, the observability agent calls Claude to write a concise incident report, then creates a GitHub issue labeled `incident` and `needs-triage`. The issue body instructs the reader to add the `new-wo` label to trigger the planning agent — feeding the anomaly into the WO workflow.

## Required GitHub secrets

| Secret | Required by |
|--------|------------|
| `ANTHROPIC_API_KEY` | `ai-review.yml`, `planning-agent.yml`, `verifier.yml`, `post-merge-memory.yml`, `merge-advisor.yml`, `observability.yml`, `ai-review-applier.yml` |

`GITHUB_TOKEN` is provisioned automatically per workflow run — you do not need to set it.

## Required GitHub Ruleset configuration

For the AI code review block to enforce merge protection, add these as required status checks in your GitHub Ruleset (**Settings → Rules → Rulesets → New ruleset**):

- `Claude Code Review`
- `Secret Detection (Gitleaks)` (if using Gitleaks in CI)
- Any CI jobs (`Lint`, `Unit Tests`, `Build`) you want as gates

Status check names must match the `name:` field in the workflow job exactly.
