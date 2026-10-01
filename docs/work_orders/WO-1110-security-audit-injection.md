# WO-1110 — Security audit: Command and query construction

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

- `services/agent-runner/backends/claude.py` — CWE-77 — Improper Neutralization of Special Elements used in a Command ('Command Injection')
