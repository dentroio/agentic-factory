# WO-1111 — Security audit: Redirects and path access

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

- `services/agent-runner/draft_server.py` — CWE-22 — Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal')
- `services/agent-runner/draft_server.py` — CWE-36 — Absolute Path Traversal
- `docs/TECHNICAL_ARCHITECTURE.md` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_github_token.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_draft_server_auth.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_review_chain_untrusted.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_doc_writer.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_factory_doctor.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_factory_smoke.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_ci_local_mirrors_ci.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `tests/unit/test_factory_init.py` — CWE-601 — URL Redirection to Untrusted Site ('Open Redirect')
- `services/agent-runner/draft_server.py` — CWE-73 — External Control of File Name or Path
