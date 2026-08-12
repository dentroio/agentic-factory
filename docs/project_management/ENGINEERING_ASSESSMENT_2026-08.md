# Agentic Factory — Engineering Assessment

**Date:** 2026-08-05
**Repo:** `dentroio/agentic-factory` @ `3b5baf7`
**Scope:** Full review — architecture, security, correctness, testing, CI/CD, template portability
**Audience:** Project management. Structured so work orders can be written directly from each finding.

**Method:** Manual inspection plus three parallel deep audits (security, core-loop correctness, testing/template). Codebase: 20,450 Python LOC across 49 modules, 19 active GitHub Actions workflows, 5 services, 101 unit tests.

**Evidence marking:** *Verified* = reproduced directly against the repo or the live running system. *Reported* = raised by audit, consistent with surrounding code, not independently reproduced.

---

## 1. Executive Summary

The factory is a well-conceived system with genuinely good engineering instincts, undermined by a single systemic weakness: **its gates are asserted in documentation rather than enforced by machinery.** Nearly every finding below is an instance of that pattern.

The clearest demonstration is that **all four documented merge tiers behave differently than specified.** P0/P1 requires human approval, but the branch ruleset requires zero approvals. P2 instructs agents to run `gh pr merge --auto --squash`, which cannot work because auto-merge is disabled at the repo level. P3 says commit directly to `main`, which the ruleset blocks. The AI review is simultaneously documented as advisory, coded to exit non-zero, and not registered as a required status check. And `make ci-local` — referenced 66 times across 28 files, injected into every agent prompt, and executed as a real subprocess by the quality gate — **does not exist.**

Three areas need attention before this template is given to another team or left running unattended:

1. **Authentication fails open at every network boundary.** The agent control server and the dashboard both listen on all interfaces with no authentication; the dashboard forwards LAN requests to the loopback-bound orchestrator with the bearer token attached.
2. **The work-order lifecycle has no ownership model.** Claims carry no fencing token and heartbeat loss is silently swallowed, so one orchestrator hiccup can put two agents in the same git worktree. The codebase already contains a comment acknowledging this is happening.
3. **The template cannot run itself.** The agent runner is hardcoded for a specific downstream product (Clarion), its quality gate invokes a Make target this repo lacks, and the setup wizard misreads inherited artifacts as evidence of a configured project — reproducing the same defect in every repo created from it.

Test coverage is 17% by imported statements and materially lower in reality; 41 of 49 modules have zero coverage, and 52% of the codebase sits in five untested files.

**Estimated remediation:** ~6 hours for the P0 set, ~3 weeks for full structural work. The P0 set is unusually cheap relative to its impact — most items are one to five lines.

---

## 2. Important Correction

An earlier draft finding claimed `main` has **no branch protection**, which would make every gate advisory. **This is incorrect and should not be actioned as written.**

`main` *is* protected — by a **repository ruleset** (`Protect main`, id `19625481`, active since 2026-07-23, no bypass actors), not by the legacy branch-protection API. The legacy API returns 404 for ruleset-protected branches; that 404 is not evidence of an unprotected branch. Force-push, branch deletion, and direct pushes to `main` are all genuinely blocked. *(Verified)*

The real gap is narrower and more specific — see **AF-01**.

---

## 3. Findings by Epic

Severity uses the project's own risk tiers so findings map directly to merge authority.

---

### Epic 1 — Enforcement Gaps: Merge Authority & The CI Gate

The highest-leverage epic. These findings mean the process documentation does not describe the system's actual behavior, and agents act on the documentation.

---

**AF-01 — P0/P1 human-approval requirement is unenforced**
**Severity:** P0 · **Effort:** 30 min · *Verified*

The ruleset requires a pull request but sets `required_approving_review_count: 0` and `require_code_owner_review: false`, and there is no `CODEOWNERS` file. `AGENT_PROCESS.md:17-18` states P0/P1 requires human approval "no exceptions."

**Impact:** An agent holding the `repo`-scoped PAT can open a P0 authentication or data-isolation change and merge it itself the moment the single required check (`Unit Tests`) passes. The entire risk-tier model — the system's central safety claim — is unenforced for its two highest tiers.

**Fix:** Set `required_approving_review_count: 1`. Add `CODEOWNERS` covering `.github/workflows/**`, `scripts/ai_review*.py`, `scripts/review_context.txt`, and `AGENT_PROCESS.md`. Enable `require_code_owner_review`.

---

**AF-02 — `make ci-local` does not exist, but is the mandated gate everywhere**
**Severity:** P0 · **Effort:** 3-4 h · *Verified*

Running it yields ``make: *** No rule to make target `ci-local'.  Stop.`` The root `Makefile` is a macOS operations file with no `ci-local`, `test`, `lint`, `install`, `format`, or `build` target.

It is not merely documented — it is executed:

```python
# services/agent-runner/quality_gate.py:174
rc, out = await _run(["make", "ci-local"], worktree, timeout=900, env=env)
```

Referenced 66 times across 28 files *(Reported)*, including `README.md:87` ("the contract every agent runs"), `AGENT_PROCESS.md:170-176`, `.cursor/rules/agent-process.mdc` ("Never skip"), and injected into every agent prompt at `prompt_builder.py:99` ("CI failure is BLOCKING").

**Impact:** Any agent working a WO in this repo is gated on a command that exits 2. The quality gate reads that as a hard CI failure, indistinguishable from a real test failure. The agent either burns its full retry allowance against an unfixable error, or learns to route around its own quality gate. `factory_status.py:77-86` reports `✅ Makefile` because it only checks for a literal `{{`.

**Fix:** Add a real `ci-local` target composing lint, test, type check, and build. Have `ci.yml` invoke `make ci-local` so the "CI is the contract" claim becomes structurally true.

---

**AF-03 — P2 auto-merge cannot work; P3 direct-push is blocked**
**Severity:** P1 · **Effort:** 15 min · *Verified*

`allow_auto_merge` is `false` at the repo level, so the documented `gh pr merge --auto --squash` (`AGENT_PROCESS.md:19`) fails outright. Separately, `AGENT_PROCESS.md:20` instructs P3 work to commit directly to `main`, which the ruleset's `pull_request` rule rejects.

**Impact:** Two of four documented workflows fail at the point of execution. Agents following instructions correctly hit hard errors.

**Fix:** Enable `allow_auto_merge`. Amend the P3 rule to use a PR with auto-merge rather than direct push, and update `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/agent-process.mdc` in the same change.

---

**AF-04 — AI review is described three contradictory ways**
**Severity:** P1 · **Effort:** 1 h · *Verified*

- `AGENT_PROCESS.md:332` — "advisory only, never blocks merge"
- `ai-review.yml:8` and `:116-117` — "merge is blocked", `exit 1`
- Ruleset `required_status_checks` — contains only `Unit Tests`; AI review is absent

**Impact:** The workflow's own header comment is the wrong one; the net behavior is advisory. Meanwhile the `exit 1` produces a red X on every PR that carries no authority, training reviewers and agents to ignore failing checks.

**Fix:** Pick one. If gating: add the check to the ruleset and keep `exit 1`. If advisory: remove the `exit 1` and post the verdict as a comment only. Then reconcile all three locations.

---

**AF-05 — CI gate is pytest only; four documented jobs are absent**
**Severity:** P1 · **Effort:** 4-6 h · *Reported*

`.github/workflows/ci.yml` is 31 lines with one job. No lint, type check, format check, build, secret scanning, or dependency audit. The shipped `ci.yml.template:29-82` defines four jobs the active CI dropped (`secrets`/Gitleaks, `lint`, `test`, `build`), and `ENGINEER.md:137` instructs new users to require five status checks by name — four of which don't exist here.

Additionally, `ci.yml:31` swallows pytest exit code 5:

```bash
python -m pytest tests/unit/ -v --tb=short || { ec=$?; [ $ec -eq 5 ] || exit $ec; }
```

If `tests/unit/` is emptied, renamed, or a collection error hides every test, **CI reports green.**

**Fix:** Restore the four jobs. Remove the exit-5 escape, or replace it with an explicit assertion that the collected test count exceeds a floor.

---

**AF-06 — Documentation defects that mislead agents**
**Severity:** P3 · **Effort:** 1 h · *Verified*

- `AGENT_PROCESS.md` has two sections numbered **§3** (Development Environment at line 129, Local CI Gate at line 170)
- `README.md:57` lists `docs/factory/PLAN.json` under "what's in the box"; the directory does not exist
- `{{PROJECT_NAME}}` remains unreplaced in `CLAUDE.md`, `AGENTS.md`, `AGENT_PROCESS.md`, `.cursor/rules/agent-process.mdc`, and `memory/MEMORY.md:1`
- `CLAUDE.md` instructs `pre-commit install`; no hook configuration exists, so it fails

---

### Epic 2 — Network Exposure & Authentication

Every finding here is a small change with large blast radius. **Recommend shipping AF-07 and AF-08 immediately, ahead of everything else.**

---

**AF-07 — Agent control server: no authentication, all interfaces**
**Severity:** P0 · **Effort:** 15 min · *Verified*

```python
# services/agent-runner/draft_server.py:562
server = _ThreadedServer(("0.0.0.0", DRAFT_PORT), _DraftHandler)
```

No bearer check, origin check, or loopback restriction anywhere in `_DraftHandler` (routes at `:207-238`, `:380-398`). Confirmed listening on `*:8101`, `*:8103`, `*:8104`. Exposed operations: `POST /dispatch` (claim and execute a WO), `POST /api/chat` and `POST /api/draft` (arbitrary LLM prompt), `PUT /api/agents/{name}` (rewrite launchd plist, including API keys), `POST /api/agents/{name}/start|stop`, `DELETE /api/agents/{name}`.

The dispatched agent runs with permission prompts disabled — `claude --permission-mode bypassPermissions` (`backends/claude.py:57-65`), `gemini --yolo` (`backends/gemini.py:51`). *(Reported)*

**Impact:** Anyone on the same network — office guest wifi, hotel, café — can `curl -X POST http://<host>:8101/dispatch` and begin autonomous AI code execution on the developer's machine, as the logged-in user, with Keychain access, `~/.ssh`, and a `repo`-scoped GitHub token. `PUT /api/agents/{name}` additionally allows planting an attacker-controlled API key and restarting the daemon.

**Fix:** Bind to `127.0.0.1`. Add a bearer token as defense in depth.

---

**AF-08 — Dashboard: no authentication, all interfaces, holds the orchestrator's token**
**Severity:** P0 · **Effort:** 2 h · *Verified*

`docker-compose.status.yml:22` maps `"8099:8099"` with no interface prefix — unlike `vault` (`127.0.0.1:8201:8200`) and `orchestrator` (`127.0.0.1:8100:8100`), which are correctly restricted. `services/status-site/main.py` has **42 write endpoints and zero authentication** — no middleware, no `Depends()` guard. It uses `API_SECRET` only as a *client* credential:

```python
# services/status-site/main.py:45-47
"""Authorization header for orchestrator write requests."""
return {"Authorization": f"Bearer {_API_SECRET}"} if _API_SECRET else {}
```

**Impact:** This is a confused deputy that fully defeats the orchestrator's loopback binding and bearer gate. `POST /settings/authentication` (`:1445`) accepts a form on the open port and forwards it to the orchestrator's `PUT /api/secrets` **with the token attached** (`:1477`). A LAN attacker can replace `GITHUB_TOKEN` with their own, dispatch or delete work orders, and approve pending human validations.

`README.md:35` states: *"The orchestrator port is bound to 127.0.0.1 (no LAN exposure). All write endpoints require a bearer token."* Both halves are true of the orchestrator alone and false of the system.

**Fix:** Bind 8099 to `127.0.0.1`. Add authentication middleware to the dashboard covering all mutating routes. Correct the README claim.

---

**AF-09 — Orchestrator auth fails open, exempts all reads, and allows any origin**
**Severity:** P0 · **Effort:** 2 h · *Verified*

```python
# services/orchestrator/orchestrator.py:1198-1211
API_SECRET = os.getenv("API_SECRET", "")

@app.middleware("http")
async def _bearer_auth(request: Request, call_next):
    """Require bearer token on all non-read requests when API_SECRET is set."""
    if API_SECRET and request.method not in ("GET", "HEAD", "OPTIONS"):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_SECRET}":
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

Three defects: the guard is opt-in and `API_SECRET` defaults to empty (compose defaults it to `${API_SECRET:-}`); **all GET requests are exempt unconditionally**; and `allow_origins=["*"]` permits any website the developer visits to read every GET endpoint on `localhost:8100`. The token comparison is also not constant-time.

`API_SECRET` is absent from the deployed `.env`, so authentication is currently **entirely disabled** — a credential-free `POST /api/intelligence/run` returned 200 against the live system. *(Reported)* Unauthenticated GET surface includes `/api/dispatch` (full internal state), `/api/config`, `/api/status`, `/api/pm/memory`, `/api/queue`, `/api/log/stream`.

One point in the design's favor: `GET /api/secrets` returns only booleans, never values. *(Verified)*

**Fix:** Fail closed — refuse to start when `API_SECRET` is unset. Cover GET. Replace the CORS wildcard with an explicit origin list. Use `secrets.compare_digest`.

---

**AF-10 — Vault is administered with its root token and adds no privilege boundary**
**Severity:** P1 · **Effort:** 4-6 h · *Reported*

`orchestrator.py:4174-4178` reads Vault's **root token** from a mounted volume (`docker-compose.status.yml:100`). `services/vault/auto-init.sh:56-58` writes the unseal key and root token to the same volume, so anything able to read it can both unseal and fully administer Vault. `Makefile:32-41` copies both into the macOS Keychain via `security add-generic-password -w "$$TOKEN"`, placing them in the process argument list where any local process can read them via `ps`. `services/vault/config.hcl:7` sets `tls_disable = "true"`.

**Impact:** Keychain is the real root of trust; Vault adds operational ceremony without a security boundary. Any code execution as this user recovers the root token and every secret.

**Fix:** Issue the orchestrator a scoped token with a policy limited to its secret path (AppRole or a periodic token). Keep the root token offline. Pass secrets via stdin or file rather than argv.

---

**AF-11 — GitHub PAT is a classic token with `repo` + `gist`**
**Severity:** P1 · **Effort:** 1 h · *Reported*

Live scopes: `gist, read:org, repo`. Classic, not fine-grained.

**Impact:** `repo` grants write to **every repository the owner can reach across every org**, not just this one — the factory also drives `dentroio/clarion`. It permits force-push, branch deletion, and (if the owner is an admin) modifying the very ruleset AF-01 recommends tightening. `gist` has no use anywhere in the codebase and is a ready-made exfiltration channel: one authenticated `POST /gists` publishes stolen data to a public URL. `.env.example:2` and `agent-setup.sh:34` document the requirement as `repo + read:org` and never mention fine-grained tokens.

**Fix:** Replace with a fine-grained token scoped to the specific repositories, `contents: write` + `pull_requests: write`, no `gist`. Update both docs.

---

**AF-12 — Secrets written to disk and stdout in cleartext**
**Severity:** P2 · **Effort:** 2 h · *Reported*

- `Makefile:23` / `agent-setup.sh:135` materialize `.env.runtime` at the repo root containing `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `CURSOR_API_KEY`, `GEMINI_API_KEY`, `SLACK_WEBHOOK_URL`, `API_SECRET`. Deleted at `Makefile:29`, but not if compose fails between write and delete.
- `scripts/publish_to_gdrive.py:177-180` prints `GDRIVE_REFRESH_TOKEN` and `GDRIVE_CLIENT_SECRET` in cleartext — lands in job logs if ever run in CI.
- `draft_server.py:435-444` writes API keys into launchd plists created with default permissions (`-rw-r--r--`, world-readable). `_plist_content:86-88` builds XML by f-string with no escaping, so a value containing `<` or `&` corrupts the plist.

**Positive finding worth recording:** `.env` is correctly gitignored and **has never been committed** in the repo's history. *(Verified)*

---

### Epic 3 — Prompt Injection & Privileged Workflow Execution

The distinctive risk class for an agentic system. These are not theoretical for a repo that is public and issue-driven.

---

**AF-13 — GitHub issue content interpolated into shell and JavaScript in a write-scoped workflow**
**Severity:** P0 · **Effort:** 2 h · *Reported*

`planning-agent.yml` runs on `issues: [opened, labeled]` with `contents: write` + `pull-requests: write` (`:29-32`). Untrusted issue fields are interpolated directly into a `run:` block (`:66-77`) and a `github-script` template literal (`:102`). GitHub expands `${{ }}` **before the shell sees the script**, so quoting provides no protection.

**Impact:** An issue titled with a shell breakout, triaged by a maintainer adding the `new-wo` label, executes arbitrary commands in a workflow holding `ANTHROPIC_API_KEY` and a write-scoped `GITHUB_TOKEN` — which `actions/checkout` persists into `.git/config` as a base64 extraheader, making it directly exfiltratable.

**Chained variant:** `dependabot-wo-bridge.yml:166-172` creates `new-wo`-labeled issues *programmatically* from Dependabot PR titles and bodies (`:123`, `:137`). If Dependabot were enabled (see AF-43), a typosquatted package's release notes would reach this workflow **with no human in the loop.** Same injection pattern at `:111-114`.

**Fix:** Move every `${{ github.event.* }}` and `${{ steps.*.outputs.* }}` value into an `env:` block and reference as `"$VAR"`. Affects `planning-agent.yml:66-77,102`, `ci-auto-fix.yml:203-207`, `ai-review-applier.yml:166-170`, `dependabot-wo-bridge.yml:111-114`.

---

**AF-14 — Privileged workflows execute scripts from the PR branch under review**
**Severity:** P0 · **Effort:** 3 h · *Reported*

`ci-auto-fix.yml` checks out the untrusted branch (`:118-124`) then runs `python3 scripts/ai_fix.py` **from that checkout** (`:203-210`) with `ANTHROPIC_API_KEY` in env and `contents: write` + `pull-requests: write` (`:34-38`). `ai-review-applier.yml` is identical in shape (`:134-140`, `:166`).

Because these use `workflow_run`, the *workflow definition* is safely read from `main` — but the *script it invokes* is not. A second injection exists on the same lines: `steps.context.outputs.diff_text` is the raw PR diff interpolated into the shell.

**Impact:** The eligibility gate (`agent-pr` label or bot author) blocks anonymous forks but explicitly permits the threat this system is built around — **the agent's own PRs are always eligible.** A prompt-injected agent that appends one line to `scripts/ai_fix.py` and introduces a failing test gains arbitrary code execution in a write-scoped workflow.

**Fix:** Fetch `scripts/*.py` from `main` via a second sparse checkout to a separate path and execute that copy, never the PR's.

---

**AF-15 — PM chat regex-executes merge commands parsed from LLM free text**
**Severity:** P0 · **Effort:** 4 h · *Reported*

```python
# services/orchestrator/orchestrator.py:5683-5693
pr_merge_pattern = re.compile(r"\[PR:merge:(\d+)\]")
for match in pr_merge_pattern.finditer(clean_text):
    pr_num = int(match.group(1))
    mr = await _ac.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_num}/merge",
        headers=_headers(), json={"merge_method": "squash"},
    )
```

The same prompt is fed `_pm_situational_brief()`, which injects WO titles parsed from GitHub-hosted markdown (`:4420-4421`) and queue titles from the database (`:4431`). `[DEPENDABOT:approve-merge:N]` (`:5632`) is the same hazard plus a GitHub approval.

**Impact:** A work order titled `... [PR:merge:472]`, echoed by the model, squash-merges an unreviewed PR to `main`. Combined with AF-01 (zero required approvals), nothing downstream stops it.

**Note for planning:** this cannot simply be deleted — the CLI backend path (`:5589-5605`) has no tool-calling support, so tag parsing is its only action mechanism. That is precisely why it needs an explicit allowlist and a confirmation step rather than a regex over free text.

---

**AF-16 — No trust boundary between work-order markdown and the executing agent**
**Severity:** P1 · **Effort:** 6 h · *Reported*

`prompt_builder.py:245-280` splices `wo_markdown` raw into the instruction stream — no delimiter, no "treat as data" framing, no escaping. The prompt then documents the factory API (`:133-156`) and instructs the agent to push branches and open PRs (`:159-182`). It executes under `bypassPermissions` (AF-07).

`format_prior_context` (`:190-226`) widens this by injecting `reject_reason` and thread `ci_analysis` messages — both writable through endpoints that are currently unauthenticated (AF-08, AF-09) — under a heading reading "fix the specific issues below **before doing anything else**."

The safeguard the system relies on is self-asserted, not enforced:

```
# services/agent-runner/prompt_builder.py:129
These requirements are enforced at the platform level. There is no bypass.
```

Nothing in `quality_gate.py` enforces the security clauses in that block.

**Fix:** Wrap untrusted content in explicit delimiters with data-not-instruction framing. Add output-side validation on what the agent commits rather than relying on the prompt's claim.

---

**AF-17 — The AI review gate can be bypassed three ways; nothing guards the guards**
**Severity:** P1 · **Effort:** 3 h · *Reported*

No check anywhere prevents a PR from modifying its own review machinery — no denylist in `quality_gate.py`, no workflow path guard, no `CODEOWNERS`.

1. **Injection through the diff.** `ai_review.py:161-169` wraps the diff in a fenced block; a diff line containing a closing fence escapes it. The verdict is then parsed from the model's own prose (`:204-214`).
2. **Editing the system prompt.** `load_project_context()` (`:117-127`) reads `scripts/review_context.txt` **from the PR checkout** into the system prompt (`:104-110`).
3. **Editing the reviewer.** `ai-review.yml:91` runs `scripts/ai_review.py` from the PR checkout; a PR can rewrite it to print `LGTM` and exit 0.

The risk tier that determines merge authority is likewise just text the agent writes into its own WO spec (`planning_agent.py:96-103`) with no contradiction check against the diff.

**Related:** `reviewer.py` satisfies the *human* validation gate with an AI verdict — it polls `/api/validations` and calls `POST /api/validations/{wo}/approve` (`:213`) based on a `claude -p` result parsed by prefix match (`:199-203`) with the PR diff in the prompt (`:183`). A diff instructing the reviewer to reply `APPROVE:` collapses the gate.

---

### Epic 4 — Work-Order Lifecycle Correctness

The system's core loop. Findings here explain the pattern visible in recent git history, where the last twenty commits are almost entirely fixes for silent failures and stuck-WO races.

---

**AF-18 — Claims have no ownership or fencing; two agents can share one worktree**
**Severity:** P0 · **Effort:** 8 h · *Reported*

```python
# services/orchestrator/orchestrator.py:1747-1752
@app.post("/api/checkin")
async def checkin(wo: str, agent: str, step: str = ""):
    """Agent heartbeat — update step label while working."""
    if wo not in _dispatch_state:
        raise HTTPException(status_code=404, detail=f"{wo} not claimed")
```

The `agent` parameter is never validated or stored. `/api/wos/{wo_id}/heartbeat` (`:1819`) takes no agent at all. `/api/complete` (`:2090`) never compares the caller to the claim holder. There is no fencing token or claim epoch anywhere.

Critically, **the runner never learns it lost a claim** — `orchestrator_client.py:53-59` swallows every checkin exception with `pass`.

**Impact:** If the orchestrator is unreachable longer than `CLAIM_TIMEOUT_SECONDS` (1200s), the sweep marks the WO stale, `/api/next` re-offers it, and a second runner claims it. Both runners then compute the **same deterministic worktree path** from WO number and title slug (`runner.py:264,267`) and run two agent processes plus two `git add -A` / `commit` / `push` sequences in one working tree.

This is already occurring — `reject_validation`'s own comment says so:

```
# services/orchestrator/orchestrator.py:1933-1934
# duplicates accumulate when multiple runners claim the same WO concurrently
```

**Fix:** Issue a fencing token on claim. Validate it on checkin, validate, and complete. Return 409 on mismatch, and make the runner abort immediately on 409.

---

**AF-19 — Two `run_wo` exit paths strand a WO in `in_progress`**
**Severity:** P0 · **Effort:** 2 h · *Verified*

`runner.py:763` and `:780` are bare `return`s after the `checkin` at `:758` has set the WO to `in_progress`. The existing safety net does not catch them: `main()` releases the claim only inside `except Exception` (`:832-838`), and a bare `return` unwinds cleanly.

**Impact:** The WO holds a slot against `MAX_PARALLEL_WOS` for 20 minutes until the stale sweep reclaims it, then **consumes a retry attempt on a WO that was never broken.**

The more serious variant: when **all backends fail**, `_run_with_fallback` logs and returns normally (`:520`) *(Reported)*, so `run_wo` proceeds through container rebuild, quality gate, and review chain on an **unmodified worktree**. The gate passes because nothing changed, the diff is empty, `_commit_and_push` returns `""`, and control lands in the stranding path at `:763`. A full attempt is consumed with no code written and no error surfaced.

**Fix:** Release the claim on both exits with an explicit failure reason. Treat "all backends failed" as a hard failure that short-circuits before the gate.

*Scope note:* a third exit at `:798` appears intentional — it logs "leaving in `awaiting_human` state" and the orchestrator owns that transition server-side. Scope this WO to `:763` and `:780` only.

---

**AF-20 — Two automatic quarantines are never persisted**
**Severity:** P1 · **Effort:** 15 min · *Verified*

Every hold site pairs the mutation with a write, except two:

| Line | Mutation | `_save_held()` |
|---|---|---|
| 1476 | `add` | 1477 ✅ |
| 1483 | `discard` | 1484 ✅ |
| 1810 | `add` | 1812 ✅ |
| 2026 | `discard` | 2028 ✅ |
| **1962** | `add` — auto-hold after 3 rejections | **missing** |
| **3784** | `add` — auto-hold after 2× stuck threshold | **missing** |

**Impact:** Both missing sites are the *automatic* quarantines — the ones that fire without a human watching. A WO the factory decided to stop retrying silently re-enters dispatch on the next orchestrator restart.

**Fix:** Add `_save_held()` at both sites. Two lines, highest value-per-character in this assessment.

---

**AF-21 — The retry ceiling is resettable, allowing unbounded reassignment**
**Severity:** P1 · **Effort:** 3 h · *Reported*

`MAX_RETRY_ATTEMPTS` (3) is enforced only in `/api/claim` (`:1698`), reading `attempt_count` from the dispatch record. But `health_agent.py:501` calls `DELETE /api/dispatch/{wo_id}`, which deletes the entire entry including `attempt_count` (`:1977`), then re-dispatches (`:503`). The next claim starts at 1. The `_acted` guard (`:462`) is keyed on `claimed_at`, which changes every re-claim.

`retry_dispatch` deliberately preserves the counter for exactly this reason (comment at `:2011-2012`); the health agent's path defeats it.

**Impact:** A WO can be reassigned indefinitely, each cycle costing a full agent run plus a CI cycle, never reaching the ceiling that would alert a human.

**Fix:** Persist `attempt_count` in a table keyed by WO that survives dispatch-record deletion.

---

**AF-22 — TOCTOU in the stale sweep aborts the reconciliation loop**
**Severity:** P1 · **Effort:** 3 h · *Reported*

`poll()` builds `stale_candidates` (`:3459-3470`), **awaits a GitHub PR lookup** (`:3476`), then writes back (`:3502`, `:3513`). During that await, a concurrent `DELETE /api/dispatch/{wo_id}` (`:1977`) or `POST /reset` (`:2073`) can remove the key, and both writes raise an **unhandled `KeyError` inside the scheduler job.** Same pattern at `:3576` → `:3596-3598`.

**Impact:** The exception aborts the remaining ~350 lines of `poll()` — merged-PR reconciliation, plan overlay, stuck detection, and the output snapshot all silently skip for that cycle, so `/api/next` keeps serving a stale queue. `claim_wo` is the one place this was noticed and patched locally (comment at `:1604-1609`) rather than fixed as a general invariant.

**Fix:** Re-read state after every await before mutating; skip keys that vanished. Wrap the sweep body per-WO so one failure doesn't abort the cycle.

---

**AF-23 — Blocking LLM calls on the event loop cause false stale reaps**
**Severity:** P1 · **Effort:** 4 h · *Reported*

Six synchronous Anthropic SDK calls run with no `asyncio.to_thread`: `orchestrator.py:4621`, `:5550`, `:5570` (the latter two inside a tool-round loop), and `intelligence.py:218`, `:256`. The orchestrator is single-process asyncio, so each blocks the entire loop for seconds to minutes — alongside `_save_dispatch()`'s full-file JSON plus full-table SQLite rewrite and `thread_store.append_message`'s read-modify-write.

**Impact:** A long PM chat delays heartbeat *processing*, which feeds directly into the false-positive stale reap in AF-18. The comment at `:47-54` documents repeatedly widening `CLAIM_TIMEOUT_SECONDS`; the root cause is that liveness detection shares a loop with unbounded blocking work.

**Fix:** Move all SDK calls to `asyncio.to_thread`. Consider a separate process for liveness tracking.

---

**AF-24 — Seven unbounded subprocess calls in the runner's critical path**
**Severity:** P1 · **Effort:** 3 h · *Reported*

`quality_gate._run` (`:18`) correctly wraps `communicate()` in `asyncio.wait_for`. `runner.py` does not: `:112` (`git diff`), `:290` (`git stash push`), `:300` (`bash wo_start.sh`), `:319` (`git diff`), `:353` (the `_git()` helper used for `checkout`, `status`, `add -A`, `commit`, **and `push`**), `:398` (`gh pr create`), `:418` (`gh pr list`). Also `review_chain.py:443` and `backends/claude.py:96`, `codex.py:97`, `gemini.py:108`, `cursor.py:118,136`.

**Impact:** An unauthenticated `git push` prompting for credentials, or a hung `gh` call, hangs `run_wo` forever with no heartbeat.

**Related:** the parallel SDK review path has no timeout at all (`review_chain.py:521-525` → `:278` → `:255`), while the sequential fallback *is* bounded at 120s (`:596`) — the two paths have different failure semantics. The parallel path also sends no checkin until all reviewers finish (`:552`), which is precisely the starvation its own docstring warns about (`:496-500`).

---

**AF-25 — Status is 11 ad-hoc strings with the "active" set defined four times**
**Severity:** P2 · **Effort:** 4 h · *Reported*

Eleven status values (`claimed`, `in_progress`, `awaiting_human`, `awaiting_commit`, `complete`, `rejected`, `stale`, `approved`, `pending_approval`, `preflight_held`, `retry_queued`) with no enum, no transition table, and no validation — 21 distinct `status ==` comparisons. The "is this WO active" predicate is redefined four times with **different contents**: `:1303` (includes `complete`), `:1588` and `:2372` (exclude it), `:1337` (only `claimed`/`in_progress` for capacity counting).

Adding a state requires finding all four. `retry_queued` and `stale` appear in none — intentional, but undocumented and unenforced.

Compounding this, **three independent stuck detectors** with different thresholds and remedies mutate the same records with no coordination: the stale sweep (`:3448`, 1200s), stuck detection (`:3752`, 4-48h by priority), and `health_agent.check_stuck_wos` (`:428`, `STUCK_WO_HOURS`).

**Fix:** Extract a `WOStatus` enum with one canonical `ACTIVE` set and a transition helper. Consolidate the three detectors.

---

### Epic 5 — Data Layer

**AF-26 — SQLite has no concurrency configuration and leaks a connection per call**
**Severity:** P1 · **Effort:** 4 h · *Verified*

**33 separate `sqlite3.connect(DB_PATH)` call sites** with no shared helper, and **zero occurrences of `journal_mode`, `WAL`, `busy_timeout`, `PRAGMA`, `timeout=`, or `check_same_thread` anywhere in the codebase.**

Consequences: the default rollback journal means any writer blocks all readers; the default 5s busy timeout yields `SQLITE_BUSY`, which `_db_sync_dispatch` swallows into a `print` (`:644-645`) — a lost write with no alert; and `with sqlite3.connect(...)` commits the transaction but **does not close the connection**, so all 33 sites leak a handle until GC. `_init_db` (`:490`) never commits, working only because DDL autocommits in legacy isolation mode.

**Architectural note:** the authoritative store is the Python dict `_dispatch_state` (`:111`), not SQLite. `_db_sync_dispatch` (`:600`) mirrors it by enumerating all rows, deleting the diff, and re-upserting **every** entry (`:604-643`) — so a single 90-second heartbeat rewrites the whole `runs` table plus the entire `dispatch_state.json`, synchronously, on the event loop. There are 21 mutated module-level globals; the system's state is process-local mutable memory with SQLite as write-behind.

**Fix:** One connection factory with `WAL`, a busy timeout, and explicit close. Replace the full-table rewrite with targeted upserts. Escalate write failures instead of printing.

---

**AF-27 — Non-atomic state writes can silently erase all in-flight claims**
**Severity:** P1 · **Effort:** 2 h · *Reported*

Every persistence helper uses bare `write_text` with no temp-file-plus-rename: `:192`, `:223`, `:326`, `:357`, `:364`, `:368`, and `thread.py:29`. A crash mid-write leaves truncated JSON — which the loaders then **silently reset to empty** (`:155-156`, `:160-161`, `:165-166` all `except Exception: → {}`).

**Impact:** A crash during a dispatch-state write silently erases all in-flight claims on restart. `thread.append_message` (`:32-36`) is unlocked read-modify-write, so two concurrent posts to the same WO lose one.

**Fix:** Write to a temp file and `os.replace`. Distinguish "file absent" from "file corrupt" and alert on the latter.

---

**AF-28 — Unvalidated path segments reach filesystem operations**
**Severity:** P2 · **Effort:** 2 h · *Reported*

`get_thread_image` (`:2312`) builds `DATA_DIR / "threads" / "images" / wo / filename` from two unvalidated path parameters. Traversal is currently constrained because uvicorn percent-decodes before routing, so `%2f` cannot smuggle segments past single-segment matchers — but `wo=".."` from a non-normalizing client still reaches `/data/threads/<filename>`, and the same unvalidated `wo` reaches `mkdir(parents=True)` (`:2288`) and `thread.save_thread`'s `write_text`. The safety is incidental to the router, not intentional.

**Related:** `put_secrets` (`:4206`) parses a raw `Request` and writes arbitrary user JSON straight to Vault or disk (`:4213-4221`) with no key allowlist or value validation. Same raw-body pattern at `put_agent_config` (`:3907`) and `configure_runner_agent` (`:4545`). State-mutating operations exposed as bare query parameters: `checkin` (`:1748`), `pm_dispatch_wo` (`:1405`), `write_pm_memory` (`:1415`), `auto_mark_done_wo` (`:2119`). No endpoint declares a response model, so `/api/dispatch` (`:2401`) returns the raw internal dict as its wire format.

---

### Epic 6 — Template Portability

This epic determines whether the factory can be handed to another team. Currently it cannot.

---

**AF-29 — The PM agent's identity is hardcoded to the origin project**
**Severity:** P1 · **Effort:** 8 h · *Verified*

```
# services/orchestrator/orchestrator.py:5292
You are the AI Factory PM for the Clarion project — a sharp, decisive engineering PM who knows the codebase.
```

Alongside: `CLARION_API_URL` (`:58`), a `_query_clarion_connectors()` preflight gate that blocks dispatch (`:446-481`), and tool descriptions using `src/clarion/` example paths (`:4744-4776`). `prompt_builder.py:162` instructs agents to "cd to the clarion worktree." `services/agent-runner/clarion_patterns.md` ships inside the runner.

Roughly 50 files reference Clarion or Oryntra: `doc_writer.py` (19), `doc-writer.yml` (18), `orchestrator.py` (17), `test_reservation.py` (10), `reviewer.py` (8), `prompt_builder.py` (7), `Makefile` (6), `status-site/main.py` (5).

**Impact:** A new consumer receives a project manager that believes it works on someone else's codebase, and a preflight gate that queries an API they don't run.

**Fix:** Extract identity, API URLs, and domain vocabulary into a `factory.yml` the setup wizard writes. Template the PM system prompt.

---

**AF-30 — The quality gate assumes a specific repository layout**
**Severity:** P1 · **Effort:** 8 h · *Verified*

Hardcoded paths rather than configuration: `quality_gate.py:129-133` (`frontend/node_modules`, runs `npm install`), `:309` (`^frontend/`), `:326` (`frontend/public/help/`), `:409-415` (`frontend/src/`), `:187` (skips `lab/` and `edge/`), plus `COMPOSE_PROJECT_NAME=clarion`. Also `reviewer.py:36,38,62` and `runner.py:117,339,358`.

**Impact:** For any project that isn't a Vite frontend plus Python backend, the gate silently skips checks or fails on missing paths — and silent skipping is the worse outcome, since it reports success.

**Fix:** Drive path classification from `factory.yml`. Fail loudly when a configured path is absent rather than skipping.

---

**AF-31 — The agent runner is macOS-only with no alternative**
**Severity:** P1 · **Effort:** 12 h · *Reported*

macOS-specific surface: `draft_server.py` (19 Keychain/launchd references), `agent-install.sh` (9), `health_agent.py` (7 — `launchctl` status polling with no abstraction), `Makefile` (5), `agent-setup.sh` (2), plus the plist. `make agent-install|start|stop|status` and `vault-export-keys` are all `launchctl` or `security` wrappers.

There is **no systemd unit, no `.service` file, and no Linux branch anywhere.** Windows is not mentioned. `Getting-Started.md:21` lists macOS under prerequisites with the sole mitigation *"Linux requires editing `.env` manually"* — a significant understatement.

**Impact:** The Docker services run cross-platform, but the component that *executes work orders* does not. Non-macOS users get a dashboard with no worker.

**Fix:** Abstract process supervision behind an interface with launchd and systemd implementations. Move secret storage behind a provider interface (Keychain, `libsecret`, Vault-only).

---

**AF-32 — Two conflicting work-order path conventions, disagreeing inside one service**
**Severity:** P2 · **Effort:** 4 h · *Verified*

`docs/work_orders/` holds 53 entries (52 specs plus `TEMPLATE.md`); `docs/project_management/work_orders/` holds 1 (`WO-000-template.md`). Twenty-three files reference the latter path, twelve the former. Two files in the *same directory* disagree on the default:

```python
# services/orchestrator/orchestrator.py:60
WO_PATH = os.getenv("WO_PATH", "docs/project_management/work_orders")

# services/orchestrator/wo_resolver.py:8
DEFAULT_WO_DIR = Path("docs/work_orders")
```

Only `orchestrator.py` makes it configurable; `planning_agent.py`, `merge_advisor.py`, `verifier_agent.py`, `status-site/github_writer.py`, and `scripts/wo_resolver.py` each hardcode one or the other.

**Impact:** A new user follows the documented `project_management` path and the orchestrator agrees, but the shipped resolvers scan a different directory — while the 52 examples they'd learn from live in the other path.

**Fix:** One configurable path, one default, every consumer reading it. Migrate this repo's own WOs.

---

**AF-33 — Consumers inherit the factory's own work orders and memories**
**Severity:** P2 · **Effort:** 3 h · *Verified*

Git-tracked and inherited by every consumer: **52 factory-internal WO specs**, **14 `memory/auto_*.md`** files (Clarion engineering notes), a Clarion-specific `doc-writer.yml`, and `clarion_patterns.md`. `.gitignore` excludes none of it. The setup wizard has no cleanup phase — its only deletion is its own resume state (`setup_factory.py:670`).

Because agents read `memory/` at session start, a new consumer's agents begin every conversation with a `{{PROJECT_NAME}}` heading and 14 lessons about someone else's codebase.

---

### Epic 7 — Setup Wizard Defects

These break a new consumer's repository. **AF-34 and AF-35 should ship before this template is shared.**

---

**AF-34 — The wizard corrupts working GitHub Actions workflows**
**Severity:** P0 · **Effort:** 2 h · *Verified*

`setup_factory.py:320` and `factory_status.py:96` detect placeholders with `"{{" in content` and `re.findall(r"\{\{[^}]+\}\}", content)`. Applied to `ci.yml`, this matches GitHub Actions expressions. Confirmed directly:

```
matches: ['{{ github.workflow }}', '{{ github.ref }}']
```

**Impact:** `factory_status.py` merely reports wrong (`❌ ci.yml still contains unfilled placeholders`). `setup_factory.py` is destructive — `phase_ci_workflow` prompts `Value for {{ github.workflow }}` and **writes the user's answer into the workflow file**, corrupting working CI. `phase_cd_workflow` has the identical defect against `deploy.yml.template`, which contains eight legitimate expressions including `${{ secrets.DEPLOY_SSH_KEY }}` and `${{ secrets.AWS_ACCESS_KEY_ID }}`.

**Fix:** Match only `\{\{[A-Z_]+\}\}` (the actual placeholder convention), or exclude `${{`.

---

**AF-35 — The documented setup command destroys the placeholder detection code**
**Severity:** P0 · **Effort:** 30 min · *Verified*

`ENGINEER.md:23-26` instructs:

```bash
find . -not -path './.git/*' -type f | xargs grep -l '{{PROJECT_NAME}}' | \
  xargs sed -i '' 's/{{PROJECT_NAME}}/THEIR_NAME/g'   # macOS
```

Confirmed to match `scripts/factory_status.py` and `scripts/setup_factory.py`, rewriting the string literals at `factory_status.py:68,71` and `setup_factory.py:105,122`.

**Impact:** Placeholder detection is permanently disabled, and the resulting all-green status output looks like success. The command also rewrites `ENGINEER.md`'s own documentation of the token and attempts to `sed` `.pyc` files. Separately, `sed -i ''` is BSD syntax — on GNU sed it consumes `''` as the script and fails, with no Linux alternative offered.

**Fix:** Replace with an explicit file list, or delegate entirely to `setup_factory.py`.

---

**AF-36 — Inherited artifacts cause the wizard to skip two essential phases**
**Severity:** P1 · **Effort:** 3 h · *Reported*

- **`phase_memory_seed` (`:543`)** counts non-example memory files and short-circuits. With 14 inherited `auto_*.md` present it prints `✅ Memory system has 14 file(s)` and **never asks for the user's project overview** — skipping the step that makes memory useful. `factory_status.py:195` mirrors the false green.
- **`phase_makefile` (`:264`)** returns early when a `Makefile` exists without `{{`. The inherited macOS Makefile qualifies, so the wizard prints `✅ Makefile already configured`, never copies `Makefile.template`, and the consumer never receives a `ci-local` target. The wizard then closes with `print(" 4. Run 'make ci-local' to verify the local gate works")` (`:719`).

**Impact:** The template reproduces AF-02 in every repo created from it.

**Fix:** Detect and clean inherited artifacts explicitly. Base phase decisions on required *content*, not file presence.

---

**AF-37 — Three overlapping, non-identical setup paths**
**Severity:** P2 · **Effort:** 4 h · *Reported*

`README.md:68` (ENGINEER.md persona, 11 items, "15-20 minutes"), `docs/wiki/Getting-Started.md` (7 sections; §2 alone is 13 GitHub UI actions), and `scripts/setup_factory.py` (11 phases, described in `ENGINEER.md:233` as "all 10 steps"). Realistic manual step count is 25-30, mostly browser actions. Nothing indicates which route is authoritative.

---

**AF-38 — The memory system is write-only**
**Severity:** P2 · **Effort:** 3 h · *Verified*

`scripts/memory_agent.py` and `post-merge-memory.yml` have produced 14 `auto_*.md` files. `memory/MEMORY.md` — which calls itself "Index only" and is the documented entry point — references **zero** of them, and nothing reads that directory at runtime. The runner's actual memory is a separate `services/agent-runner/memory/factory_memory.json` (`prompt_builder.py:10`).

**Impact:** An entire workflow and script produce artifacts that never feed back into any agent. The advertised learning loop does not close.

**Fix:** Either wire `memory/` into `prompt_builder`, or have the memory agent write to `factory_memory.json` and retire the duplicate path.

---

### Epic 8 — Testing & Quality Tooling

**AF-39 — 84% of modules have zero test coverage**
**Severity:** P1 · **Effort:** 3-4 weeks · *Reported*

101 tests pass in 3.78s with no flakes — but coverage is **17% of 3,231 imported statements**, and the real figure is materially lower because the `services/*` directories contain hyphens and aren't importable, so untested modules are absent from the report entirely.

**41 of 49 modules have no coverage.** The five largest — `orchestrator.py` (5,853), `status-site/main.py` (2,527), `runner.py` (864), `setup_factory.py` (728), `review_chain.py` (698) — total 10,670 lines with zero executed coverage: **52% of the codebase in five untested files.** `pr-watchdog/watchdog.py` (453) is untested despite owning automatic WO completion on PR merge.

---

**AF-40 — ~415 lines of tests mirror production logic instead of importing it**
**Severity:** P1 · **Effort:** 1 week · *Reported*

`test_file_overlap_guard.py` (178 lines) has **zero production imports** — it redefines `_parse_depends_on`, `_parse_files_likely_changed`, `_files_in_flight`, and `ACTIVE_STATUSES` inline, and its own docstring says *"Keep these in sync with the real implementation if either changes."* `test_reservation.py` (237 lines) redefines six functions; 1 of its 14 tests imports anything real.

The mirrors currently match production but nothing enforces that, and they already omit real behavior — production `_expire_stale_reservations` (`:233`) is nested per-repo, defaults a missing timestamp, deletes emptied buckets, and persists; the mirror does none of this.

**Impact:** These tests can stay green through an arbitrary production regression.

**The repo already knows how to solve this.** `test_wo_resolver_parity.py` exists precisely because a resolver copy silently drifted; it loads all three copies by file path and pins expected values so a fix that makes all three agree on the *wrong* answer still fails. Apply that technique, or extract the helpers into an importable module.

---

**AF-41 — No integration, end-to-end, or contract tests**
**Severity:** P1 · **Effort:** 2 weeks · *Reported*

`tests/` contains only `unit/`. No `conftest.py` anywhere — no shared fixtures. **No test exercises the claim→PR loop**: `orchestrator_client.py` and `runner.py` have zero coverage, and `/api/claim`, `/api/checkin`, `/api/validate`, `/api/complete` are never invoked by a test. No fixtures or mocks for the AI backends — no recorded responses, no HTTP interception layer, no fake CLI harness. No contract test between orchestrator and agent-runner; they agree on a JSON dispatch schema by convention only. `Makefile.template:42` defines a `test-integration` target pointing at a directory that doesn't exist.

**Note for the WO:** there is no `make test`, no `requirements-dev.txt`, and pytest is absent from the default interpreter — the only way to discover how to run the tests is to read `ci.yml`. Fix that as part of this work.

---

**AF-42 — No lint, format, or type configuration anywhere**
**Severity:** P1 · **Effort:** 1 week · *Verified*

Absent: `pyproject.toml`, `.pre-commit-config.yaml`, `ruff.toml`, `mypy.ini`, `setup.cfg`, `.flake8`, `tox.ini`, `.editorconfig`. `.ruff_cache/` exists, so ruff has been run ad hoc with default settings — no pinned version, no rule selection, no line-length agreement, nothing reproducible.

**This matters more than usual here.** Type hints are present and consistent across nearly every function using modern syntax (`str | None`, `dict[str, dict]`) — genuinely above average — but **nothing checks them**, so they are documentation rather than contract. Violations already exist: `_dispatch_state: dict[str, dict]` holds records whose shape varies by status, which no annotation captures. Meanwhile `prompt_builder.py:101` promises agents that "black and ruff are auto-fixed by the quality gate," and `CLAUDE.md` instructs `pre-commit install` — both referencing tooling with no configuration behind it.

---

**AF-43 — Dependencies unpinned, no lockfiles, Dependabot inactive**
**Severity:** P1 · **Effort:** 1 week · *Verified*

All 22 requirements across four services are floor constraints only (`httpx>=0.24.0`, `anthropic>=0.40.0`); the sole upper bound anywhere is `fastapi>=0.100.0,<1.0`. No `requirements.lock`, `poetry.lock`, or `uv.lock` — two Docker builds a day apart can produce different images from identical source. CI installs its own unpinned set (`pip install pytest pytest-asyncio httpx`) rather than reading any requirements file, so the tested dependency graph and the deployed one are unrelated.

**Dependabot is not active** — `.github/` contains only `dependabot.yml.template`, so GitHub never reads it. Yet `dependabot-wo-bridge.yml` (8 KB) is enabled and waiting on PRs that will never arrive, and `Getting-Started.md:57` instructs users to create a label "used by the Dependabot WO bridge." Neither the wizard nor the status script activates or checks it.

**Combined impact:** nothing in this repo tracks dependency vulnerabilities.

---

**AF-44 — No workflow has a timeout; 17 of 19 lack concurrency control**
**Severity:** P1 · **Effort:** 2 h · *Reported*

**Timeouts: 0 of 19.** Every job inherits GitHub's 6-hour default. Since `ci-auto-fix`, `ai-review-applier`, `doc-writer`, `planning-agent`, `merge-advisor`, and `observability` all make Anthropic API calls, one hung request holds a runner for six hours. **This is the cheapest fix in the assessment.**

**Concurrency: 2 of 19** (`ci.yml:10`, `ai-review.yml:31`). Sharpest gap is `observability.yml` on a `*/15` cron — runs exceeding 15 minutes stack with no cancellation. `rebase-stacked-prs.yml:71` issues `git push --force-with-lease` on every PR close with no concurrency group, so several quick merges produce overlapping force-pushes to the same stacked branches.

**Loop guards are mostly good, with two gaps.** `ci-auto-fix.yml:63` checks its marker *before any API call* and enforces a 2-attempt label ceiling — well designed. But it and `ai-review-applier.yml:54` each ignore only their **own** marker, so an `[ai-review-apply]` commit that breaks CI is a valid auto-fix trigger and vice versa; the two can ping-pong, bounded only incidentally. `post-merge-memory.yml:31` guards on `'memory(auto)'` appearing in the squash subject — **fragile**: if a maintainer edits the PR title or uses a merge commit, the guard silently stops matching and the workflow recurses.

---

### Epic 9 — Maintainability & Observability

**AF-45 — `orchestrator.py` is 5,853 lines holding seven responsibilities**
**Severity:** P2 · **Effort:** 2-3 weeks · *Verified*

95 HTTP routes, 23 Pydantic models, 33 SQLite call sites plus schema DDL and ad-hoc migrations (`:490-587`), a GitHub API client (`:2766-3205`), WO markdown parsing (`:2823-2891`), the scheduler reconciliation loop (`:3405-3866`), secrets and Vault management (`:4125-4223`), and an LLM agent with tool execution that merges PRs. Three functions dominate: `_execute_pm_tool` (~538 lines), `poll()` (~482), `pm_chat` (~437).

Together with `status-site/main.py` (2,527), that is **40% of the codebase in two files.**

Schema changes are ad-hoc `ALTER TABLE` in try/except with no `schema_version` table (`:568-582`).

**Fix:** The seams are already visible: `db.py`, `github.py`, `wo_parsing.py`, `secrets.py`, `pm_agent.py`, `routes/`. **Sequence this after AF-42** — adding ruff and mypy first makes the refactor far safer, since nothing currently checks the annotations that already exist.

---

**AF-46 — ~180 lines of privileged PR-merge logic duplicated verbatim**
**Severity:** P2 · **Effort:** 1 week · *Reported*

`_execute_pm_tool` (`:4959-5090`) and `pm_chat`'s regex tag handler (`:5631-5760`) independently implement the same four actions — Dependabot rebase, recreate, approve-merge, and PR merge with WO auto-completion. The merge-plus-auto-complete blocks at `:5005-5048` and `:5681-5732` are **character-for-character identical**, including the WO corroboration logic and log strings. Two code paths that squash-merge to `main` will drift.

**Other duplication:**

- **Slug derivation appears four times** with different rules: `wo_resolver.py:161`, `runner.py:264` (worktree name), `runner.py:343` (**git branch name**, recomputed independently), and `prompt_builder.py:325` (**no `[:40]` truncation**). Any divergence pushes to a branch that doesn't match the worktree; titles over 40 characters already diverge.
- **WO-ID normalization is scattered across ~40 sites** — 29 `startswith("WO-")` checks and 11 `replace("WO-", "")` calls. `claim_wo` spends 10 lines on it (`:1577-1586`). `reviewer.py:472` uses `str(w).lstrip("WO-")`, which strips *characters* rather than a prefix — correct only by accident.
- **GitHub API access is reimplemented five times** (`orchestrator.py:2766`, `intelligence.py:95-109`, `agent-runner/github_client.py:34`, `pr-watchdog/watchdog.py:49`, `status-site/github_writer.py`), plus 20 inline API URL literals in `orchestrator.py` that bypass `_get` and its caching entirely.
- **Agent config loading diverges:** `review_chain._fetch_agent_config` (`:296`) falls back to per-reviewer env vars; `orchestrator._load_agent_config` (`:3887`) falls back to `_DEFAULT_AGENT_CONFIG`, which has **no `documentation` reviewer** while `_DEFAULT_REVIEWER_BACKENDS` (`:287`) does.

---

**AF-47 — Logging is `print()` with no correlation IDs**
**Severity:** P2 · **Effort:** 1 week · *Verified*

81 `print` calls in `orchestrator.py`; the only modules importing `logging` are `slack_bot.py`, `doc_writer.py`, and `publish_to_gdrive.py`. No log level, timestamp, module name, or way to raise verbosity without editing code.

**No correlation IDs.** The WO ID is an implicit trace key, but there is no run or attempt ID — so log lines from attempt 1 and attempt 3 of the same WO are **indistinguishable**. The `run_steps` table (`:513-522`) has no attempt discriminator either.

**Can a failed WO be debugged from logs?** Partially, and not for the worst failures. In favor: `/api/runs/{wo_id}/history` exposes an audit trail, the runner mirrors output for SSE streaming, and thread messages give a readable per-WO narrative. Against: `_db_append_step` is called at only **four** sites (`:1739`, `:2103`, `:2221`, `:3623`), so the audit log records claim and completion but **not** `awaiting_human`, `rejected`, `stale`, `preflight_held`, or `retry_queued`; its own write failures are swallowed (`:655`); `runner.py:59-66` fires a `create_task` per log line at a 1.0s timeout and discards the result, so lines silently vanish from the UI under load. The stranding paths in AF-19 emit one line and then silence — 20 minutes later an unrelated "claim expired" alert fires from a different subsystem.

**Error handling volume:** 149 `except` blocks in `orchestrator.py`; 84 `except: pass` across orchestrator and agent-runner (171 broad excepts and ~200 `except: pass` across all of `services/` plus `scripts/`). `review_chain.py:599` catches `except (TimeoutError, Exception)` inside a retry — `TimeoutError` is already an `Exception` subclass, so this retries genuine bugs.

**Positive:** **zero bare `except:`** and **zero `shell=True`**, and all 74 `httpx.AsyncClient` constructions pass an explicit timeout.

---

**AF-48 — No token or cost accounting**
**Severity:** P2 · **Effort:** 1 week · *Verified*

`usage_tracker.py` is 28 lines recording run outcomes and duration — not tokens, not spend. For a system whose per-WO cost is its dominant operating expense, there is no way to answer "what did this feature cost," no per-backend spend comparison, and no budget cap. Combined with AF-21 (resettable retry ceiling), a single WO can consume unbounded spend with no alert.

---

## 4. What Is Working Well

Recorded so this is not read as a rewrite recommendation. The engineering instincts are sound; the gap is enforcement, not care.

- **No `shell=True`, no `os.system`/`os.popen`, no `eval`/`exec` on untrusted input.** Every subprocess call is list-form. The most common injection vector in a system like this is closed by construction.
- **`.env` correctly gitignored and never committed** across full history.
- **All 74 HTTP client constructions pass explicit timeouts.**
- **Zero bare `except:`** clauses.
- **Consistent modern type hints** across nearly every function.
- **`ci-auto-fix.yml`'s loop guard is genuinely well designed** — marker check before any API call, agent-PR restriction, and a hard label-tracked attempt ceiling.
- **The stale sweep checks GitHub for an existing PR before discarding work** (`:3449-3457`) specifically to avoid destroying finished work.
- **`test_wo_resolver_parity.py` is exemplary** — it loads three duplicate copies by file path and pins expected values, so a fix making all three agree on the *wrong* answer still fails. This is the pattern the rest of the suite should adopt.
- **Comments explain *why*, not *what*** — the CI-lock PID reclaim (`quality_gate.py:150-158`) documents a real 14-hour outage; `orchestrator.py:2029-2036` explains why a notify block is deliberately dead code. This is unusually good institutional memory.
- **Notification hygiene is consistent** — `notify_factory_alert` is used for retry exhaustion, preflight holds, and stale claims, with evident care about alert *reachability*.

---

## 5. Recommended Sequencing

### Wave 1 — Ship this week (~6 hours, mostly one-liners)

Ordered by value per unit effort. Every item is independently shippable.

| ID | Finding | Effort |
|---|---|---|
| AF-07 | Bind draft server to `127.0.0.1` | 15 min |
| AF-20 | Add `_save_held()` at `:1962`, `:3784` | 15 min |
| AF-03 | Enable `allow_auto_merge`; fix P3 rule | 15 min |
| AF-01 | Required approvals → 1; add `CODEOWNERS` | 30 min |
| AF-35 | Remove destructive sed from `ENGINEER.md` | 30 min |
| AF-44 | `timeout-minutes` on all 19 workflows | 2 h |
| AF-19 | Release claim at `runner.py:763`, `:780` | 2 h |
| AF-08 | Bind 8099 to loopback; dashboard auth | 2 h |
| AF-09 | `API_SECRET` fail closed; cover GET; scope CORS | 2 h |
| AF-34 | Fix placeholder regex | 2 h |

### Wave 2 — Next sprint (~2 weeks)

AF-02 (`ci-local`), AF-04 (AI review verdict), AF-05 (restore CI jobs), AF-13/AF-14 (workflow injection), AF-15 (merge-tag executor), AF-42 (lint/type config), AF-43 (pins + Dependabot), AF-26/AF-27 (SQLite + atomic writes), AF-21 (retry ceiling), AF-24 (subprocess timeouts).

### Wave 3 — Following sprint (~3 weeks)

AF-18 (lease fencing — the largest correctness win), AF-22/AF-23 (TOCTOU, event loop), AF-16/AF-17 (prompt trust boundary, review guards), AF-10/AF-11 (Vault scoping, fine-grained PAT), AF-25 (status FSM), AF-40 (convert mirrored tests).

### Wave 4 — Quarter (~4-6 weeks)

AF-29/AF-30/AF-31 (`factory.yml` extraction, cross-platform runner — the epic that makes this genuinely reusable), AF-45 (split `orchestrator.py`, **after AF-42**), AF-46 (de-duplicate), AF-39/AF-41 (coverage, integration tests), AF-47/AF-48 (observability, cost).

---

## 6. Suggested Work Order Grouping

Sixteen work orders covering all 48 findings, sized for single-agent execution.

| WO | Title | Findings | Tier | Effort |
|---|---|---|---|---|
| 1 | Bind all local services to loopback | AF-07, AF-08 | P0 | 3 h |
| 2 | Fail-closed auth on orchestrator and dashboard | AF-09 | P0 | 3 h |
| 3 | Fix claim release and hold persistence | AF-19, AF-20 | P0 | 3 h |
| 4 | Align ruleset with documented merge tiers | AF-01, AF-03, AF-04 | P0 | 2 h |
| 5 | Harden workflow inputs and script provenance | AF-13, AF-14 | P0 | 5 h |
| 6 | Repair setup wizard placeholder handling | AF-34, AF-35, AF-36 | P0 | 5 h |
| 7 | Add a real `ci-local` target and restore CI jobs | AF-02, AF-05 | P1 | 8 h |
| 8 | Workflow timeouts and concurrency groups | AF-44 | P1 | 2 h |
| 9 | Lint, type, and format configuration + pre-commit | AF-42, AF-06 | P1 | 1 wk |
| 10 | Pin dependencies and activate Dependabot | AF-43 | P1 | 1 wk |
| 11 | SQLite connection factory, WAL, atomic writes | AF-26, AF-27, AF-28 | P1 | 1 wk |
| 12 | Claim lease with fencing tokens | AF-18, AF-21, AF-22, AF-23, AF-24, AF-25 | P1 | 2 wk |
| 13 | Prompt trust boundary and review-guard hardening | AF-15, AF-16, AF-17 | P1 | 1.5 wk |
| 14 | Secret scoping: fine-grained PAT and Vault policy | AF-10, AF-11, AF-12 | P1 | 1 wk |
| 15 | Extract `factory.yml`; de-Clarion; cross-platform runner | AF-29, AF-30, AF-31, AF-32, AF-33, AF-37, AF-38 | P1 | 4 wk |
| 16 | Test foundation: fixtures, integration, real assertions | AF-39, AF-40, AF-41 | P1 | 4 wk |

Structural refactors (AF-45, AF-46, AF-47, AF-48) should be scheduled after WO-9 lands, since static checking makes them substantially safer.

---

## 7. Closing Assessment

The factory's architecture is sound and its ambition is well-matched to what current agent tooling can do. The problems are not conceptual — they are the predictable result of a system that grew by fixing production incidents without an enforcement layer to catch the next class of failure. Recent git history bears this out: the last twenty commits are almost entirely fixes for silent failures and stuck-WO races, each found the expensive way.

The single highest-leverage change is not on any individual line. It is closing the loop between what the documentation asserts and what the system enforces — required checks that match the risk tiers, a `ci-local` that exists and runs in CI, a type checker that reads the annotations already written, and tests that import the code they claim to cover. Wave 1 buys most of the safety for about six hours of work. Wave 4 is what turns a working internal tool into a template another team can actually adopt.
