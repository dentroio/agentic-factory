# WO-1107 — Security audit: Privilege and access checks

**Created:** 2026-10-01
**Priority:** P0
**Status:** Draft
**Source:** Security Audit
**Audit run:** c3203fc3c8ce
**Repository:** dentroio/agentic-factory

## Problem

This draft came from a Security Audit. Antares named files in a read-only snapshot. None of these leads is a confirmed defect.

## What to Build

A person confirms or rejects each lead. A confirmed lead gets a test for the corrected behavior. Do not change product code while this order is Draft.

## Out of scope

- Implementing a lead before this order is Accepted.
- Leads that belong in another security-audit order.

## Leads

- `services/status-site/dashboard_auth.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/draft_auth.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/runner.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/config.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/prompt_builder.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/proc.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/health_agent.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/product_setup.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/worktree_guard.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/review_chain.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/backends/cursor.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/backends/gemini.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/backends/claude.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/backends/quota_state.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/quality_gate.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/tool_policy.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/orchestrator_client.py` — CWE-269 — Improper Privilege Management
- `services/orchestrator/runner_auth.py` — CWE-269 — Improper Privilege Management
- `services/orchestrator/vault_auth.py` — CWE-269 — Improper Privilege Management
- `services/agent-runner/draft_auth.py` — CWE-284 — Improper Access Control
- `services/orchestrator/orchestrator.py` — CWE-862 — Missing Authorization
- `services/orchestrator/slack_bot.py` — CWE-862 — Missing Authorization
- `services/status-site/github_client.py` — CWE-863 — Incorrect Authorization
