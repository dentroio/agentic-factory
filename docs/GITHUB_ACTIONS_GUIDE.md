# GitHub Actions & PR Workflow Guide

**For people who are new to the AI factory, GitHub Actions, pull requests, and merges.**

---

## What Is GitHub Actions?

Think of GitHub Actions as a **robot assistant that watches your repository and automatically runs jobs** whenever something happens — like when you push code or open a pull request.

You write instructions for that robot in YAML files stored in `.github/workflows/`. Every time a trigger event happens (a PR opens, code is pushed, etc.), GitHub spins up a fresh computer in the cloud, runs your instructions, and reports back with ✅ pass or ❌ fail.

The key insight: **these robots run on GitHub's servers, not your machine.** Your local laptop is never involved. GitHub runs them for free (within limits) on every PR.

---

## The Big Picture: What Happens When an Agent Opens a PR

Here's the full sequence from "agent pushes code" to "code is on main":

```
Agent pushes branch + opens PR
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  CI (ci.yml) runs 5 checks in parallel:      │
    │    1. Secret Detection (Gitleaks)             │
    │    2. Lint (Black + Ruff)                    │
    │    3. Unit Tests (pytest)                    │
    │    4. Frontend (TypeScript + build)           │
    │    5. Migration Safety                        │
    └──────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  AI Code Review (ai-review.yml)              │
    │    Claude reads the diff → posts a comment   │
    │    Verdict: LGTM / Needs attention / ❌ Block │
    └──────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  Self-Healing (if needed):                   │
    │    • CI failed? → ci-auto-fix.yml tries fix  │
    │    • AI said "Needs attention"?              │
    │      → ai-review-applier.yml patches code    │
    └──────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  Merge Advisor (merge-advisor.yml)           │
    │    Reads all signals → posts one clear       │
    │    recommendation: ✅ merge / ⚠️ review / ❌  │
    └──────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  Merge Decision                              │
    │    P1: Human clicks Merge after reviewing    │
    │    P2: Auto-merge fires when all checks pass │
    └──────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │  After merge on main:                        │
    │    • auto-update-prs.yml keeps other         │
    │      branches current with main              │
    └──────────────────────────────────────────────┘
```

---

## Each Workflow Explained

### 1. `ci.yml` — The Gate (Runs on Every PR)

**What it does:** Checks that the code is correct before anyone merges it.

**Trigger:** Any PR opened or updated against `main`. Also runs on every push to `main`.

**The 5 checks it runs (all in parallel, so it's fast):**

| Check | What it looks for |
|-------|-------------------|
| **Secret Detection** | Scans every commit for passwords, API keys, tokens accidentally committed. Uses Gitleaks. If it finds one, the PR is blocked hard. |
| **Lint** | Runs Black (Python formatter) and Ruff (Python linter). If your code isn't formatted correctly or has style violations, it fails. |
| **Unit Tests** | Runs `pytest tests/unit/`. If any test fails, the PR is blocked. |
| **Frontend** | Runs TypeScript type-check + test + build on the React frontend. |
| **Migration Safety** | Verifies every new database migration file is registered in `adapter.py`. This prevents "migration exists but never runs" bugs. |

**The Gate job:** After all 5 checks finish, a final "PR Gate" job collects their results. If any single check failed, Gate fails. The GitHub Ruleset requires Gate to pass before merge is allowed — this is what actually blocks the merge button.

**Key point:** CI runs **code quality checks only**. It does NOT deploy anything. It runs on GitHub's cloud servers — your Docker containers are never touched.

---

### 2. `ai-review.yml` — Claude Reads Your Code (Runs on Every PR)

**What it does:** Claude reads the diff of your PR and posts a structured code review comment.

**Trigger:** Any PR opened or updated against `main`.

**What Claude checks:**
- Security issues (SQL injection, hardcoded secrets, missing auth)
- Logic bugs and edge cases
- Whether the code matches Clarion's patterns (db.commit(), require_role(), etc.)
- Anything that looks risky or incomplete

**Three possible verdicts:**

| Verdict | Meaning | Effect on merge |
|---------|---------|----------------|
| **LGTM** | Code looks good | No block — merge can proceed |
| **Needs attention** | Minor issues found | Advisory only — merge still allowed |
| **Review required** | Critical issues found | CI job exits with failure code — **blocks merge** |

**Cost:** About $0.01–0.05 per PR. (Claude reads ~4,000 tokens of diff per review.)

---

### 3. `ai-review-applier.yml` — Claude Fixes Its Own Suggestions

**What it does:** When the AI review says "Needs attention," this workflow reads the suggestions and automatically applies the code fixes, then commits back to the branch.

**Trigger:** Runs right after `ai-review.yml` completes (only on agent PRs — not human PRs).

**What happens step by step:**
1. Reads the "Suggestions" section from the AI review comment
2. Calls Claude with the suggestions + the current diff
3. Claude generates search-and-replace edits (not full file rewrites)
4. The edits are applied to the checked-out branch files
5. A new commit is pushed: `refactor(ai-review): apply review suggestions [ai-review-apply]`
6. CI re-runs automatically on the new commit
7. If the new review is LGTM → auto-merge fires

**Guard rails:**
- Only runs once per review cycle (the `[ai-review-apply]` tag in the commit message stops the loop)
- Only runs on agent PRs (human PRs are reviewed by humans, not auto-patched)
- If suggestions require human judgment, it posts a comment saying so instead of guessing

---

### 4. `ci-auto-fix.yml` — Self-Healing CI

**What it does:** When CI fails on an agent PR, Claude reads the failure logs and tries to fix the code automatically.

**Trigger:** Runs right after `ci.yml` completes with a failure (only on agent PRs).

**What happens:**
1. Downloads the logs from the failed CI job
2. Gets the PR's code diff
3. Calls Claude: "Here are the failures, here is the code that changed — what's the minimal fix?"
4. Claude generates search-and-replace edits
5. Commits and pushes: `fix(ci): auto-fix CI failure [ci-autofix]`
6. CI re-runs automatically

**Guard rails:**
- Maximum 2 auto-fix attempts per PR (tracked via labels `ci-autofix-attempted` and `ci-autofix-failed`)
- Skips build failures (those need human attention — Claude can't fix broken imports or missing files blindly)
- Skips if the PR touches more than 10 files (too complex to auto-fix safely)
- The `[ci-autofix]` tag in the commit message stops infinite loops

**What you'll see on a PR:** If auto-fix is applied, a comment appears: "🤖 CI Auto-Fix Applied — CI is now re-running." If the limit is reached: "❌ CI Auto-Fix Limit Reached — Manual Fix Required."

---

### 5. `merge-advisor.yml` — One Clear Merge Recommendation

**What it does:** After the AI code review runs, the merge advisor collects all signals and posts a single synthesized recommendation to help the human reviewer decide.

**Trigger:** Runs right after `ai-review.yml` completes.

**Signals it reads:**
- Did CI pass or fail? (all 5 checks)
- What was the AI review verdict? (LGTM / Needs attention / Review required)
- Did a previous verifier find any unmet acceptance criteria?
- What does the diff look like? (risk indicators)

**Three possible outputs:**

| Output | Meaning |
|--------|---------|
| ✅ Ready to merge | All signals green — includes a checklist of what to spot-verify |
| ⚠️ Review before merging | Something looks off — specific concerns listed |
| ❌ Do not merge | A check failed or the AI review found critical issues |

**Important:** The merge advisor **never blocks the merge itself** — it only advises. Actual blocking is done by `ci.yml` and `ai-review.yml`. The advisor is there to give the human a fast, clear answer instead of having to read 5 different check results.

---

### 6. `auto-update-prs.yml` — Keeping Branches Current

**What it does:** Every time a commit lands on `main`, this workflow finds all open PRs that have auto-merge enabled and merges the new main into each of those branches automatically.

**Why this matters:** If three agents are working in parallel on branches A, B, and C, and branch A merges first, branches B and C are now "behind main." This workflow automatically catches them up so they always include the latest code.

**Trigger:** Any push to `main`.

**Conflict handling:**
- Clean merge → pushed automatically
- Only `PROGRESS.md` conflicts → resolved automatically (main's version wins)
- Any other conflict → skipped with a comment; agent must resolve manually

---

## Understanding Pull Requests

### What is a Pull Request?

A **pull request (PR)** is a proposal to merge code from your working branch into `main`.

It's called a "pull request" because you're asking the repository to "pull" your changes in. When you open one, GitHub:
- Shows a visual diff of everything you changed
- Runs all the Actions workflows above
- Creates a place for comments and review
- Shows whether all checks pass

### The PR Lifecycle in This Project

1. **Agent creates a branch** — e.g., `wo/288-network-ai-agent`
2. **Agent commits code** to that branch
3. **Agent opens a PR** with `gh pr create`
4. **CI runs** (all 5 checks in parallel, ~9 minutes)
5. **AI review runs** (posts a review comment)
6. **Self-healing kicks in** if needed (auto-fix or review applier)
7. **Merge advisor posts** a recommendation
8. **Merge happens** — either auto (P2) or human approves (P1)
9. **Branch is deleted** after merge
10. **auto-update-prs.yml fires** to update other open branches

---

## Merge vs. Squash Merge — What's the Difference?

This is one of the most confusing things for people new to Git. Here's the simple version.

### Regular Merge

When you merge a branch normally, **every individual commit from the branch is added to main's history.**

```
Before:
  main:    A --- B --- C
                       \
  branch:               D --- E --- F

After regular merge:
  main:    A --- B --- C --- D --- E --- F --- [merge commit]
```

You can see every individual step the agent took — every "fix typo," "refactor," "attempt 1," etc.

### Squash Merge

When you squash merge, **all commits on the branch are compressed into ONE commit on main.**

```
Before:
  main:    A --- B --- C
                       \
  branch:               D --- E --- F

After squash merge:
  main:    A --- B --- C --- DEF
                              ↑
                     One clean commit summarizing the whole branch
```

The individual D, E, F commits disappear from main's history. Only the one clean summary commit appears.

### Why This Project Uses Squash Merge

This project always squash-merges PRs. Here's why:

1. **Clean history.** An agent might make 15 commits while iterating on a feature ("add route," "fix lint," "fix test," "add missing import"). Squashing makes main's git log a clean list of features and fixes, not a journal of debugging steps.

2. **Easy to revert.** If a feature has a problem, you can `git revert` exactly one commit instead of hunting through 15 to figure out which ones to revert.

3. **The branch is the unit of work.** A work order = a branch = one squash commit on main. The mapping is clean.

4. **The detail is still available.** The individual commits still exist on the feature branch (until GitHub deletes it after merge). If you need to see step-by-step history, look at the PR — it shows all the commits before they were squashed.

### What "Auto-Merge with Squash" Means

For P2 work orders, agents run:
```bash
gh pr merge --auto --squash
```

This tells GitHub: "When all required checks pass, automatically squash-merge this PR — no human needs to click anything."

The merge will fire the moment:
- All required CI checks pass (Gate job = green)
- The AI review doesn't say "Review required"

For P1 work orders, auto-merge is **not** used. A human must review the PR and click the merge button themselves. The merge advisor comment helps them make that decision quickly.

---

## Required Checks (Branch Protection)

GitHub has a **ruleset** configured on `main` that lists the checks that MUST pass before merge is allowed. No one — not even an admin — can bypass these.

The required checks on `main`:

| Check name | What must pass |
|------------|----------------|
| `Secret Detection (Gitleaks)` | No secrets found in commits |
| `Lint` | Black + Ruff clean |
| `Unit Tests` | All pytest tests pass |
| `Frontend (TypeScript + Build)` | tsc + npm test + npm build clean |
| `Migration Safety Check` | All migration files registered in adapter.py |
| `Claude Code Review` | AI review did not exit with "Review required" |
| `PR Gate` | All of the above via the gate aggregator job |

If any one of these is red, the merge button is disabled. Period.

---

## Secrets Setup

The workflows that call Claude need an API key. This key is stored as a GitHub Actions secret — never in code.

| Secret name | Used by | How to set it |
|-------------|---------|---------------|
| `ANTHROPIC_API_KEY` | `ai-review.yml`, `ai-review-applier.yml`, `ci-auto-fix.yml`, `merge-advisor.yml` | GitHub repo → Settings → Secrets and variables → Actions → New repository secret |
| `GH_PAT` | `auto-update-prs.yml` | Fine-grained PAT with Contents + Pull Requests read/write; stored same way |
| `GITHUB_TOKEN` | All workflows | Provided automatically by GitHub — no setup needed |

The `GH_PAT` vs `GITHUB_TOKEN` distinction matters for `auto-update-prs.yml`: pushes made with `GITHUB_TOKEN` are treated as bot activity and **do not trigger downstream CI**. A PAT push is treated as a human action, so CI fires automatically on the updated branch.

---

## Common Questions

**Q: Why do I see the CI checks run twice sometimes?**
A: When `auto-update-prs.yml` pushes a merge-from-main to a branch, that push triggers CI again on the updated branch. This is intentional — you want CI to pass on the code as it will look after merge, not as it looked before.

**Q: What's the difference between a check being "skipped" and "passing"?**
A: Skipped means the job ran but determined it had nothing to do (e.g., the AI review applier fires but the PR has no "Needs attention" verdict). Skipped counts as passing for branch protection purposes.

**Q: Can an agent merge without any human involvement?**
A: For P2 work orders, yes — if all checks pass, auto-merge fires and no human clicks are needed. For P1, a human must approve. The risk tier is specified in each work order.

**Q: If the agent's CI auto-fix commits code, does that create an infinite loop?**
A: No. The auto-fix commit includes `[ci-autofix]` in the message. `ci-auto-fix.yml` checks the most recent commit message at the start and exits immediately if it sees that tag. Same pattern for `[ai-review-apply]`.

**Q: CI auto-fixed my branch — now my push is rejected. What happened?**

`ci-auto-fix.yml` and `ai-review-applier.yml` push commits directly to your branch from GitHub's cloud servers. Your local machine never receives those commits automatically. When you then try to push, Git sees that the remote is ahead and rejects the push with:

```
! [rejected]  my-branch -> my-branch (non-fast-forward)
  Updates were rejected because the remote contains work you do not have locally.
```

Fix it with a rebase pull before pushing:
```bash
git pull --rebase origin <your-branch>
```

This replays your local commits on top of the auto-fix commit, then you can push normally.

**Prevention is better than recovery:** if you run `make ci-local` locally and it passes before you open the PR, CI will also pass on GitHub and the auto-fixers will never need to fire. The local gate and the remote gate run exactly the same checks.

**Q: What happens if an agent accidentally commits a secret?**
A: Gitleaks will catch it and fail CI, blocking the merge. The commit is still in the branch's history — the agent or human must remove it (via `git rebase` to drop/edit the commit) and force-push the branch. Never try to "fix" it by adding another commit — the secret is still in history.

---

## Summary: The Chain of Automation

```
You (or an agent) push code
       ↓
GitHub detects the push
       ↓
5 CI checks run in parallel (ci.yml)
       ↓
Claude reads the diff (ai-review.yml)
       ↓  
If "Needs attention" → Claude patches code (ai-review-applier.yml) → CI reruns
If CI failed → Claude patches code (ci-auto-fix.yml) → CI reruns
       ↓
Merge advisor synthesizes all signals (merge-advisor.yml)
       ↓
P2: Auto-merge fires if all checks green
P1: Human sees the advisory and clicks Merge
       ↓
Code lands on main (squash commit)
       ↓
Other open branches get updated (auto-update-prs.yml)
```

The goal of all this automation: **a human should never have to chase down "why did CI fail" or read 5 check results.** The system does the detective work and surfaces a single clear answer. Humans stay in the loop for risky changes (P1) and let the system handle safe changes (P2) end-to-end.
