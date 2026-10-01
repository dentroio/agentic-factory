# WO-1112 — Security audit: Input and output checks

**Created:** 2026-10-01
**Priority:** P1
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

- `scripts/publish_to_gdrive.py` — CWE-1050 — Excessive Platform Resource Consumption within a Loop
- `services/agent-runner/draft_server.py` — CWE-1050 — Excessive Platform Resource Consumption within a Loop
- `services/agent-runner/quality_gate.py` — CWE-1050 — Excessive Platform Resource Consumption within a Loop
- `services/agent-runner/github_client.py` — CWE-113 — Improper Neutralization of CRLF Sequences in HTTP Headers ('HTTP Request/Response Splitting')
- `services/status-site/github_client.py` — CWE-116 — Improper Encoding or Escaping of Output
- `services/agent-runner/factory_profile.py` — CWE-1286 — Improper Validation of Syntactic Correctness of Input
- `services/orchestrator/factory_profile.py` — CWE-1286 — Improper Validation of Syntactic Correctness of Input
- `services/agent-runner/config.py` — CWE-15 — External Control of System or Configuration Setting
- `services/agent-runner/orchestrator_client.py` — CWE-20 — Improper Input Validation
- `services/orchestrator/secrets_policy.py` — CWE-200 — Exposure of Sensitive Information to an Unauthorized Actor
- `scripts/memory_agent.py` — CWE-35 — Path Traversal: '.../...//'
- `services/agent-runner/prompt_builder.py` — CWE-400 — Uncontrolled Resource Consumption
- `services/status-site/main.py` — CWE-400 — Uncontrolled Resource Consumption
- `tests/unit/test_factory_doctor.py` — CWE-436 — Interpretation Conflict
- `tests/unit/test_factory_smoke.py` — CWE-436 — Interpretation Conflict
- `services/agent-runner/thread_monitor.py` — CWE-662 — Improper Synchronization
- `services/agent-runner/runner.py` — CWE-662 — Improper Synchronization
- `services/agent-runner/draft_server.py` — CWE-667 — Improper Locking
- `services/orchestrator/github_dispatch.py` — CWE-670 — Always-Incorrect Control Flow Implementation
- `services/orchestrator/github_dispatch.py` — CWE-691 — Insufficient Control Flow Management
- `services/agent-runner/draft_server.py` — CWE-732 — Incorrect Permission Assignment for Critical Resource
- `services/agent-runner/backends/claude.py` — CWE-74 — Improper Neutralization of Special Elements in Output Used by a Downstream Component ('Injection')
- `memory/auto_fix-orchestrator-alert-when-the-dispatch-queue-sta.md` — CWE-918 — Server-Side Request Forgery (SSRF)
- `services/agent-runner/runner.py` — CWE-94 — Improper Control of Generation of Code ('Code Injection')
- `services/agent-runner/prompt_builder.py` — CWE-95 — Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')
