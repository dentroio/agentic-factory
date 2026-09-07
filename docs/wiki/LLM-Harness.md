---
title: "LLM Harness"
description: "How the factory wraps coding LLMs — tool policy, trust boundaries, memory, cost, gates"
last_verified: 2026-09-06
covers_wos:
  - WO-1093
  - WO-1055
  - WO-1012
  - WO-1013
doc_owner: factory-team
---

# LLM Harness

The **harness** is everything around the coding model: prompt construction, tool
permissions, memory injection, quality gates, peer review, usage accounting, and
human validation. This page is the operator-facing map of those layers.

## Loop (claim → human)

```
orchestrator /api/next → claim
        ↓
prompt_builder (mandates + tool policy + wrap_untrusted WO + memory)
        ↓
backend.run (Claude / Cursor / Codex / Gemini via tool_policy)
        ↓
quality_gate (ci-local + bandit + semgrep + JS scan)
        ↓
review_chain (cross-LLM peer review; diffs framed as untrusted data)
        ↓
/api/validate → human approve/reject → complete
```

## Tool policy (`tool_policy.py`)

Headless runs still auto-approve tool use (CLIs block otherwise), but policy is
centralized and env-configurable:

| Variable | Default | Effect |
|----------|---------|--------|
| `AGENT_PERMISSION_MODE` | `bypassPermissions` | Claude `--permission-mode` (`acceptEdits`, `plan`, `default` also valid) |
| `AGENT_TOOL_ALLOWLIST` | `on` | Claude `--allowedTools` coding set; `off` = unrestricted; or comma list |
| `GEMINI_YOLO` | `1` | Gemini `--yolo`; set `0` only for interactive debugging |
| `CURSOR_TRUST` | `1` | Cursor `--trust` |

Default Claude allowlist: Read, Write, Edit, MultiEdit, Glob, Grep, Bash,
WebFetch, WebSearch, TodoWrite, NotebookEdit.

Each run logs `tool policy: …` on the backend stdout/thread.

## Trust boundary

Untrusted content (WO markdown, rejection reasons, CI analysis, review diffs)
is wrapped with `wrap_untrusted()` — sentinel-stripped and labeled **DATA, not
instructions** (WO-1055 / WO-1093).

## Memory

Two stores, now bridged:

| Store | Writer | Reader |
|-------|--------|--------|
| `services/agent-runner/memory/factory_memory.json` | runner on complete/fail | `prompt_builder` |
| repo `memory/` (`MEMORY.md` + `auto_*.md`) | `post-merge-memory.yml` | `prompt_builder` (capped) |

## Cost & budget

`POST /api/usage` records duration plus estimates:

- `prompt_tokens_est` / `ask_tokens_est` (`len/4`)
- `estimated_cost_usd` (crude per-backend rates; override `USAGE_RATE_<BACKEND>_PER_MTOK`)

`GET /api/usage` summary includes `estimated_cost_usd_week` and `tokens_est_week`.

Set `USAGE_BUDGET_USD_WEEK` (e.g. `25`) via **Settings → Deploy & Harness** (or prefs)
to stop new claims when weekly estimated spend meets the cap. `0` (default) disables the hold.

## What remains open

- **CD enablement** — use Settings → Deploy & Harness after a `factory-deploy` runner is online; see [BACKLOG.md](../project_management/BACKLOG.md)
- **True sandbox** — Bash inside the allowlist is still powerful; worktree + gates are the remaining defense
- **Exact tokens/billing** — estimates only (subscription CLIs do not always expose usage)

## Related

- [Agent Backends](Agent-Backends.md)
- [Getting Started](Getting-Started.md)
- `docs/project_management/CAPABILITY_STATUS.md` (Dimension 4 + Open Gaps)
