# WO-1093 — LLM harness hardening (tool policy, memory, cost, evals)

**Created:** 2026-09-06
**Priority:** P2
**Effort:** M
**Services:** agent-runner, orchestrator, docs
**Depends on:** none
**Status:** 🟡 In Progress

---

## Problem

The factory’s LLM loop is strong on prompt framing and post-hoc gates, but still weak where it matters for “best we can do”:

1. Coding CLIs run with blanket auto-approve (`bypassPermissions` / `--yolo` / `--trust`) and no centralized, documented tool policy.
2. Repo `memory/` lessons are largely disconnected from the runner’s live `factory_memory.json` prompt path (AF-38).
3. Usage tracking records duration only — no token estimates or optional spend hold (AF-48).
4. Harness regressions (injection framing, review-chain untrusted diffs, tool-policy argv) are under-tested.
5. Operators lack a single doc describing the harness layers and remaining gaps (CD still deferred).

## Goal

A documented, testable harness: configurable tool policy with a default coding allowlist, repo memory wired into prompts, usage estimates + optional weekly budget hold, and CAPABILITY_STATUS / wiki coverage.

## Scope

**In scope:**
- Central `tool_policy.py` used by Claude / Gemini / Cursor backends
- Wire `memory/` index + recent `auto_*.md` lessons into `prompt_builder`
- Token/cost estimates on `/api/usage` + optional `USAGE_BUDGET_USD_WEEK` hold
- Wrap review-chain WO notes + git diffs with `wrap_untrusted`
- Unit tests for policy argv, memory merge, usage estimates, review prompt framing
- Docs: `docs/wiki/LLM-Harness.md`, CAPABILITY_STATUS, PROGRESS, Agent-Backends, TECHNICAL_ARCHITECTURE

**Out of scope:**
- Activating CD / self-hosted deploy runners (still documented as Open Gap)
- Replacing subscription CLIs with a fully sandboxed SDK runtime
- Splitting `orchestrator.py` (AF-45)

## Approach

- Keep unattended defaults (`bypassPermissions` / yolo / trust) so the factory still runs headlessly, but constrain Claude with an explicit `--allowedTools` allowlist by default and make every mode env-configurable.
- Load engine `memory/MEMORY.md` bullets + capped `auto_*.md` bodies into the Factory Memory section.
- Estimate tokens as `len(text)//4`; cost via crude per-backend USD rates; hold new claims when weekly estimated spend exceeds budget (0 = disabled).

## Acceptance Criteria

- [x] Claude/Gemini/Cursor run argv built via `tool_policy` (logged at run start)
- [x] `AGENT_TOOL_ALLOWLIST=off` restores unrestricted Claude tools
- [x] `build_prompt` includes repo memory lessons when `memory/` exists
- [x] `build_reviewer_prompt` wraps diff/notes as untrusted data
- [x] Usage records include `prompt_tokens_est`, `ask_tokens_est`, `estimated_cost_usd`
- [x] `USAGE_BUDGET_USD_WEEK>0` blocks further claims when over budget
- [x] Unit tests cover the above
- [x] Harness documented in wiki + CAPABILITY_STATUS
- [x] `make ci-local` passes

## Verification Steps

```bash
pytest tests/unit/test_tool_policy.py tests/unit/test_prompt_untrusted.py \
  tests/unit/test_harness_memory.py tests/unit/test_usage_tracker.py \
  tests/unit/test_review_chain_untrusted.py -v
make ci-local
```

---

## Execution

**Branch:** `wo/1093-llm-harness-hardening`
**Risk tier:** P2
**PR title:** `feat(agent-runner): WO-1093 — LLM harness hardening`
**Auto-merge:** yes (after human verifies)

**PM docs to update after merge:**
- `docs/project_management/PROGRESS.md`
- `docs/project_management/CAPABILITY_STATUS.md`

**Files to touch (estimated):**
- `services/agent-runner/tool_policy.py` (new)
- `services/agent-runner/backends/{claude,gemini,cursor}.py`
- `services/agent-runner/prompt_builder.py`
- `services/agent-runner/usage_tracker.py`
- `services/agent-runner/review_chain.py`
- `services/agent-runner/runner.py`
- `services/orchestrator/orchestrator.py` (UsageRecord + summary)
- `docs/wiki/LLM-Harness.md` (new)
- tests under `tests/unit/`

**Key constraints:**
- Do not break headless claim→run for default env
- Do not activate CD in this WO
- No secrets in logs; policy logging is mode/tool names only

### UI Verification

No UI changes — backend / API / docs only. Confirm via unit tests and `GET /api/usage` summary fields after a recorded run (or fixture).

---

## Notes / Context

See assessment canvas and Open Gaps in CAPABILITY_STATUS. CD remains a separate workstream (`docs/CD_IMPLEMENTATION_PLAN.md`).
