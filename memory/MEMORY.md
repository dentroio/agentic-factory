# Agentic Factory Memory

## Project Overview
- [Project overview and stack](project_overview.md) — repo path, language/framework, architecture, version

## Team & Collaboration
- [User profile](user_profile.md) — role, expertise, collaboration preferences

## Active Programs
<!-- Add entries as programs/epics are kicked off -->
<!-- Format: [Short title](file.md) — one-line hook with current status -->

## Architecture Decisions
<!-- Add entries when significant architecture choices are made -->
<!-- Format: [Decision title](decision_NAME.md) — what was decided and why -->

## Feedback & Working Style
- [dict.get() default trap](auto_fix-status-site-factory-500-null-claimed-at-breaks.md) — `dict.get(key, default)` does NOT apply the default when the key exists with value `None`, only when the key is absent

## Known Invariants
- [product-setup-host-only-and-path-guard](auto_wo1091.md) — agent-runner (not orchestrator/Docker) owns product wiring; LOCAL_REPO_PATH is restricted to under $HOME unless overridden
- [wo-resolver-docs-scope-title-not-completion](auto_wo547.md) — docs(...)/chore(...)-scoped PR titles never complete a WO by title mention alone in wo_resolver.py's completion logic
- [wo-spec-section-validation-sync](auto_docs-factory-align-work-order-wording-317.md) — Work order template section headings must stay in sync across planning_agent.py, github_writer.py, and orchestrator.py's SPEC_REQUIRED_SECTION_GROUPS
- [factory-profile-duplicated-across-services](auto_feat-engine-factory-yaml-profile-remove-clarion-ha.md) — factory_profile.py is copy-pasted identically into services/agent-runner and services/orchestrator (no shared package) — must be updated in both places
- [watchdog-auto-approves-trusted-branch-workflows](auto_fix-watchdog-status-site-auto-approve-trusted-work.md) — pr-watchdog auto-approves GitHub Actions runs for branches matching common prefixes, bypassing manual "Approve and run" gating
- [runner-admin-endpoints-master-only](auto_wo1088_2.md) — Runner registration/revocation endpoints require master-level auth via request.state.is_master
- [runner-auth-and-identity-binding](auto_wo1090.md) — Per-runner authentication, SHA-256 token hashing, zero-trust identity verification on claim/checkin/complete, and master-only admin endpoints
- [orchestrator-multi-repo-scoping](auto_wo1089.md) — Multi-repo dispatch in orchestrator.py — repo config precedence and per-repo isolation of conflict guards
- [orchestrator-history-route-ordering-and-failure-isolation](auto_wo1088.md) — FastAPI route ordering constraint for /api/history/* endpoints and best-effort audit trail recording pattern in orchestrator.py
- [factory-agent-cursor-runs-uncommitted-checkout](auto_wo1086.md) — factory-agent-cursor LaunchAgent executes runner.py directly from a shared local checkout with no Docker isolation — uncommitted local edits are already live in production
- [orchestrator-silent-stall-detection](auto_fix-orchestrator-alert-when-the-dispatch-queue-sta.md) — Orchestrator dispatch queue can silently stall (all WOs held, nothing active) for hours with no alert — new health/stall detectors must mirror /api/next's exact filter and use one-alert-per-episode in-memory state.
- [orchestrator-proxy-routes-require-auth-header](auto_wo1037.md) — All status-site proxy calls to the orchestrator must include _orch_headers() or they silently 401
- [github-action-required-runs-are-not-cleaned-up](auto_feat-watchdog-surface-github-actions-runs-waiting-.md) — GitHub Actions runs stuck in action_required state persist forever even after the PR closes or gets superseded, and omit pull_requests field

Auto-extracted by `memory_agent.py` after merges — one lesson per PR, written but never indexed here until 2026-08-05 (the gap itself was AF-38 in the 2026-08 engineering assessment). Two entries below are marked superseded where a later fix changed the behavior they describe.

- [ANTHROPIC_MODEL default is hardcoded in many places](auto_chore-doc-writer-bump-default-model-to-claude-sonn.md) — not just doc_writer.py; no single env var override covers .env, docker-compose, and workflow inputs together
- ~~[Orchestrator auth exempts all GET reads](auto_feat-factory-vault-service-api-secret-auth-for-orc.md)~~ — **superseded 2026-08-05, AF-09**: auth is now required on every method, not just writes
- [claude CLI subprocess invocation invariant](auto_fix-agent-runner-cursor-py-s-claude-cli-fallback-a.md) — every subprocess call to the `claude` CLI must pin `--model AGENT_MODEL` and use `env=_subscription_env()`
- [agent-runner is native-only, no Docker path](auto_fix-agent-runner-remove-docker-path-entirely-fix-n.md) — runs only via launchd; CLI subprocesses must not inherit `ANTHROPIC_API_KEY`
- [claude CLI must strip ANTHROPIC_API_KEY](auto_fix-agent-runner-strip-anthropic-api-key-from-all-.md) — every subprocess call must use `_subscription_env()` + explicit `--model`, or it silently bills metered API instead of the subscription
- [ai_review.py max_tokens undersized](auto_fix-ci-ai-review-py-max-tokens-still-too-low-for-a.md) — bumped twice already (1500→4096→8192) for truncation on normal-sized PRs; if a review looks cut off, this is why
- [Anthropic text-block extraction pitfall](auto_fix-extract-the-text-block-correctly-not-content-0.md) — never use `message.content[0].text`; scan for the text-type block instead (a missing case of this crashed `merge_advisor.py` and `memory_agent.py` — both fixed 2026-08-05)
- ~~[Orchestrator auth middleware guards non-GET only](auto_fix-peer-review-now-respects-the-dashboard-configu.md)~~ — **superseded 2026-08-05, AF-09**: same fix as above, duplicate lesson from a different PR
- [Planned-WO board display vs. dispatch eligibility are decoupled](auto_fix-status-site-show-planned-wos-in-open-board-col.md) — showing "planned" WOs in the open board column does NOT affect which WOs agents actually pick up
- [Stuck detection uses last_seen, not step changes](auto_wo1029.md) — a long-running step (test run, compile) needs an explicit `/heartbeat` call every ~5min or it auto-holds after 2× the priority threshold, even though the agent is working fine
- [WO resolution: branch is authoritative, title is fallback](auto_wo1041.md) — `extract_wo_from_branch` requires the bare ref, no `origin/` prefix or `refs/heads/`
- [WO resolution from title alone is unsafe for destructive actions](auto_wo1042.md) — only branch-corroborated matches may trigger auto-complete or ghost cleanup (this is also why `mark-wo-done-on-merge.yml` in the Clarion repo needs the same fix — it currently trusts title alone, see 2026-08-05 conversation)
- [WO number reservation is not truly atomic](auto_wo1043.md) — relies on single-threaded FastAPI event-loop ordering, not a real lock, under concurrent HTTP requests

---

_Index only — keep each entry under ~150 chars. All detail lives in topic files._
_Files in this directory persist across Claude Code conversations._
