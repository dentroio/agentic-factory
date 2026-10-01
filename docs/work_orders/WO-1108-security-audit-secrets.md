# WO-1108 — Security audit: Secrets, hashing, and transport

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

- `services/agent-runner/factory_profile.py` — CWE-295 — Improper Certificate Validation
- `services/orchestrator/factory_profile.py` — CWE-295 — Improper Certificate Validation
- `tests/unit/test_factory_init.py` — CWE-295 — Improper Certificate Validation
- `scripts/factory_init.py` — CWE-295 — Improper Certificate Validation
- `services/orchestrator/secrets_policy.py` — CWE-312 — Cleartext Storage of Sensitive Information
- `services/orchestrator/orchestrator.py` — CWE-312 — Cleartext Storage of Sensitive Information
- `services/agent-runner/orchestrator_client.py` — CWE-319 — Cleartext Transmission of Sensitive Information
- `services/agent-runner/backends/cursor.py` — CWE-328 — Use of Weak Hash
- `services/agent-runner/backends/codex.py` — CWE-328 — Use of Weak Hash
- `services/agent-runner/backends/claude.py` — CWE-328 — Use of Weak Hash
- `services/agent-runner/backends/gemini.py` — CWE-328 — Use of Weak Hash
- `services/agent-runner/backends/quota_state.py` — CWE-328 — Use of Weak Hash
- `services/agent-runner/backends/base.py` — CWE-328 — Use of Weak Hash
- `services/status-site/github_client.py` — CWE-522 — Insufficiently Protected Credentials
- `services/agent-runner/product_setup.py` — CWE-798 — Use of Hard-coded Credentials
