# WO-1109 — Security audit: Sensitive data in logs

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

- `scripts/publish_to_gdrive.py` — CWE-117 — Improper Output Neutralization for Logs
- `scripts/doc_writer.py` — CWE-117 — Improper Output Neutralization for Logs
- `scripts/observability_agent.py` — CWE-532 — Insertion of Sensitive Information into Log File
- `tests/unit/test_scoped_vault_token.py` — CWE-532 — Insertion of Sensitive Information into Log File
- `tests/unit/test_doc_writer_empty.py` — CWE-532 — Insertion of Sensitive Information into Log File
- `docs/wiki/Agent-Backends.md` — CWE-532 — Insertion of Sensitive Information into Log File
- `docs/work_orders/WO-1057-scoped-vault-token.md` — CWE-532 — Insertion of Sensitive Information into Log File
- `memory/auto_feat-factory-vault-service-api-secret-auth-for-orc.md` — CWE-532 — Insertion of Sensitive Information into Log File
