# Agentic Engineering Factory — Technical Architecture

## Architecture Overview

The factory has two complementary layers:

1. **GitHub Actions layer** — stateless CI/CD workflows that run on GitHub's infrastructure: AI code review, CI auto-fix, planning agent, merge advisor, post-merge verifier, observability monitor. No external servers required.

2. **Runtime Docker layer** — a local Docker Compose stack that provides the live orchestrator, status dashboard, autonomous agent runner, and collaboration tools. This layer dispatches work, monitors agents in real time, manages credentials, and receives screenshots and annotations from browser extensions.

Both layers share the same `PLAN.json` state and `docs/factory/` work order specs in the target repository.

---

## Runtime Factory (Docker Compose Stack)

### Services at a Glance

| Service | Port | Description |
|---------|------|-------------|
| `factory-status` | 8099 | Live dashboard — WO queue, PM view, thread panel, plan authoring, settings, authentication |
| `orchestrator` | 8100 | REST API for agent dispatch, claim/validate lifecycle, secrets vault, hold/unhold queue, draft proxy |
| `pr-watchdog` | (internal) | Background poller — stale PR detection, CI health, merge eligibility |
| `agent-runner` | host | Autonomous WO execution via subscription CLI backends; exposes draft server on port 8101 |

**Start all services (macOS):**

```bash
make agent-setup              # one-time: stores GitHub token, repo, Slack webhook in macOS Keychain
make up                       # reads Keychain → .env.runtime → starts Docker services
open http://localhost:8099
```

**Rebuild after code changes:**

```bash
make restart                  # rebuild all images + force-recreate containers
```

---

### Orchestrator (`services/orchestrator/`)

The orchestrator is a FastAPI application (APScheduler polling loop, port 8100) that manages the WO lifecycle, credential storage, and draft generation routing.

**Key endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Current dispatch state — active WO, agent, step |
| `/api/next` | GET | Next WO from the priority queue (respects pins, dependencies, status, hold list) |
| `/api/claim` | POST | Agent claims a WO; orchestrator marks it in-flight |
| `/api/checkin` | POST | Agent heartbeat with current step description |
| `/api/validate` | POST | Agent requests human review; returns 422 if `ci_passed=false` or `security_passed=false` |
| `/api/complete` | POST | Agent signals PR merged; WO transitions to done |
| `/api/thread/{wo}/messages` | GET / POST | Read or post messages to a WO's thread |
| `/api/thread/{wo}/stream` | GET | SSE stream — 2 s poll + keepalive |
| `/api/threads` | GET | Summary of all active WO threads |
| `/api/thread/{wo}/images/{filename}` | GET | Serve a stored annotation image |
| `/api/dispatch-codex` | POST | Trigger a Codex GitHub Actions workflow run |
| `/api/secrets` | GET | Return secrets presence map `{key: bool}` — values are never returned |
| `/api/secrets` | PUT | Merge new key/value pairs into the secrets vault |
| `/api/backends` | GET | Aggregate backend availability — API key status + agent-runner online/offline + available CLIs |
| `/api/plan/draft` | POST | Generate a WO spec from a natural-language description; routes to Anthropic API or agent-runner draft server |
| `/api/held-wos` | GET | List of WO IDs currently on hold |
| `/api/wos/{wo_id}/hold` | POST | Add a WO to the hold list — orchestrator skips it when assigning work |
| `/api/wos/{wo_id}/hold` | DELETE | Remove a WO from the hold list |
| `/api/pm/chat` | POST | PM assistant chat — context-aware, includes queue/board state; processes `[DISPATCH:WO-NNN:backend]` action tags to trigger immediate dispatch |
| `/api/pm/dispatch` | POST | Directly dispatch a WO from PM chat; sets a priority slot in `/api/next` and wakes the runner via the draft server `/dispatch` endpoint |
| `/api/pm/memory` | GET | Return the current PM session memory (`/data/pm_memory.json`) |
| `/api/pm/memory` | POST | Write a key/value pair to PM memory (keys: `preferred_backend`, `decision`, `dispatched`) |

**Secrets vault:** Credentials are stored at `/data/secrets.json` inside the orchestrator's Docker volume. They persist across restarts. The `GET /api/secrets` endpoint returns a boolean presence map — it never returns actual values. Set credentials via the factory dashboard (Settings → Authentication) or directly via `PUT /api/secrets`.

**Hold/unhold queue:** The hold list is persisted at `/data/held_wos.json`. When `get_next()` is called, any WO in the hold set is skipped. Hold state survives container restarts.

**SECONDARY_REPOS:** Set `SECONDARY_REPOS=owner/repo:path/to/wos` (comma-separated for multiple) to have the orchestrator poll additional GitHub repositories for WO specs. Secondary specs are merged into the board view and into the PM assistant's context (`_wo_status_summary()`), but they are **not dispatchable** — the dispatch queue only pulls from the primary repo's PLAN.json.

**PLAN overlay:** During each poll cycle the orchestrator computes a `_plan_overlay` — spec-file WOs from the primary repo that have an actionable status (Ready/Open/Planned) but are absent from PLAN.json. These are appended to `/api/next`'s queue at runtime, making spec-file-only WOs visible and dispatchable without requiring a PLAN.json entry.

**PM memory:** `/api/pm/memory` persists lightweight PM session state to `/data/pm_memory.json`. Tracked keys: `preferred_backend` (last chosen backend), `decision` (notable PM decisions), `dispatched` (WO IDs dispatched this session). The PM assistant reads this at the start of each chat turn to maintain continuity across container restarts.

**PM dispatch:** `POST /api/pm/dispatch` sets a priority slot consumed by the next `/api/next` call. It also calls the agent-runner draft server at `http://host.docker.internal:8101/dispatch`, which sets a `threading.Event` to wake the runner immediately instead of waiting for the next poll interval.

**Thread storage:** Per-WO conversation lives in `/data/threads/{wo}.json`. System messages are auto-posted on lifecycle transitions (claim, validate, approve, reject, complete). Image messages store base64-decoded PNGs in `/data/threads/images/{wo}/{timestamp}.png`.

**Quality gate enforcement:** `/api/validate` rejects (HTTP 422) any call where `ci_passed=false` or `security_passed=false`. This is a hard gate — agents cannot request human review for broken code.

**Draft routing:** `POST /api/plan/draft` accepts `{description, next_wo_num, backend}`. If `backend=claude-api`, it calls the Anthropic SDK directly using the key from the secrets vault. For all other backends (`claude`, `cursor`, `codex`, `gemini`), it proxies the request to the agent-runner draft server at `http://host.docker.internal:8101/api/draft` — so subscription CLI credentials never need to be in Docker.

**Notification hooks:** The orchestrator fires `notifications.py` on key lifecycle events, posting to ntfy.sh and Slack Block Kit webhooks in parallel if `NTFY_TOPIC` / `SLACK_WEBHOOK_URL` are configured (secrets vault or env vars). Both channels are no-ops if absent. Events: WO needs human review (high priority), WO complete (default), agent error/gave up (high), Dependabot PR merged (low), Dependabot conflict auto-rebased (low). `NTFY_SERVER` defaults to `https://ntfy.sh`; override to point at a self-hosted ntfy instance. Topics are auto-generated as `factory-{14 random alphanumeric chars}` by `make agent-setup` and managed via `Settings → Authentication`. `GET /api/notifications/config` returns the current topic and server (non-sensitive — needed by the Settings UI to display the subscribe URL). `POST /api/notifications/test` sends a test ping.

---

### Slack Socket Mode Bot (`services/orchestrator/slack_bot.py`)

The orchestrator runs an optional two-way Slack bot via Socket Mode. When `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are configured, the bot starts automatically alongside the orchestrator.

**How it works:**

All Slack communication is routed through the PM assistant (`/api/pm/chat`). The bot listens for:
- DMs to the bot
- `@mention` in any channel
- Follow-up messages in threads the bot has already replied in

**Block Kit rich messages:**

The bot automatically upgrades plain-text PM replies to Slack Block Kit when the reply contains structured data:

- **WO lists** — if the reply contains two or more lines matching `WO-NNN: Title [metadata]`, each WO gets a `▶ Dispatch` button inline. Clicking dispatches that WO immediately via the PM chat confirmation flow.
- **Dispatch offers** — if the reply contains a phrase like "Want me to dispatch WO-NNN to cursor?", it renders as a text block with `✅ Yes, dispatch` / `❌ Not yet` action buttons. Pronoun resolution handles "it", "this one", "that one" by scanning the full reply for the most recently mentioned `WO-NNN`.

**Persistence:**

Conversation history and active thread IDs are flushed to `/data/slack_state.json` after each message. On restart, the bot reloads this state so conversations survive container restarts. Capped at 100 threads × 50 turns per thread.

**Configuration:**

| Env var | Purpose |
|---------|---------|
| `SLACK_BOT_TOKEN` | `xoxb-...` OAuth token — issued from Slack app's OAuth page |
| `SLACK_APP_TOKEN` | `xapp-...` Socket Mode token — issued from Slack app's "App-Level Tokens" page |

Both tokens can be stored in the secrets vault (`PUT /api/secrets`) or passed as env vars. The bot is a no-op if either token is absent — it does not block orchestrator startup.

**Important:** `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` (Socket Mode conversational bot) are separate from `SLACK_WEBHOOK_URL` (one-way Incoming Webhook for lifecycle notifications). Both can be configured simultaneously.

---

### Factory Status Site (`services/status-site/`)

A FastAPI + Jinja2 server (port 8099) that renders the live dashboard, provides settings pages, and proxies credential operations to the orchestrator.

**Views:**

| Route | Purpose |
|-------|---------|
| `/` | Overview — active WO card, pending validation badge, quick stats, agent-runner online badge |
| `/pm` | PM View — velocity bar chart (8 weeks), milestone progress, program roll-up |
| `/engineering` | CI health, run history, pass rate |
| `/plan` | Milestone cards, phase progress, WO priority queue |
| `/wo/<n>` | WO detail — structured spec, live thread panel (SSE), review findings |
| `/usage` | Per-backend usage stats — runs, success rate, estimated requests |
| `/settings` | Settings hub — links to all settings pages |
| `/settings/agents` | Agent configuration (preferred backend, reviewer backends, timeout) + Anthropic key panel |
| `/settings/authentication` | GitHub token, Anthropic API key, ntfy topic/server, Slack webhook — reads presence from orchestrator secrets; ntfy topic/server fetched from `/api/notifications/config` (actual values, not booleans) |
| `/settings/plan` | Plan Authoring Hub — open WOs (with hold/unhold + edit), phases, milestones |
| `/settings/plan/wos/new` | WO creation — natural language textarea + backend selector |
| `/settings/plan/wos/draft` | POST handler — calls orchestrator draft endpoint, renders review form |
| `/settings/plan/wos` | POST handler — assembles WO data, calls `github_writer.create_wo()`, redirects with PR URL |
| `/settings/plan/wos/{wo_id}/edit` | GET — loads raw markdown from GitHub; POST — calls `github_writer.edit_wo()`, redirects with PR URL |
| `/settings/plan/wos/{wo_id}/hold` | POST — proxies to orchestrator `POST /api/wos/{wo_id}/hold` |
| `/settings/plan/wos/{wo_id}/unhold` | POST — proxies to orchestrator `DELETE /api/wos/{wo_id}/hold` |
| `/settings/plan/phases` | POST handler — calls `github_writer.add_phase()` |
| `/settings/plan/milestones` | POST handler — calls `github_writer.add_milestone()` |
| `/api/backends` | Proxies orchestrator `/api/backends` — available to the new WO form's JS |

**CORS proxy (for Oryntra Chrome extension):**

| Route | Purpose |
|-------|---------|
| `POST /api/proxy/thread/{wo}/messages` | Relay to orchestrator — allows extension to post without browser CORS block |
| `GET /api/proxy/thread/{wo}/images/{filename}` | Relay image from orchestrator to extension popup |

---

### Plan Authoring (`services/status-site/github_writer.py`)

`github_writer.py` handles all write operations from the factory UI. It operates in two modes depending on whether `LOCAL_REPO_MOUNT` is set:

**Local mode** (`LOCAL_REPO_MOUNT` set — the default for the Docker Compose stack): Writes directly to the filesystem at the mount path. The target repo is mounted at `/repos/primary` (writable). WO spec files and PLAN.json are written to disk immediately — no git commit, no PR, no round-trip. The orchestrator's next poll cycle picks them up instantly. This is the correct mode for the agentic-factory running alongside a local Clarion checkout.

**Remote mode** (no `LOCAL_REPO_MOUNT`): Falls back to the GitHub API — creates files on a branch and opens a PR. Useful for cloud deployments where no local repo mount is available.

| Function | What it does |
|----------|-------------|
| `next_wo_number()` | Scans local filesystem glob (local mode) or GitHub API (remote mode), returns max WO number + 1 |
| `render_wo_template()` | Generates the standard WO markdown spec from structured data |
| `create_wo()` | Writes spec file + PLAN.json entry; local mode = immediate disk write, remote mode = PR |
| `read_wo_file()` | Reads raw markdown from local filesystem or GitHub API |
| `edit_wo()` | Updates an existing WO spec file |
| `add_phase()` | Adds a phase to PLAN.json |
| `add_milestone()` | Adds a milestone to PLAN.json |

**WO creation flow (local mode):**
1. User describes the desired feature in the New WO textarea.
2. User selects which AI backend generates the structured spec.
3. Status site POSTs to orchestrator `/api/plan/draft`.
4. Orchestrator routes to Anthropic SDK (`claude-api`) or proxies to the agent-runner draft server (subscription CLIs).
5. AI returns a JSON object with `title`, `priority`, `effort`, `services`, `problem`, `what_to_build`, `acceptance_criteria`, `notes`.
6. Status site renders the review form with all fields pre-filled and editable.
7. User reviews, edits, and clicks Save.
8. `github_writer.create_wo()` writes the spec file and updates PLAN.json directly on disk.
9. The orchestrator picks up the new WO on its next poll cycle — typically within 5 minutes.

---

### Agent Runner (`services/agent-runner/`)

The agent runner is an autonomous loop (macOS host process, not Docker) that claims WOs from the orchestrator and executes them using a configurable AI backend. It also starts the draft server daemon that the orchestrator calls for subscription-based WO spec generation.

**`--once` flag:** Run `make agent-once` or pass `--once` to claim and complete exactly one WO then exit. Useful for testing or manually triggering a specific WO without starting the full daemon.

**Draft server (`draft_server.py`):**

A lightweight stdlib HTTP server that starts as a daemon thread inside the agent-runner process on port 8101. It exposes:

- `GET /health` — returns `{"status": "ok", "backends": {...}}` where `backends` maps each CLI name to a boolean (found in PATH or at known install path)
- `POST /api/draft` — accepts `{description, next_wo_num, backend}`, calls `backend.ask(prompt)`, returns the structured JSON spec
- `POST /dispatch` — accepts `{wo, backend}`; sets `_pending_dispatch` and fires `_wake_event` to interrupt the runner's polling sleep immediately
- `POST /api/chat` — accepts `{system, message, history, backend}`; calls `backend.ask()` with the assembled prompt; used for non-agentic PM-level queries

The orchestrator calls this server when a subscription CLI backend is selected for WO drafting or PM dispatch. This design keeps CLI credentials on the host machine — the Docker container never needs them.

**Backends** (`services/agent-runner/backends/`):

| Backend | `run()` — agentic execution | `ask()` — text Q&A |
|---------|---------------------------|---------------------|
| `ClaudeBackend` | `claude --print --dangerously-skip-permissions` | `claude --print` |
| `CursorBackend` | `agent --print --force` | `agent --print --mode ask` |
| `CodexBackend` | `codex exec -` (reads prompt from stdin) | `codex review` |
| `GeminiBackend` | `gemini --yolo -p` | `gemini -p` |

**Critical distinction:** `run()` is agentic file-editing — the agent reads code, creates files, runs commands. `ask()` is pure text Q&A — no side effects. Reviewer roles and draft server calls must use `ask()` — never `run()`.

**Execution flow per WO:**

```
Claim WO from orchestrator
    │
    ▼
Fetch WO markdown spec from GitHub
    │
    ▼
Build prompt (QUALITY_MANDATE + PROCESS_SECTION + FACTORY_API_SECTION + WO spec)
    │
    ▼
backend.run(prompt, worktree)  ← agentic execution; streams output to thread
    │
    ├── thread_monitor runs in parallel (polls every 15 s)
    │       ├── Q&A questions → backend.ask() (non-blocking)
    │       └── Directive injections → backend.inject()
    │
    ▼ (agent calls POST /api/validate)
Quality gate (quality_gate.py — runs in parallel):
    ├── make ci-local
    ├── bandit (blocking on CRITICAL/HIGH)
    ├── semgrep (blocking on ERROR only — WARNING is non-blocking)
    └── JS/TS security scan (eslint-plugin-security or regex fallback)
    │
    ▼ (gate passes)
Peer review chain (review_chain.py):
    ├── security reviewer  (blocking on CRITICAL/HIGH)
    ├── architecture reviewer  (blocking on CRITICAL)
    ├── correctness reviewer  (blocking on CRITICAL/HIGH)
    └── performance reviewer  (blocking on CRITICAL)
    │   All 4 run for P0/P1/P2; none for P3
    │
    ▼ (all reviewers sign off)
POST /api/validate (accepted — orchestrator queues for human review)
    │
    ▼ (human approves)
git commit + push + PR open + PR merge + POST /api/complete
```

**Agent mandate (injected into every prompt):**

```
MANDATORY QUALITY, SECURITY & OPTIMIZATION REQUIREMENTS
1. make ci-local — zero errors before /api/validate
2. SECURITY — no hardcoded secrets, no SQL concat, no missing require_role(),
               no XSS, no eval()/innerHTML= with dynamic input
3. PERFORMANCE — no blocking I/O in async, no unbounded queries, no N+1
4. CODE QUALITY — follow existing patterns, no premature abstractions,
                  handle all error paths, functions ≤ ~40 lines
5. Quality gate runs before validate is accepted. No bypass.
```

---

### Peer Review Chain (`services/agent-runner/review_chain.py`)

Four AI reviewers run sequentially for every non-P3 WO. Each reviewer receives:
- The WO spec (problem statement + acceptance criteria)
- The full git diff (`HEAD~1..HEAD`)
- Findings from previous reviewers (so later reviewers know what was already flagged)

Each reviewer outputs zero or more `FINDING: {...}` JSON blocks. The chain stops early if any finding exceeds the reviewer's blocking severity threshold.

| Reviewer | Blocks on |
|----------|-----------|
| security | CRITICAL, HIGH |
| architecture | CRITICAL |
| correctness | CRITICAL, HIGH |
| performance | CRITICAL |

**Backend assignment is live — not static.** At the start of each review chain run, `_fetch_agent_config()` calls `GET /api/config` on the orchestrator to read the current agent configuration. This means reviewer backend changes made in the Settings UI take effect on the next WO without any container restart.

**Force cross-LLM review (`force_cross_llm_review`).** When this flag is `true` (the default) and more than one backend is available, `_assign_reviewer_backends()` automatically rotates reviewers across backends that differ from the coding agent. Example: if Cursor wrote the code and Claude + Codex are available, the four reviewers get assigned Claude/Codex/Claude/Codex in rotation. This prevents the same model from reviewing its own output. If only one backend is available, it is used for all reviewers regardless of the flag.

When `force_cross_llm_review` is `false`, reviewer backends are assigned from the manual per-reviewer settings configured in Settings → Agents.

Configure via Settings → Agents → Reviewer Assignments. The toggle and per-reviewer dropdowns are wired to `PUT /api/config` on the orchestrator, which persists to `/data/agent_config.json` on the data volume.

---

### Agent Configuration (`/data/agent_config.json`)

Runtime agent settings are stored in `/data/agent_config.json` on the orchestrator's data volume and exposed via `GET /PUT /api/config`. This file is the authoritative source for settings that affect agent behavior — not environment variables, which require container restarts to change.

| Key | Default | Purpose |
|-----|---------|---------|
| `preferred` | `"claude"` | Which AI backend executes WOs |
| `name` | `"factory-agent"` | Display name shown in the dashboard |
| `timeout` | `7200` | Max seconds before a WO run is forcibly stopped |
| `force_cross_llm_review` | `true` | Auto-assign reviewers to different LLMs from the coding agent |
| `reviewers.security` | `"claude"` | Manual reviewer backend (used when `force_cross_llm_review` is false) |
| `reviewers.architecture` | `"claude"` | Same |
| `reviewers.correctness` | `"claude"` | Same |
| `reviewers.performance` | `"claude"` | Same |

All fields are editable from **Settings → Agents** in the dashboard. Changes take effect on the next WO the runner picks up — no container restart needed.

---

### Oryntra Chrome Extension (`dentroio/Oryntra`)

A Chrome MV3 extension that lets engineers annotate browser screenshots and post them directly to a WO thread.

**Extension components:**
- `src/content.js` — injects a canvas overlay on the active tab; circle, arrow, text tools; undo; capture button
- `src/background.js` — service worker; captures tab screenshot via `chrome.tabs.captureVisibleTab()`; composites canvas overlay onto screenshot; POSTs to factory proxy
- `src/factory.js` — shared factory API client; reads config from `chrome.storage.sync`
- `popup.html` / `popup.js` — extension popup; shows active WO and quick-post status
- `options.html` / `options.js` — settings: factory URL, WO number, author name

**Data flow:**
```
User draws annotation on page
    │
    ▼
background.js captures screenshot (base64 PNG)
    │
    ▼
POST /api/proxy/thread/{wo}/messages on status site (CORS proxy)
    │
    ▼
Orchestrator stores image → /data/threads/images/{wo}/{ts}.png
    │
    ▼
WO detail thread panel renders inline image with click-to-zoom
```

**Why a proxy?** Browser extensions cannot POST to a different origin (the orchestrator) without CORS. The status site proxy relays the request server-side, bypassing the browser's origin check.

---

### Quality Gate (`services/agent-runner/quality_gate.py`)

Four checks run in parallel:

1. **`make ci-local`** — project's full CI suite (lint, type check, tests). Exit code 1 = blocking.
2. **bandit** — Python SAST. Blocking on `CRITICAL` or `HIGH` confidence+severity findings.
3. **semgrep** — multi-language SAST. Blocking on `ERROR` severity only. `WARNING` is non-blocking (suppressed to prevent false-positive halts on stylistic patterns).
4. **JS/TS security scan** — tries `npx eslint --plugin security`; falls back to regex if not installed. Regex patterns cover: `eval()`, `innerHTML=`, `document.write()`, `new Function()`, `child_process`, hardcoded credentials. Non-blocking if no JS/TS files exist in the worktree.

`/api/validate` refuses (HTTP 422) unless `security_passed=true` is included in the body and all gate checks pass.

---

## GitHub Actions Layer

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
    |                              (same lifecycle as UI-created WOs)
    |
    | OR: WO created via factory UI (Settings → Plan → Create WO)
    |    └── AI draft → review form → github_writer.create_wo() → GitHub PR → merge
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

**Alternative:** WO specs can also be created directly from the factory dashboard (Settings → Plan → Create WO) without triggering this workflow. Both paths produce the same spec format and PR structure — the orchestrator treats them identically.

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

**Endpoint contract:** The endpoint must return JSON. It should include at minimum a `status` field. Optional but supported: `error_rate_pct`, `p99_latency_ms`, and a `services` object with named service statuses.

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

### Adding a new agent backend

1. Create `services/agent-runner/backends/yourbackend.py` implementing `run(prompt, worktree)` and `ask(prompt)`.
2. Register it in the backends `__init__.py` and in `draft_server.py`'s `_probe_backends()` function.
3. Add detection logic (path to check with `shutil.which` or a known install path).
4. The backend selector in the New WO form will show it as available once the draft server detects the CLI.

### Adding a custom GitHub Actions agent

1. Write a Python script in `scripts/` following the same pattern: parse arguments, check for `ANTHROPIC_API_KEY`, call `anthropic.Anthropic().messages.create()`, write output to `--output`, exit 0 or 1 based on outcome.
2. Create a workflow in `.github/workflows/` that installs `anthropic`, calls the script, and handles the output (post comment, create issue, open PR, etc.).
3. If the workflow should block merge, register its job `name:` as a required status check in the GitHub Ruleset.

### Replacing Claude with another model

All scripts use `model="claude-sonnet-4-6"`. Change this string in each script. The scripts use the Anthropic SDK directly — to use a different provider, replace the `anthropic.Anthropic()` client with the appropriate SDK and adjust the `messages.create()` call signature.

---

## Security Model

### Credentials and secrets

The factory uses two complementary credential stores:

**macOS Keychain** (host machine) — used by `scripts/factory-env.sh` at startup. `make agent-setup` stores `GITHUB_TOKEN`, `GITHUB_REPO`, `ANTHROPIC_API_KEY`, `NTFY_TOPIC`, `NTFY_SERVER`, and `SLACK_WEBHOOK_URL` in Keychain under service name `dentroio-factory`. The ntfy topic is auto-generated as `factory-{14 random alphanumeric chars}` — no user input required. On `make up`, these are read from Keychain and written to `.env.runtime`, which `docker compose` consumes. Credentials never touch the filesystem as plaintext files.

**Orchestrator secrets vault** (`/data/secrets.json` in the Docker volume) — set via `Settings → Authentication` in the dashboard or via `PUT /api/secrets`. The vault persists across container restarts. `GET /api/secrets` returns a boolean presence map — actual values are never returned over the API (security). Exception: `GET /api/notifications/config` returns the actual `NTFY_TOPIC` and `NTFY_SERVER` values — these are not sensitive (subscribers need to know the topic URL), and the Settings UI needs them to display the subscribe link and copy buttons. The vault is the runtime source of truth for credentials the orchestrator needs during operation: `ANTHROPIC_API_KEY` for drafting, `NTFY_TOPIC`/`NTFY_SERVER` for push notifications, and `SLACK_WEBHOOK_URL` for Slack alerts.

**GitHub Actions secrets** — `ANTHROPIC_API_KEY` must be set in GitHub repo secrets for AI review workflows to function. `GITHUB_TOKEN` is provisioned automatically per workflow run.

### What the agents can do

- Read repository files (via checkout).
- Write to PR branches (via `git push` with `GITHUB_TOKEN` write permission).
- Post PR comments and create issues (via `GITHUB_TOKEN` with `pull-requests: write` and `issues: write`).
- Call the Anthropic API with the repository's API key.
- Call the configured health endpoint (outbound HTTP from GitHub Actions runners).
- Claim and execute WOs from the orchestrator's queue.

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

**Draft server requires agent-runner running.** Subscription CLI backends (Claude, Cursor, Codex, Gemini) for WO spec drafting require the agent-runner process to be active on the host machine. If agent-runner is not running, only the `claude-api` backend is available for draft generation. The New WO form detects this and marks unavailable backends.
