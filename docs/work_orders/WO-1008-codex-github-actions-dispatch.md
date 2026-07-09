# WO-1008 — Codex GitHub Actions Dispatch: Cloud Agent Path

**Status:** ✅ Complete
**Priority:** P2
**Effort:** M (1 day)
**Services:** orchestrator (new endpoint + module)
**Depends on:** WO-365, WO-1007

---

## Problem

The local agent-runner (WO-365) requires Docker, a worktree, and a developer
machine running Claude / Cursor / Codex. P3 / docs-only WOs — those with
`services: none` — don't need any of that. They just need a process that:

1. Gets the WO spec
2. Runs a code agent in some environment
3. Opens a PR

GitHub Actions provides that environment for free, and Codex runs well in CI.

---

## What Was Done

### `github_dispatch.py` — new module in `services/orchestrator/`

`trigger_codex_workflow(repo, wo_id, slug, ref)` POSTs a `workflow_dispatch`
event to the target repo:

```
POST /repos/{repo}/actions/workflows/codex-dispatch.yml/dispatches
{
  "ref": "main",
  "inputs": { "wo_id": "WO-362", "wo_slug": "sync-in-app-help" }
}
```

Returns `True` on HTTP 204 (queued), `False` on any error.

### New orchestrator endpoint — `POST /api/dispatch-codex`

```json
{ "wo": "WO-362", "repo": "dentroio/clarion", "ref": "main", "slug": "sync-in-app-help" }
```

1. Checks for existing claim — 409 if already active
2. Pre-claims the WO as `codex-gh-actions / github-actions`
3. Triggers `workflow_dispatch`; on failure, rolls back the claim and returns 502
4. Returns `{"ok": true, "wo": "WO-362", "repo": "...", "agent": "codex-gh-actions"}`

The orchestrator's existing poll loop then detects the branch and PR automatically
(no callback needed — it queries the GitHub API every `POLL_INTERVAL` seconds).

### `.github/workflows/codex-dispatch.yml` in `dentroio/clarion`

Triggered by `workflow_dispatch` with `wo_id` + `wo_slug` inputs:

| Step | What happens |
|------|-------------|
| Checkout + git config | Fresh clone, authorship as "Factory Codex" |
| Create branch | `wo/{wo_id}-{wo_slug}` |
| Fetch WO + build prompt | Python inline — fetches markdown via GitHub API, adds quality mandate |
| Install Codex | `npm install -g @openai/codex` |
| Run Codex | `codex exec -p "$PROMPT"` |
| Detect changes | `git diff --cached` after `git add -A` |
| Commit + push | Only if Codex made changes |
| Open PR | `gh pr create` with WO reference in title and body |

**Required secrets in the target repo:**
- `OPENAI_API_KEY` — for Codex
- `GITHUB_TOKEN` — provided automatically by Actions

---

## New env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `CODEX_WORKFLOW_FILE` | `codex-dispatch.yml` | Workflow filename in the target repo |

---

## Usage

```bash
# Via curl
curl -X POST http://localhost:8100/api/dispatch-codex \
  -H "Content-Type: application/json" \
  -d '{"wo":"WO-362","slug":"sync-in-app-help"}'

# Via status site (future: PM View dispatch button)
# The orchestrator auto-selects this path when WO spec has "services: none"
```

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `POST /api/dispatch-codex {"wo":"WO-X"}` triggers `workflow_dispatch` on the repo |
| 2 | WO is pre-claimed as `codex-gh-actions` — 409 if already active |
| 3 | On workflow_dispatch failure (bad repo, workflow not found) → 502, claim rolled back |
| 4 | Clarion has `codex-dispatch.yml` workflow that creates branch, runs Codex, opens PR |
| 5 | Orchestrator poll loop detects the new branch/PR without any callback |

---

## Execution

- **agentic-factory branch:** `wo/367-codex-dispatch`
- **clarion branch:** `wo/367-codex-workflow` (workflow file)
- **Risk tier:** P2 — new API endpoint + new GH Actions workflow (non-breaking)
